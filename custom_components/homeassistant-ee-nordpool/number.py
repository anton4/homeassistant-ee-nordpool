from homeassistant.components.number import NumberEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        NordpoolExtendFIDaysNumber(coordinator),
        NordpoolEmhassMpcIntervalNumber(coordinator),
    ])

class NordpoolExtendFIDaysNumber(NumberEntity):
    """How many days beyond the last actual EE hour to extend using the selected forecast."""
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Forecast Extend Days"
        self._attr_unique_id = "nordpool_extend_fi_days_number"
        self._attr_icon = "mdi:calendar-range"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 7
        self._attr_native_step = 1

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    @property
    def native_value(self):
        return self.coordinator.extend_fi_days

    async def async_set_native_value(self, value: float):
        """Update extension days and force all sensors to recalculate."""
        await self.coordinator.async_set_extend_fi_days(int(value))


class NordpoolEmhassMpcIntervalNumber(NumberEntity):
    """Minutes between automatic EMHASS MPC runs (used when EMHASS Auto MPC is on)."""
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "EMHASS MPC Interval"
        self._attr_unique_id = "nordpool_emhass_mpc_interval_number"
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 120
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    @property
    def native_value(self):
        return self.coordinator.emhass_mpc_interval

    async def async_set_native_value(self, value: float):
        """Update the automatic MPC interval and recompute the next-run ETA."""
        await self.coordinator.async_set_emhass_mpc_interval(int(value))
