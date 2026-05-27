import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import *

def get_schema(entry=None):
    """Helper to get the schema with defaults from existing entry if available."""
    def get_val(key, default):
        if entry:
            return entry.options.get(key, entry.data.get(key, default))
        return default

    return vol.Schema({
        vol.Required("fast_interval", default=get_val("fast_interval", 5)): vol.All(int, vol.Range(min=1, max=15)),
        vol.Required("slow_interval", default=get_val("slow_interval", 1)): vol.All(int, vol.Range(min=1, max=5)),
        vol.Required("margin", default=get_val("margin", DEFAULT_MARGIN)): vol.Coerce(float),
        vol.Required("taastuv", default=get_val("taastuv", DEFAULT_TAASTUV)): vol.Coerce(float),
        vol.Required("aktsiis", default=get_val("aktsiis", DEFAULT_AKTSIIS)): vol.Coerce(float),
        vol.Required("elektrilevi_day", default=get_val("elektrilevi_day", DEFAULT_ELEKTRILEVI_DAY)): vol.Coerce(float),
        vol.Required("elektrilevi_night", default=get_val("elektrilevi_night", DEFAULT_ELEKTRILEVI_NIGHT)): vol.Coerce(float),
        vol.Required("tasakaal", default=get_val("tasakaal", DEFAULT_TASAKAAL)): vol.Coerce(float),
        vol.Required("varustus", default=get_val("varustus", DEFAULT_VARUSTUS)): vol.Coerce(float),
        vol.Required("vat", default=get_val("vat", DEFAULT_VAT)): vol.Coerce(float),
    })

class NordpoolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Nordpool EE Prices", data=user_input)
        return self.async_show_form(step_id="user", data_schema=get_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NordpoolOptionsFlow(config_entry)

class NordpoolOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=get_schema(self.config_entry))
