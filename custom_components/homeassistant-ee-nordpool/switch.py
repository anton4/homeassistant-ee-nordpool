from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolExtendFISwitch(coordinator)])

class NordpoolExtendFISwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Extend with FI Forecast"
        self._attr_unique_id = "nordpool_extend_fi_switch"
        self._attr_icon = "mdi:chart-timeline"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    @property
    def is_on(self):
        return self.coordinator.extend_fi

    async def async_turn_on(self, **kwargs):
        """Enable FI tracking and force all sensors to recalculate."""
        await self.coordinator.async_set_extend_fi(True)

    async def async_turn_off(self, **kwargs):
        """Disable FI tracking and force all sensors to recalculate."""
        await self.coordinator.async_set_extend_fi(False)
