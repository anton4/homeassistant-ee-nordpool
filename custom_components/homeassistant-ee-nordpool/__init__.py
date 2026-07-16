import logging
import async_timeout
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
import homeassistant.util.dt as dt_util
from .const import DOMAIN, OPTION_NONE
from .coordinator import NordpoolCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "button", "select", "number", "switch"]
EMHASS_URL = "http://localhost:5001/action"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = NordpoolCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(entry.add_update_listener(update_listener))

    session = async_get_clientsession(hass)

    def get_extend_days():
        """Extra forecast days currently in play (0 unless a forecast source is selected)."""
        active = getattr(coordinator, 'forecast_source', OPTION_NONE) != OPTION_NONE
        return coordinator.extend_fi_days if active else 0

    def get_max_lags():
        """Calculates the absolute maximum prediction horizon to prevent ML lag crashes."""
        max_horizon = 192 + (get_extend_days() * 96)
        return max_horizon

    def get_delta_days():
        """Calculates the max daily horizon limit to prevent EMHASS from clipping the arrays."""
        return 2 + get_extend_days()
        
    def get_history_needed():
        """Ensures EMHASS pulls enough days of history to satisfy the ML lags."""
        auto_lags = get_max_lags()
        return max(7, int((auto_lags / 96) + 2))

    def get_split_date_delta():
        """Converts lags into hours so the test dataset length matches the prediction horizon."""
        hours = int(get_max_lags() / 4)
        return f"{hours}h"

    async def call_emhass(service_name: str, endpoint: str, payload: dict, timeout: int) -> dict:
        """POST to EMHASS, capture the response, and record the outcome for the debug sensors."""
        start = dt_util.utcnow()
        http_code = None
        body = None
        try:
            async with async_timeout.timeout(timeout):
                resp = await session.post(f"{EMHASS_URL}/{endpoint}", json=payload)
                http_code = resp.status
                try:
                    body = await resp.json()
                except Exception:
                    body = await resp.text()
                resp.raise_for_status()
            duration = (dt_util.utcnow() - start).total_seconds()
            _LOGGER.info("EMHASS %s succeeded (HTTP %s) in %.1fs.", service_name, http_code, duration)
            await coordinator.record_emhass_run(
                service_name, status="success", http_code=http_code,
                response=body, payload=payload, duration=duration
            )
            return {"status": "success", "http_code": http_code, "payload_sent": payload, "response": body}
        except Exception as e:
            duration = (dt_util.utcnow() - start).total_seconds()
            _LOGGER.error("EMHASS %s failed: %s", service_name, e)
            await coordinator.record_emhass_run(
                service_name, status="error", http_code=http_code,
                response=body, payload=payload, error=str(e), duration=duration
            )
            return {"status": "error", "error_message": str(e), "http_code": http_code, "response": body}

    async def handle_fit_ml_model(call: ServiceCall) -> dict:
        auto_lags = get_max_lags()
        payload = {
            "historic_days_to_retrieve": call.data.get("historic_days_to_retrieve", 30),
            "model_type": "load_forecast",
            "var_model": "sensor.house_power_without_deferrable",
            "sklearn_model": call.data.get("sklearn_model", "KNeighborsRegressor"),
            "num_lags": auto_lags,
            "split_date_delta": get_split_date_delta()
        }
        return await call_emhass("fit_ml_model", "forecast-model-fit", payload, 3600)

    async def handle_tune_ml_model(call: ServiceCall) -> dict:
        auto_lags = get_max_lags()
        payload = {
            "historic_days_to_retrieve": call.data.get("historic_days_to_retrieve", 30),
            "model_type": "load_forecast",
            "var_model": "sensor.house_power_without_deferrable",
            "sklearn_model": call.data.get("sklearn_model", "KNeighborsRegressor"),
            "num_lags": auto_lags,
            "split_date_delta": get_split_date_delta(),
            "n_trials": call.data.get("n_trials", 10)
        }
        return await call_emhass("tune_ml_model", "forecast-model-tune", payload, 7200)

    async def handle_predict_ml_model(call: ServiceCall) -> dict:
        payload = {
            "model_type": "load_forecast",
            "var_model": "sensor.house_power_without_deferrable",
            "num_lags": get_max_lags(),
            "historic_days_to_retrieve": get_history_needed(),
            "model_predict_publish": True,
            "model_predict_entity_id": "sensor.p_load_forecast_custom_model",
            "model_predict_unit_of_measurement": "W",
            "model_predict_friendly_name": "Load Power Forecast ML"
        }
        return await call_emhass("predict_ml_model", "forecast-model-predict", payload, 180)

    async def handle_run_mpc_optim(call: ServiceCall) -> dict:
        np_state = hass.states.get('sensor.nordpool_ee_prices_prices_from_now')
        import_prices = np_state.attributes.get('import_prices', []) if np_state else []
        export_prices = np_state.attributes.get('export_prices', []) if np_state else []
        timestamps_left = np_state.attributes.get('timestamps_left', 0) if np_state else 0

        sc_state = hass.states.get('sensor.nordpool_ee_prices_solcast_forecast_15min')
        pv_forecast = list(sc_state.attributes.get('values', [])) if sc_state else []

        ev_soc_state = hass.states.get('sensor.ev6_battery_soc')
        soc_init = (float(ev_soc_state.state) / 100.0) if ev_soc_state else 0.5

        target_soc_state = hass.states.get('input_number.emhass_target_soc')
        soc_final = (float(target_soc_state.state) / 100.0) if target_soc_state else 0.8

        ev_enabled = hass.states.is_state('input_boolean.ev_charging_enabled', 'on')
        ev_force = hass.states.is_state('input_boolean.ev_force_continuous_charging', 'on')

        nominal_power = [11000] if ev_enabled else [0]
        
        op_hours_state = hass.states.get('sensor.ev_operating_hours')
        op_hours = [float(op_hours_state.state)] if ev_enabled and op_hours_state else [0]

        timesteps_state = hass.states.get('sensor.ev_charging_timesteps')
        timesteps = [int(float(timesteps_state.state))] if ev_enabled and timesteps_state else [0]

        load_cost = [round(p, 4) for p in import_prices]
        prod_price = [round(p, 4) for p in export_prices]

        # The lists above are anchored to the slot containing "now" ([0] = the
        # current slot). EMHASS with method_ts_round=nearest anchors its grid
        # to the NEAREST quarter-hour, so a run in the second half of a slot
        # plans from the NEXT slot. Drop the current slot's element in that
        # case, or every series lands one grid row late and the whole plan
        # (and the published sensors) permanently lags one slot behind.
        now = dt_util.now()
        if (now.minute % 15) * 60 + now.second > 450:
            load_cost = load_cost[1:]
            prod_price = prod_price[1:]
            pv_forecast = pv_forecast[1:]
            timestamps_left = max(0, int(timestamps_left) - 1)

        payload = {
            "load_cost_forecast": load_cost,
            "prod_price_forecast": prod_price,
            "prediction_horizon": timestamps_left,
            "pv_power_forecast": pv_forecast,
            "load_forecast_method": "mlforecaster",
            "var_model": "sensor.house_power_without_deferrable",
            "num_lags": get_max_lags(),
            "historic_days_to_retrieve": get_history_needed(),
            "delta_forecast_daily": get_delta_days(),
            "soc_init": soc_init,
            "soc_final": soc_final,
            "number_of_deferrable_loads": 1,
            "nominal_power_of_deferrable_loads": nominal_power,
            "operating_hours_of_each_deferrable_load": op_hours,
            "end_timesteps_of_each_deferrable_load": timesteps,
            "set_deferrable_load_single_constant": [ev_force]
        }

        # Publishing the p_* HA sensors is intentionally NOT chained here. A separate
        # publish-data POST replaces the optimization figure on the EMHASS web UI with the
        # publish output (empty graphs). Instead enable `continual_publish: true` in the
        # EMHASS config so the optimization publishes the sensors itself while keeping its
        # figure. Use the standalone `publish_data` service if you prefer manual publishing.
        return await call_emhass("run_mpc_optim", "naive-mpc-optim", payload, 180)

    async def handle_publish_data(call: ServiceCall) -> dict:
        return await call_emhass("publish_data", "publish-data", {}, 60)

    hass.services.async_register(DOMAIN, "fit_ml_model", handle_fit_ml_model, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "tune_ml_model", handle_tune_ml_model, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "predict_ml_model", handle_predict_ml_model, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "run_mpc_optim", handle_run_mpc_optim, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "publish_data", handle_publish_data, supports_response=SupportsResponse.OPTIONAL)

    async def _publish_on_quarter(now):
        """Post the current slot's plan right after each quarter-hour boundary.

        EMHASS's continual_publish thread free-runs from server start, so left
        alone the plan sensors can refresh as late as ~14 minutes into a slot.
        Automations that read them right after the boundary need the row for
        the slot that just started; with method_ts_round=nearest, a
        publish-data call at boundary+2s selects exactly that row.
        """
        if not coordinator.emhass_auto_mpc:
            return
        await call_emhass("publish_data", "publish-data", {}, 60)

    entry.async_on_unload(
        async_track_time_change(hass, _publish_on_quarter, minute=[0, 15, 30, 45], second=2)
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
