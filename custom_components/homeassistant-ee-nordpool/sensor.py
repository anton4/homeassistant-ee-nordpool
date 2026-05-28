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
        """Merges EE prices with the FI Forecast if enabled."""
        raw_prices = self.coordinator.data.get("prices", [])
        if not raw_prices:
            return []

        # Retrieve user config
        def get_opt(key, default):
            return self.coordinator.entry.options.get(key, self.coordinator.entry.data.get(key, default))

        extend_fi = get_opt("extend_fi", DEFAULT_EXTEND_FI)
        if not extend_fi:
            return raw_prices

        # Fetch external FI Sensor State
        fi_state = self.coordinator.hass.states.get("sensor.nordpool_predict_fi_price")
        if not fi_state or not fi_state.attributes.get("forecast"):
            return raw_prices

        merged = list(raw_prices)
        extend_days = get_opt("extend_fi_days", DEFAULT_EXTEND_FI_DAYS)
        
        # Determine the exact timestamp where EE prices stop
        ee_end_dt = dt_util.parse_datetime(merged[-1]["end"])
        cutoff_dt = ee_end_dt + timedelta(days=extend_days)

        fi_forecast = fi_state.attributes.get("forecast")

        for item in fi_forecast:
            # Convert UTC time to Local HA timezone
            fi_start_dt = dt_util.as_local(dt_util.parse_datetime(item["timestamp"]))
            fi_end_dt = fi_start_dt + timedelta(hours=1)
            
            # Skip FI blocks that overlap with existing EE blocks
            if fi_end_dt <= ee_end_dt:
                continue
                
            # Stop parsing if we hit the user's future day limit
            if fi_start_dt >= cutoff_dt:
                break
                
            # Convert FI cents/kWh to EUR/kWh
            fi_value_eur = float(item["value"]) / 100.0
            
            # Split the 1-hour block into four 15-minute blocks
            for i in range(4):
                block_start = fi_start_dt + timedelta(minutes=15 * i)
                block_end = block_start + timedelta(minutes=15)
                
                if block_start >= ee_end_dt and block_start < cutoff_dt:
                    merged.append({
                        "start": block_start.isoformat(),
                        "end": block_end.isoformat(),
                        "value": round(fi_value_eur, 5),
                        "is_forecast": True # Tagged as forecast just in case
                    })
                    
        return merged


class NordpoolPriceSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Raw Prices"
        self._attr_unique_id = "nordpool_prices_ee_sensor"
        self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self):
        prices = self._get_merged_raw_prices()
        if prices:
            return f"{len(prices)} periods loaded"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        return {
            "prices": self._get_merged_raw_prices(),
            "last_poll_time": self.coordinator.last_poll_time.isoformat() if self.coordinator.last_poll_time else None
        }

class NordpoolStateSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Prices State"
        self._attr_unique_id = "nordpool_prices_state_sensor"
        self._attr_icon = "mdi:list-status"

    @property
    def native_value(self):
        return self.coordinator.data.get("state", "Waiting")

    @property
    def extra_state_attributes(self):
        """Exposes clean diagnostic network feedback to the UI."""
        return {
            "http_code_today": self.coordinator.data.get("http_code_today"),
            "status_today": self.coordinator.data.get("api_status_today", "Unknown"),
            "http_code_tomorrow": self.coordinator.data.get("http_code_tomorrow"),
            "status_tomorrow": self.coordinator.data.get("api_status_tomorrow", "Unknown")
        }

class NordpoolImportCostSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Import Cost"
        self._attr_unique_id = "nordpool_import_cost_ee_sensor"
        self._attr_icon = "mdi:transmission-tower-export"
        self.ee_holidays = holidays.country_holidays("EE")

    @property
    def native_value(self):
        prices = self._get_merged_raw_prices()
        if prices:
            return f"{len(prices)} calculated"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        # Now fetches the perfectly stitched EE + FI raw list
        raw_prices = self._get_merged_raw_prices()
        if not raw_prices:
            return {"prices": []}

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

        calculated_prices = []

        for p in raw_prices:
            start_dt = dt_util.parse_datetime(p["start"])
            
            is_weekend = start_dt.weekday() in (5, 6)
            is_night_hour = start_dt.hour < 7 or start_dt.hour >= 22
            is_holiday = start_dt.date() in self.ee_holidays

            if is_weekend or is_night_hour or is_holiday:
                tariff = margin + taastuv + aktsiis + tasakaal + varustus + el_night
            else:
                tariff = margin + taastuv + aktsiis + tasakaal + varustus + el_day

            final_value = (p["value"] + tariff) * (1.0 + (vat_percent / 100.0))

            calculated_prices.append({
                "start": p["start"],
                "end": p["end"],
                "value": round(final_value, 5),
                "is_forecast": p.get("is_forecast", False)
            })

        return {"prices": calculated_prices}

class NordpoolExportCostSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Export Cost"
        self._attr_unique_id = "nordpool_export_cost_ee_sensor"
        self._attr_icon = "mdi:transmission-tower-import"

    @property
    def native_value(self):
        prices = self._get_merged_raw_prices()
        if prices:
            return f"{len(prices)} calculated"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        raw_prices = self._get_merged_raw_prices()
        if not raw_prices:
            return {"prices": []}

        def get_opt(key, default):
            return self.coordinator.entry.options.get(key, self.coordinator.entry.data.get(key, default))

        ex_margin = get_opt("export_margin", DEFAULT_EXPORT_MARGIN)
        ex_tasakaal = get_opt("export_tasakaal", DEFAULT_EXPORT_TASAKAAL)

        calculated_prices = []

        for p in raw_prices:
            final_value = p["value"] - ex_margin - ex_tasakaal

            calculated_prices.append({
                "start": p["start"],
                "end": p["end"],
                "value": round(final_value, 5),
                "is_forecast": p.get("is_forecast", False)
            })

        return {"prices": calculated_prices}


class NordpoolLastPollSensor(NordpoolBaseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Last Poll Time"
        self._attr_unique_id = "nordpool_last_poll_time_sensor"
        self._attr_icon = "mdi:clock-check"

    @property
    def native_value(self):
        return self.coordinator.last_poll_time

class NordpoolNextPollSensor(NordpoolBaseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Next Poll Time"
        self._attr_unique_id = "nordpool_next_poll_time_sensor"
        self._attr_icon = "mdi:update"

    @property
    def native_value(self):
        return self.coordinator.next_poll_time
