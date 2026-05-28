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
        NordpoolSolcastSensor(coordinator), # New Solcast Array Sensor
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

        # Now reads directly from the live coordinator properties
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
                is_holiday = start_dt.date() in ee_holidays

                if is_weekend or is_night_hour or is_holiday:
                    tariff = margin + taastuv + aktsiis + tasakaal + varustus + el_night
                else:
                    tariff = margin + taastuv + aktsiis + tasakaal + varustus + el_day

                final_value = (p["value"] + tariff) * (1.0 + (vat_percent / 100.0))
            else:
                final_value = p["value"] - ex_margin - ex_tasakaal

            calculated_prices.append({
                "start": p["start"],
                "end": p["end"],
                "value": round(final_value, 5),
                "is_forecast": p.get("is_forecast", False)
            })

        return calculated_prices


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

    @property
    def native_value(self):
        prices = self._get_calculated_prices("import")
        if prices:
            return f"{len(prices)} calculated"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        return {"prices": self._get_calculated_prices("import")}

class NordpoolExportCostSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Export Cost"
        self._attr_unique_id = "nordpool_export_cost_ee_sensor"
        self._attr_icon = "mdi:transmission-tower-import"

    @property
    def native_value(self):
        prices = self._get_calculated_prices("export")
        if prices:
            return f"{len(prices)} calculated"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        return {"prices": self._get_calculated_prices("export")}

class NordpoolFromNowSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Prices From Now"
        self._attr_unique_id = "nordpool_prices_from_now_sensor"
        self._attr_icon = "mdi:chart-timeline-variant-shimmer"

    @property
    def native_value(self):
        now = dt_util.now()
        prices = self._get_calculated_prices("import")
        future_prices = [p for p in prices if dt_util.parse_datetime(p["end"]) > now]
        return len(future_prices)

    @property
    def extra_state_attributes(self):
        now = dt_util.now()
        
        import_prices = self._get_calculated_prices("import")
        future_imports = [p["value"] for p in import_prices if dt_util.parse_datetime(p["end"]) > now]
        
        export_prices = self._get_calculated_prices("export")
        future_exports = [p["value"] for p in export_prices if dt_util.parse_datetime(p["end"]) > now]

        return {
            "timestamps_left": len(future_imports),
            "import_prices": future_imports,
            "export_prices": future_exports
        }

# --- NEW SENSOR: SOLCAST 15-MINUTE ARRAY FORECAST ---
class NordpoolSolcastSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Solcast Forecast 15min"
        self._attr_unique_id = "nordpool_solcast_15min_sensor"
        self._attr_icon = "mdi:solar-power"

    @property
    def native_value(self):
        """Displays how many 15-minute periods are matched and loaded."""
        return len(self._get_solcast_forecast())

    @property
    def extra_state_attributes(self):
        """Outputs the perfectly sliced Watts array to match Nordpool timestamps."""
        return {
            "values": self._get_solcast_forecast()
        }

    def _get_solcast_forecast(self):
        hass = self.coordinator.hass
        now = dt_util.now()
        
        # 1. Get the forecast field dynamically (e.g., 'estimate', 'estimate10', 'estimate90')
        field_select = hass.states.get('select.solcast_pv_forecast_use_forecast_field')
        field_name = field_select.state if field_select else 'estimate'
        forecast_use_field = f"pv_{field_name}"

        # 2. Iterate through all potential 7 days of Solcast sensors
        sensors = [
            "sensor.solcast_pv_forecast_forecast_today",
            "sensor.solcast_pv_forecast_forecast_tomorrow",
            "sensor.solcast_pv_forecast_forecast_day_3",
            "sensor.solcast_pv_forecast_forecast_day_4",
            "sensor.solcast_pv_forecast_forecast_day_5",
            "sensor.solcast_pv_forecast_forecast_day_6",
            "sensor.solcast_pv_forecast_forecast_day_7"
        ]

        raw_30min_values = []
        for sensor_id in sensors:
            state = hass.states.get(sensor_id)
            if state and 'detailedForecast' in state.attributes:
                for item in state.attributes['detailedForecast']:
                    # Extract the selected field, default to 0.0 if missing
                    val = item.get(forecast_use_field, 0.0)
                    raw_30min_values.append(val)

        # 3. Convert 30-min block kW to two identical 15-min block Watts
        values_15min_watts = []
        dampener = 1
        for val in raw_30min_values:
            watts = int(float(val) * 1000) * dampener
            values_15min_watts.extend([watts, watts])

        # 4. Determine starting index and required length
        intervals_since_midnight = (now.hour * 4) + (now.minute // 15)
        
        prices = self._get_calculated_prices("import")
        future_prices = [p for p in prices if dt_util.parse_datetime(p["end"]) > now]
        np_range = len(future_prices)

        # 5. Slice the array directly to the active timeline window
        sliced_values = values_15min_watts[intervals_since_midnight : intervals_since_midnight + np_range]

        # 6. Safety check: Pad with 0s if FI extended prices stretch further than Solcast data length
        while len(sliced_values) < np_range:
            sliced_values.append(0)

        return sliced_values


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
