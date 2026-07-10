from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NordpoolProblemBinarySensor(coordinator)])

class NordpoolProblemBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On (Problem) when any update is failing: Nordpool scraping, the
    eupowerprices.com forecast poll, or any EMHASS call (MPC/publish/fit/tune/predict)."""
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Update Problem"
        self._attr_unique_id = "nordpool_update_problem_binary_sensor"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="Nordpool EE Prices",
            manufacturer="Custom Scraper",
            model="15-Minute Market Resolution",
        )

    @property
    def available(self):
        """Always available — this sensor must keep reporting when updates fail."""
        return True

    @property
    def is_on(self):
        return bool(self.coordinator.get_failures())

    @property
    def extra_state_attributes(self):
        failures = self.coordinator.get_failures()
        return {
            "failed_components": sorted(failures),
            "failures": list(failures.values()),
        }
