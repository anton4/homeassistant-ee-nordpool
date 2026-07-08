from homeassistant.components.select import SelectEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, FORECAST_OPTIONS

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolForecastSourceSelect(coordinator)])

class NordpoolForecastSourceSelect(SelectEntity):
    """Which forecast extends the price curve beyond the last published EE hour."""
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Forecast Source"
        self._attr_unique_id = "nordpool_forecast_source_select"
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_options = FORECAST_OPTIONS

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    @property
    def current_option(self):
        return self.coordinator.forecast_source

    async def async_select_option(self, option: str):
        """Switch the active forecast source and force all sensors to recalculate."""
        await self.coordinator.async_set_forecast_source(option)
