import holidays
import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import *

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        NordpoolPriceSensor(coordinator),
        NordpoolStateSensor(coordinator),
        NordpoolImportCostSensor(coordinator),
        NordpoolExportCostSensor(coordinator)
    ])

class NordpoolPriceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Nordpool Raw Prices EE"
        self._attr_unique_id = "nordpool_prices_ee_sensor"
        self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self):
        prices = self.coordinator.data.get("prices", [])
        if prices:
            return f"{len(prices)} periods loaded"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        return {
            "prices": self.coordinator.data.get("prices", []),
            "last_poll_time": self.coordinator.last_poll_time.isoformat() if self.coordinator.last_poll_time else None
        }

class NordpoolStateSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Nordpool Prices State"
        self._attr_unique_id = "nordpool_prices_state_sensor"
        self._attr_icon = "mdi:list-status"

    @property
    def native_value(self):
        return self.coordinator.data.get("state", "Waiting")


# --- IMPORT COST SENSOR (RENAMED) ---
class NordpoolImportCostSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Nordpool Import Cost EE"
        self._attr_unique_id = "nordpool_import_cost_ee_sensor"
        self._attr_icon = "mdi:transmission-tower-export"
        self.ee_holidays = holidays.country_holidays("EE")

    @property
    def native_value(self):
        prices = self.coordinator.data.get("prices", [])
        if prices:
            return f"{len(prices)} calculated"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        raw_prices = self.coordinator.data.get("prices", [])
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
                "value": round(final_value, 5)
            })

        return {"prices": calculated_prices}


# --- NEW EXPORT COST SENSOR ---
class NordpoolExportCostSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Nordpool Export Cost EE"
        self._attr_unique_id = "nordpool_export_cost_ee_sensor"
        self._attr_icon = "mdi:transmission-tower-import"

    @property
    def native_value(self):
        prices = self.coordinator.data.get("prices", [])
        if prices:
            return f"{len(prices)} calculated"
        return "Waiting for data"

    @property
    def extra_state_attributes(self):
        raw_prices = self.coordinator.data.get("prices", [])
        if not raw_prices:
            return {"prices": []}

        def get_opt(key, default):
            return self.coordinator.entry.options.get(key, self.coordinator.entry.data.get(key, default))

        ex_margin = get_opt("export_margin", DEFAULT_EXPORT_MARGIN)
        ex_tasakaal = get_opt("export_tasakaal", DEFAULT_EXPORT_TASAKAAL)

        calculated_prices = []

        for p in raw_prices:
            # Replicates your custom template math exactly: raw_value - export_margin - export_tasakaal
            final_value = p["value"] - ex_margin - ex_tasakaal

            calculated_prices.append({
                "start": p["start"],
                "end": p["end"],
                "value": round(final_value, 5)
            })

        return {"prices": calculated_prices}
