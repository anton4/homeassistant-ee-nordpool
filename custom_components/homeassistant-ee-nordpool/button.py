from homeassistant.components.button import ButtonEntity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolManualPollButton(coordinator)])

class NordpoolManualPollButton(ButtonEntity):
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Nordpool Manual Poll"
        self._attr_unique_id = "nordpool_manual_poll_button"
        self._attr_icon = "mdi:refresh"

    async def async_press(self) -> None:
        """Trigger an immediate, forced update."""
        await self.coordinator.async_request_refresh()
