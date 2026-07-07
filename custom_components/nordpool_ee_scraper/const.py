DOMAIN = "nordpool_ee_scraper"

# Default Tariff Settings (€/kWh)
DEFAULT_MARGIN = 0.00328
DEFAULT_TAASTUV = 0.0084
DEFAULT_AKTSIIS = 0.0021
DEFAULT_ELEKTRILEVI_DAY = 0.0369
DEFAULT_ELEKTRILEVI_NIGHT = 0.021
DEFAULT_TASAKAAL = 0.00373
DEFAULT_VARUSTUS = 0.00758
DEFAULT_VAT = 24.0

# New Export Tariff Defaults (€/kWh)
DEFAULT_EXPORT_MARGIN = 0.01
DEFAULT_EXPORT_TASAKAAL = 0.00373

# FI Extension Defaults
DEFAULT_EXTEND_FI = False
DEFAULT_EXTEND_FI_DAYS = 1

# Forecast source options (values shown/stored by the "Forecast Source" select entity)
OPTION_NONE = "None"
OPTION_FI = "Finland (FI)"
OPTION_EE = "Estonia (EE)"
FORECAST_OPTIONS = [OPTION_NONE, OPTION_FI, OPTION_EE]

# eupowerprices.com EE price forecast API
EE_FORECAST_URL = "https://api.eupowerprices.com/v1/forecasts/EE/latest"
FORECAST_POLL_HOURS = 1
