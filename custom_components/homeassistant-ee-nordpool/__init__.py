import logging
import async_timeout
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN
from .coordinator import NordpoolCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button", "switch", "number"]
EMHASS_URL = "http://localhost:5001/action"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = NordpoolCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(entry.add_update_listener(update_listener))

    session = async_get_clientsession(hass)

    def get_max_lags():
        """Calculates the absolute maximum prediction horizon to prevent ML lag crashes."""
        fi_days = coordinator.extend_fi_days if getattr(coordinator, 'extend_fi', False) else 0
        max_horizon = 192 + (fi_days * 96)
        return max_horizon

    def get_delta_days():
        """Calculates the max daily horizon limit to prevent EMHASS from clipping the arrays."""
        fi_days = coordinator.extend_fi_days if getattr(coordinator, 'extend_fi', False) else 0
        return 2 + fi_days
        
    def get_history_needed():
        """Ensures EMHASS pulls enough days of history to satisfy the ML lags."""
        auto_lags = get_max_lags()
        return max(7, int((auto_lags / 96) + 2))

    def get_split_date_delta():
        """Converts lags into hours so the test dataset length matches the prediction horizon."""
        hours = int(get_max_lags() / 4)
        return f"{hours}h"

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
        try:
            async with async_timeout.timeout(3600):
                resp = await session.post(f"{EMHASS_URL}/forecast-model-fit", json=payload)
                resp.raise_for_status()
                _LOGGER.info(f"EMHASS ML Model Fit initiated with {auto_lags} automated lags.")
                return {"status": "success", "http_code": resp.status, "automated_lags": auto_lags, "payload_sent": payload}
        except Exception as e:
            _LOGGER.error("Failed to fit EMHASS ML model: %s", e)
            return {"status": "error", "error_message": str(e)}

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
        try:
            async with async_timeout.timeout(7200):
                resp = await session.post(f"{EMHASS_URL}/forecast-model-tune", json=payload)
                resp.raise_for_status()
                _LOGGER.info("EMHASS ML Model Tune completed.")
                return {"status": "success", "http_code": resp.status, "payload_sent": payload}
        except Exception as e:
            _LOGGER.error("Failed to tune EMHASS ML model: %s", e)
            return {"status": "error", "error_message": str(e)}

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
        try:
            async with async_timeout.timeout(180):
                resp = await session.post(f"{EMHASS_URL}/forecast-model-predict", json=payload)
                resp.raise_for_status()
                _LOGGER.info("EMHASS ML Predict published.")
                return {"status": "success", "http_code": resp.status, "payload_sent": payload}
        except Exception as e:
            _LOGGER.error("Failed to predict EMHASS ML model: %s", e)
            return {"status": "error", "error_message": str(e)}

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

        try:
            async with async_timeout.timeout(180):
                resp = await session.post(f"{EMHASS_URL}/naive-mpc-optim", json=payload)
                resp.raise_for_status()
                _LOGGER.info("EMHASS MPC Optim triggered.")
                
                return {
                    "status": "success", 
                    "http_code": resp.status, 
                    "payload_sent": payload
                }
        except Exception as e:
            _LOGGER.error("Failed to trigger MPC Optim: %s", e)
            return {"status": "error", "error_message": str(e)}

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
