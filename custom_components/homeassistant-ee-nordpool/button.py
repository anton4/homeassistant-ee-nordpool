from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolForceUpdateButton(coordinator)])

class NordpoolForceUpdateButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Force Update Prices"
        self._attr_unique_id = "nordpool_force_update_button"
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    async def async_press(self) -> None:
        """Force an immediate update bypassing restrictions."""
        await self.coordinator.async_request_refresh()
