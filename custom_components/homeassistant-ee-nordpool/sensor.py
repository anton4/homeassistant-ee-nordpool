import holidays
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
import homeassistant.util.dt as dt_util
from .const import *

# Valid MDI icons per EMHASS action (mdi:cog-clock used before was not a real icon).
EMHASS_RUN_ICONS = {
    "run_mpc_optim": "mdi:calculator",
    "publish_data": "mdi:publish",
    "fit_ml_model": "mdi:brain",
    "tune_ml_model": "mdi:tune",
    "predict_ml_model": "mdi:chart-line",
}

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NordpoolPriceSensor(coordinator),
        NordpoolStateSensor(coordinator),
        NordpoolImportCostSensor(coordinator),
        NordpoolExportCostSensor(coordinator),
        NordpoolFromNowSensor(coordinator),
        NordpoolSolcastSensor(coordinator),
        NordpoolLastPollSensor(coordinator),
        NordpoolNextPollSensor(coordinator),
        NordpoolEeForecastSensor(coordinator),
        NordpoolForecastLastPollSensor(coordinator),
        NordpoolForecastNextPollSensor(coordinator),
        NordpoolEmhassNextRunSensor(coordinator),
    ]
    for service_key, label in EMHASS_SERVICE_LABELS.items():
        icon = EMHASS_RUN_ICONS.get(service_key, "mdi:cog")
        entities.append(NordpoolEmhassRunSensor(coordinator, service_key, label, icon))
    async_add_entities(entities)

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
        """Extends the actual EE spot prices with the forecast selected via the Forecast Source entity."""
        raw_prices = self.coordinator.data.get("prices", [])
        if not raw_prices:
            return []

        source = self.coordinator.forecast_source
        if source == OPTION_FI:
            hourly = self._get_fi_hourly()
        elif source == OPTION_EE:
            hourly = self._get_ee_hourly()
        else:
            return raw_prices

        if not hourly:
            return raw_prices

        return self._append_forecast(raw_prices, hourly)

    def _get_fi_hourly(self):
        """Reads the FI price forecast from an external sensor as (start_dt, €/kWh) tuples."""
        fi_state = self.coordinator.hass.states.get("sensor.nordpool_predict_fi_price")
        if not fi_state or not fi_state.attributes.get("forecast"):
            return []

        hourly = []
        for item in fi_state.attributes.get("forecast"):
            start_dt = dt_util.parse_datetime(item["timestamp"])
            if start_dt is None:
                continue
            # FI forecast values are published in cents/kWh.
            hourly.append((dt_util.as_local(start_dt), float(item["value"]) / 100.0))
        return hourly

    def _get_ee_hourly(self):
        """Reads the cached eupowerprices.com EE forecast as (start_dt, €/kWh) tuples."""
        hourly = []
        for item in self.coordinator.ee_forecast or []:
            start_dt = dt_util.parse_datetime(item["start"])
            if start_dt is None:
                continue
            # EE forecast values are already stored in €/kWh by the coordinator.
            hourly.append((dt_util.as_local(start_dt), float(item["value"])))
        return hourly

    def _append_forecast(self, raw_prices, hourly):
        """Appends hourly forecast values (expanded into 15-min blocks) after the last actual EE period."""
        merged = list(raw_prices)
        extend_days = self.coordinator.extend_fi_days

        ee_end_dt = dt_util.parse_datetime(merged[-1]["end"])
        cutoff_dt = ee_end_dt + timedelta(days=extend_days)

        for start_dt, value_eur in hourly:
            hour_end_dt = start_dt + timedelta(hours=1)

            if hour_end_dt <= ee_end_dt:
                continue
            if start_dt >= cutoff_dt:
                continue

            for i in range(4):
                block_start = start_dt + timedelta(minutes=15 * i)
                block_end = block_start + timedelta(minutes=15)

                if block_start >= ee_end_dt and block_start < cutoff_dt:
                    merged.append({
                        "start": block_start.isoformat(),
                        "end": block_end.isoformat(),
                        "value": round(value_eur, 5),
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
            "last_poll_time": self.coordinator.last_poll_time.isoformat() if self.coordinator.last_poll_time else None,
            "source": "Nordpool Day-Ahead API (dataportal-api.nordpoolgroup.com)",
            "delivery_area": "EE",
            "currency": "EUR",
            "unit": "€/kWh",
            "forecast_source": self.coordinator.forecast_source,
        }

class NordpoolStateSensor(NordpoolBaseEntity, SensorEntity):
    """Nordpool's publication status for tomorrow's EE day-ahead prices (Waiting/Preliminary/Final)."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Day-Ahead Publish Status"
        self._attr_unique_id = "nordpool_prices_state_sensor"
        self._attr_icon = "mdi:list-status"

    @property
    def native_value(self):
        return self.coordinator.data.get("state", "Waiting")

    @property
    def extra_state_attributes(self):
        return {
            "nordpool_api": "https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices",
            "delivery_area": "EE",
            "currency": "EUR",
            "http_code_today": self.coordinator.data.get("http_code_today"),
            "status_today": self.coordinator.data.get("api_status_today", "Unknown"),
            "http_code_tomorrow": self.coordinator.data.get("http_code_tomorrow"),
            "status_tomorrow": self.coordinator.data.get("api_status_tomorrow", "Unknown"),
            "forecast_source": self.coordinator.data.get("forecast_source"),
            "forecast_api": "https://api.eupowerprices.com/v1/forecasts/EE/latest",
            "forecast_status": self.coordinator.data.get("forecast_status"),
            "http_code_forecast": self.coordinator.data.get("http_code_forecast"),
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
        """State is the number of 15-minute periods left."""
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

class NordpoolSolcastSensor(NordpoolBaseEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Solcast Forecast 15min"
        self._attr_unique_id = "nordpool_solcast_15min_sensor"
        self._attr_icon = "mdi:solar-power"

    @property
    def native_value(self):
        return len(self._get_solcast_forecast())

    @property
    def extra_state_attributes(self):
        return {
            "values": self._get_solcast_forecast()
        }

    def _get_solcast_forecast(self):
        hass = self.coordinator.hass
        now = dt_util.now()
        
        field_select = hass.states.get('select.solcast_pv_forecast_use_forecast_field')
        field_name = field_select.state if field_select else 'estimate'
        forecast_use_field = f"pv_{field_name}"

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
                    val = item.get(forecast_use_field, 0.0)
                    raw_30min_values.append(val)

        values_15min_watts = []
        dampener = 1
        for val in raw_30min_values:
            watts = int(float(val) * 1000) * dampener
            values_15min_watts.extend([watts, watts])

        intervals_since_midnight = (now.hour * 4) + (now.minute // 15)
        
        prices = self._get_calculated_prices("import")
        future_prices = [p for p in prices if dt_util.parse_datetime(p["end"]) > now]
        np_range = len(future_prices)

        sliced_values = values_15min_watts[intervals_since_midnight : intervals_since_midnight + np_range]

        while len(sliced_values) < np_range:
            sliced_values.append(0)

        return sliced_values


class NordpoolLastPollSensor(NordpoolBaseEntity, SensorEntity):
    """When the integration last actually fetched prices from the Nordpool API."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Last Nordpool Poll"
        self._attr_unique_id = "nordpool_last_poll_time_sensor"
        self._attr_icon = "mdi:clock-check"

    @property
    def native_value(self):
        return self.coordinator.last_poll_time

class NordpoolNextPollSensor(NordpoolBaseEntity, SensorEntity):
    """When the integration will next poll the Nordpool API (per the fast/slow schedule)."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Next Nordpool Poll"
        self._attr_unique_id = "nordpool_next_poll_time_sensor"
        self._attr_icon = "mdi:update"

    @property
    def native_value(self):
        return self.coordinator.next_poll_time


class NordpoolEeForecastSensor(NordpoolBaseEntity, SensorEntity):
    """Status of the eupowerprices.com Estonian (EE) price forecast source."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "EE Price Forecast"
        self._attr_unique_id = "nordpool_ee_forecast_sensor"
        self._attr_icon = "mdi:crystal-ball"

    @property
    def native_value(self):
        """Inactive unless the Forecast Source is Estonia (EE); otherwise the fetch status."""
        if self.coordinator.forecast_source != OPTION_EE:
            return "Inactive"
        return self.coordinator.forecast_status or "Not polled yet"

    @property
    def extra_state_attributes(self):
        last = self.coordinator.last_forecast_poll
        return {
            "active": self.coordinator.forecast_source == OPTION_EE,
            "forecast_source": self.coordinator.forecast_source,
            "provider": "eupowerprices.com",
            "api": EE_FORECAST_URL,
            "api_key_set": bool(self.coordinator.api_key),
            "http_code": self.coordinator.http_code_forecast,
            "points": len(self.coordinator.ee_forecast or []),
            "last_fetch": last.isoformat() if last else None,
            "forecast": self.coordinator.ee_forecast or [],
        }


class NordpoolForecastLastPollSensor(NordpoolBaseEntity, SensorEntity):
    """When the eupowerprices.com EE forecast API was last polled."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Forecast API Last Poll"
        self._attr_unique_id = "nordpool_forecast_last_poll_sensor"
        self._attr_icon = "mdi:clock-check"

    @property
    def native_value(self):
        return self.coordinator.last_forecast_poll


class NordpoolForecastNextPollSensor(NordpoolBaseEntity, SensorEntity):
    """When the eupowerprices.com EE forecast API will next be polled (only while Estonia (EE) is selected)."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Forecast API Next Poll"
        self._attr_unique_id = "nordpool_forecast_next_poll_sensor"
        self._attr_icon = "mdi:update"

    @property
    def native_value(self):
        if self.coordinator.forecast_source != OPTION_EE:
            return None
        last = self.coordinator.last_forecast_poll
        if last is None:
            return None
        return last + timedelta(hours=self.coordinator.forecast_poll_hours)


class NordpoolEmhassNextRunSensor(NordpoolBaseEntity, SensorEntity):
    """ETA of the next automatic EMHASS MPC run (when Auto MPC is enabled)."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "EMHASS Next Run"
        self._attr_unique_id = "nordpool_emhass_next_run_sensor"
        self._attr_icon = "mdi:robot-outline"

    @property
    def native_value(self):
        return self.coordinator.emhass_next_mpc

    @property
    def extra_state_attributes(self):
        last_mpc = self.coordinator.emhass_last_mpc
        return {
            "auto_mpc_enabled": self.coordinator.emhass_auto_mpc,
            "interval_minutes": self.coordinator.emhass_mpc_interval,
            "last_scheduled_run": last_mpc.isoformat() if last_mpc else None,
        }


class NordpoolEmhassRunSensor(NordpoolBaseEntity, SensorEntity):
    """Exposes the outcome of the most recent call to a given EMHASS service."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, service_key, name, icon):
        super().__init__(coordinator)
        self._service_key = service_key
        self._attr_name = name
        self._attr_unique_id = f"nordpool_emhass_{service_key}_run_sensor"
        self._attr_icon = icon

    @property
    def native_value(self):
        run = self.coordinator.emhass_runs.get(self._service_key)
        if not run or not run.get("last_run"):
            return None
        return dt_util.parse_datetime(run["last_run"])

    @property
    def extra_state_attributes(self):
        run = self.coordinator.emhass_runs.get(self._service_key, {})
        return {
            "status": run.get("status"),
            "http_code": run.get("http_code"),
            "duration_seconds": run.get("duration_seconds"),
            "error": run.get("error"),
            "response": run.get("response"),
            "payload": run.get("payload"),
        }
