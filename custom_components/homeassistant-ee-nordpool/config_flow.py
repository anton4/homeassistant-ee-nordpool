import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import *


def _num(min_val=None, max_val=None, step=1, unit=None):
    """A number input rendered as a box, with an inline unit suffix."""
    cfg = {"step": step, "mode": selector.NumberSelectorMode.BOX}
    if min_val is not None:
        cfg["min"] = min_val
    if max_val is not None:
        cfg["max"] = max_val
    if unit is not None:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(cfg)


def _build_schema(get):
    """Build the shared config/options schema. `get(key, default)` supplies the field default."""
    fee = dict(min_val=0, step="any", unit="€/kWh")
    return vol.Schema({
        vol.Required("fast_interval", default=get("fast_interval", 5)): _num(1, 60, 1, "min"),
        vol.Required("slow_interval", default=get("slow_interval", 1)): _num(1, 24, 1, "h"),
        vol.Optional("api_key", default=get("api_key", "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
        vol.Required("margin", default=get("margin", DEFAULT_MARGIN)): _num(**fee),
        vol.Required("taastuv", default=get("taastuv", DEFAULT_TAASTUV)): _num(**fee),
        vol.Required("aktsiis", default=get("aktsiis", DEFAULT_AKTSIIS)): _num(**fee),
        vol.Required("elektrilevi_day", default=get("elektrilevi_day", DEFAULT_ELEKTRILEVI_DAY)): _num(**fee),
        vol.Required("elektrilevi_night", default=get("elektrilevi_night", DEFAULT_ELEKTRILEVI_NIGHT)): _num(**fee),
        vol.Required("tasakaal", default=get("tasakaal", DEFAULT_TASAKAAL)): _num(**fee),
        vol.Required("varustus", default=get("varustus", DEFAULT_VARUSTUS)): _num(**fee),
        vol.Required("vat", default=get("vat", DEFAULT_VAT)): _num(0, 100, 0.1, "%"),
        vol.Required("export_margin", default=get("export_margin", DEFAULT_EXPORT_MARGIN)): _num(**fee),
        vol.Required("export_tasakaal", default=get("export_tasakaal", DEFAULT_EXPORT_TASAKAAL)): _num(**fee),
    })


class NordpoolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Nordpool EE Prices", data=user_input)

        schema = _build_schema(lambda key, default: default)
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NordpoolOptionsFlow()


class NordpoolOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def get_val(key, default):
            return self.config_entry.options.get(key, self.config_entry.data.get(key, default))

        return self.async_show_form(step_id="init", data_schema=_build_schema(get_val))
