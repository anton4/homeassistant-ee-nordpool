import logging
import async_timeout
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.util.dt as dt_util
from .const import DOMAIN, OPTION_NONE
from .coordinator import NordpoolCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button", "select", "number", "switch"]
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
            "set_deferrable_load_single_constant": [ev_force],
            "battery_soc_deficit_threshold": 0.3,
            "battery_soc_deficit_cost": 1.5,
            "publish_data": True # <-- This tells EMHASS to generate the SVG graphs
        }

        return await call_emhass("run_mpc_optim", "naive-mpc-optim", payload, 180)

    hass.services.async_register(DOMAIN, "fit_ml_model", handle_fit_ml_model, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "tune_ml_model", handle_tune_ml_model, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "predict_ml_model", handle_predict_ml_model, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "run_mpc_optim", handle_run_mpc_optim, supports_response=SupportsResponse.OPTIONAL)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
