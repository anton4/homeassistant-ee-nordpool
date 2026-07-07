from homeassistant.components.number import NumberEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolExtendFIDaysNumber(coordinator)])

class NordpoolExtendFIDaysNumber(NumberEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Forecast Extend Days"
        self._attr_unique_id = "nordpool_extend_fi_days_number"
        self._attr_icon = "mdi:calendar-expand-horizontal"
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
