from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolEmhassAutoMpcSwitch(coordinator)])

class NordpoolEmhassAutoMpcSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "EMHASS Auto MPC"
        self._attr_unique_id = "nordpool_emhass_auto_mpc_switch"
        self._attr_icon = "mdi:robot"

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
        return self.coordinator.emhass_auto_mpc

    async def async_turn_on(self, **kwargs):
        """Enable the automatic MPC schedule."""
        await self.coordinator.async_set_emhass_auto_mpc(True)

    async def async_turn_off(self, **kwargs):
        """Disable the automatic MPC schedule."""
        await self.coordinator.async_set_emhass_auto_mpc(False)
