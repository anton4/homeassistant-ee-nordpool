import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import *

class NordpoolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Nordpool EE Prices", data=user_input)

        schema = vol.Schema({
            vol.Required("fast_interval", default=5): vol.All(int, vol.Range(min=1, max=15)),
            vol.Required("slow_interval", default=1): vol.All(int, vol.Range(min=1, max=5)),
            vol.Required("margin", default=DEFAULT_MARGIN): vol.Coerce(float),
            vol.Required("taastuv", default=DEFAULT_TAASTUV): vol.Coerce(float),
            vol.Required("aktsiis", default=DEFAULT_AKTSIIS): vol.Coerce(float),
            vol.Required("elektrilevi_day", default=DEFAULT_ELEKTRILEVI_DAY): vol.Coerce(float),
            vol.Required("elektrilevi_night", default=DEFAULT_ELEKTRILEVI_NIGHT): vol.Coerce(float),
            vol.Required("tasakaal", default=DEFAULT_TASAKAAL): vol.Coerce(float),
            vol.Required("varustus", default=DEFAULT_VARUSTUS): vol.Coerce(float),
            vol.Required("vat", default=DEFAULT_VAT): vol.Coerce(float),
            vol.Required("export_margin", default=DEFAULT_EXPORT_MARGIN): vol.Coerce(float),
            vol.Required("export_tasakaal", default=DEFAULT_EXPORT_TASAKAAL): vol.Coerce(float),
            vol.Required("extend_fi", default=DEFAULT_EXTEND_FI): bool,
            vol.Required("extend_fi_days", default=DEFAULT_EXTEND_FI_DAYS): vol.All(int, vol.Range(min=1, max=7)),
        })
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

        schema = vol.Schema({
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
            vol.Required("export_margin", default=get_val("export_margin", DEFAULT_EXPORT_MARGIN)): vol.Coerce(float),
            vol.Required("export_tasakaal", default=get_val("export_tasakaal", DEFAULT_EXPORT_TASAKAAL)): vol.Coerce(float),
            vol.Required("extend_fi", default=get_val("extend_fi", DEFAULT_EXTEND_FI)): bool,
            vol.Required("extend_fi_days", default=get_val("extend_fi_days", DEFAULT_EXTEND_FI_DAYS)): vol.All(int, vol.Range(min=1, max=7)),
        })
        
        return self.async_show_form(step_id="init", data_schema=schema)
