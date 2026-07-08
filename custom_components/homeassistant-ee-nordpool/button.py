from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolForceUpdateButton(coordinator)])

class NordpoolForceUpdateButton(ButtonEntity):
    """Immediately fetch today's + tomorrow's day-ahead prices from the Nordpool API
    (and the EE forecast if that source is selected), bypassing the polling schedule."""
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Fetch Nordpool Prices Now"
        self._attr_unique_id = "nordpool_force_update_button"
        self._attr_icon = "mdi:cloud-download-outline"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    async def async_press(self) -> None:
        """Fetch fresh Nordpool day-ahead prices now, bypassing the fast/slow throttle."""
        await self.coordinator.async_request_refresh()
