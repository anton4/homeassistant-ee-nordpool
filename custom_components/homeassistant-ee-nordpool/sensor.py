import holidays
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
import homeassistant.util.dt as dt_util
from .const import *

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        NordpoolPriceSensor(coordinator),
        NordpoolStateSensor(coordinator),
        NordpoolImportCostSensor(coordinator),
        NordpoolExportCostSensor(coordinator),
        NordpoolFromNowSensor(coordinator),
        NordpoolSolcastSensor(coordinator),
        NordpoolLastPollSensor(coordinator),
        NordpoolNextPollSensor(coordinator)
    ])

class NordpoolBaseEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    def _get_merged_raw_prices(self):
        """Merges EE prices with the FI Forecast if enabled via the toggle switch."""
        raw_prices = self.coordinator.data.get("prices", [])
        if not raw_prices:
            return []

        extend_fi = self.coordinator.extend_fi
        if not extend_fi:
            return raw_prices

        fi_state = self.coordinator.hass.states.get("sensor.nordpool_predict_fi_price")
        if not fi_state or not fi_state.attributes.get("forecast"):
            return raw_prices

        merged = list(raw_prices)
        extend_days = self.coordinator.extend_fi_days
        
        ee_end_dt = dt_util.parse_datetime(merged[-1]["end"])
        cutoff_dt = ee_end_dt + timedelta(days=extend_days)

        fi_forecast = fi_state.attributes.get("forecast")

        for item in fi_forecast:
            fi_start_dt = dt_util.as_local(dt_util.parse_datetime(item["timestamp"]))
            fi_end_dt = fi_start_dt + timedelta(hours=1)
            
            if fi_end_dt <= ee_end_dt:
                continue
            if fi_start_dt >= cutoff_dt:
                break
                
            fi_value_eur = float(item["value"]) / 100.0
            
            for i in range(4):
                block_start = fi_start_dt + timedelta(minutes=15 * i)
                block_end = block_start + timedelta(minutes=15)
                
                if block_start >= ee_end_dt and block_start < cutoff_dt:
                    merged.append({
                        "start": block_start.isoformat(),
                        "end": block_end.isoformat(),
                        "value": round(fi_value_eur, 5),
                        "is_forecast": True
                    })
        return merged

    def _get_calculated_prices(self, price_type):
        """Centralized calculator for Import or Export math."""
        raw_prices = self._get_merged_raw_prices()
        if not raw_prices:
            return []

        def get_opt(key, default):
            return self.coordinator.entry.options.get(key, self.coordinator.entry.data.get(key, default))

        margin = get_opt("margin", DEFAULT_MARGIN)
        taastuv = get_opt("taastuv", DEFAULT_TAASTUV)
        aktsiis = get_opt("aktsiis", DEFAULT_AKTSIIS)
        tasakaal = get_opt("tasakaal", DEFAULT_TASAKAAL)
        varustus = get_opt("varustus", DEFAULT_VARUSTUS)
        el_day = get_opt("elektrilevi_day", DEFAULT_ELEKTRILEVI_DAY)
        el_night = get_opt("elektrilevi_night", DEFAULT_ELEKTRILEVI_NIGHT)
        vat_percent = get_opt("vat", DEFAULT_VAT)

        ex_margin = get_opt("export_margin", DEFAULT_EXPORT_MARGIN)
        ex_tasakaal = get_opt("export_tasakaal", DEFAULT_EXPORT_TASAKAAL)

        ee_holidays = holidays.country_holidays("EE")
        calculated_prices = []

        for p in raw_prices:
            start_dt = dt_util.parse_datetime(p["start"])
            
            if price_type == "import":
                is_weekend = start_dt.weekday() in (5, 6)
                is_night_hour = start_dt.hour < 7 or start_dt.hour >= 22
                is_holiday = start_dt.date() in ee_
