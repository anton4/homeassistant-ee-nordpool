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

# Forecast source options (values shown/stored by the "Forecast Source" select entity).
# The labels name the data provider so the dropdown is self-explanatory.
OPTION_NONE = "None"
OPTION_FI = "Finland (FI) - nordpool-predict-fi"
OPTION_EE = "Estonia (EE) - eupowerprices.com"
FORECAST_OPTIONS = [OPTION_NONE, OPTION_FI, OPTION_EE]

# Pre-2026.7.10 cached values mapped to the new provider-labelled options
LEGACY_FORECAST_SOURCES = {
    "Finland (FI)": OPTION_FI,
    "Estonia (EE)": OPTION_EE,
}

# eupowerprices.com EE price forecast API
EE_FORECAST_URL = "https://api.eupowerprices.com/v1/forecasts/EE/latest"
FORECAST_POLL_HOURS = 1

# EMHASS automation defaults
DEFAULT_EMHASS_AUTO_MPC = False
DEFAULT_EMHASS_MPC_INTERVAL = 15  # minutes between automatic MPC runs

# EMHASS services/actions whose last run is tracked, mapped to a friendly sensor name
EMHASS_SERVICE_LABELS = {
    "run_mpc_optim": "EMHASS Last MPC",
    "publish_data": "EMHASS Last Publish",
    "fit_ml_model": "EMHASS Last Fit",
    "tune_ml_model": "EMHASS Last Tune",
    "predict_ml_model": "EMHASS Last Predict",
}
