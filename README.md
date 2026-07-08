# Nordpool EE 15-Minute Prices + Forecasts + EMHASS

A custom Home Assistant integration that fetches 15-minute interval Nordpool Day-Ahead electricity prices for the Estonian (`EE`) delivery area. On top of the raw spot price it computes real-time **Import Costs** (Elektrilevi transmission, excise, renewable-energy and balancing fees, and VAT) and **Export Costs** (for net-metering solar/battery setups), can **extend the price curve into the future** using either a Finnish (FI) price forecast or an Estonian (EE) price forecast from [eupowerprices.com](https://eupowerprices.com), reshapes **Solcast** PV forecasts into the same 15-minute grid, and exposes a set of **EMHASS** services for machine-learning load forecasting and battery/EV Model Predictive Control (MPC) optimization.

> **Integration domain:** `nordpool_ee_scraper` — the folder inside `custom_components/` **must** be named `nordpool_ee_scraper` for Home Assistant to load it (see [Installation](#installation)).

---

## Features

* **15-Minute Resolution:** Fully compatible with the 15-minute Nordpool market intervals for Estonia.
* **Persistent Storage:** Caches data to disk via Home Assistant's `Store` helper (`.storage/nordpool_ee_scraper_cache`). Prices and the selected forecast survive a restart without re-hitting the API.
* **Smart Polling Logic:** Polls today's prices as needed, waits until **13:45** local time before probing for tomorrow's prices, switches to a fast retry interval during the publish window (13:45–15:00), and locks out redundant requests once tomorrow's prices are marked `Final`.
* **Dynamic Import Tariffs:** Handles split day/night Elektrilevi transmission rates with automatic Estonian holiday detection (via the `holidays` library), then applies margin and VAT.
* **Export Tariffs:** Deducts a broker margin and balancing fee from the raw spot price for solar/battery yield tracking.
* **Selectable Price Forecast:** A **Forecast Source** selector chooses how to extend the price curve beyond the last published spot hour:
  * **None** — actual spot prices only.
  * **Finland (FI)** — merges a Finnish price forecast from a separate `sensor.nordpool_predict_fi_price`.
  * **Estonia (EE)** — merges the [eupowerprices.com](https://eupowerprices.com) EE price forecast (requires an API key).
* **Solcast Reshaping (optional):** Converts Solcast PV forecast sensors from 30-minute kW into 15-minute W values, aligned to the remaining price horizon — ready to feed into EMHASS.
* **EMHASS Services (optional):** Fit / tune / predict an ML load forecaster and run a `naive-mpc-optim` battery + EV charging optimization against a local [EMHASS](https://emhass.readthedocs.io/) instance — with an optional built-in MPC scheduler (next-run ETA sensor) and per-service last-run debug sensors (status, HTTP code, duration, response, payload).
* **UI Configurable:** No YAML required. Tariffs, intervals, and the API key are set through the config flow; the forecast source and horizon are live entities.

---

## How It Works

### Polling & state machine
The coordinator runs on a 1-minute tick but throttles actual API calls:

* Before **13:45** it only ensures today's prices are present.
* From **13:45 to 15:00** it uses the **fast interval** (minutes) to retry for tomorrow's prices.
* Otherwise it uses the **slow interval** (hours).
* Once tomorrow's window reports `Final`, further polling is suppressed until the next day's 13:45.
* The **Force Update** button bypasses all throttling for an immediate refresh.

Prices are fetched from the public Nordpool data portal:
`https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?...&deliveryArea=EE&currency=EUR`, converted from €/MWh to €/kWh, and keyed by local start time.

### Import cost formula
For each 15-minute period the transmission rate is chosen by time of use:

* **Night/weekend/holiday rate** applies when the hour is `< 07:00` or `>= 22:00`, on Saturdays/Sundays, or on Estonian public holidays.
* **Day rate** applies otherwise.

```
tariff       = margin + taastuv + aktsiis + tasakaal + varustus + (elektrilevi_day | elektrilevi_night)
import_cost  = (spot_price + tariff) × (1 + VAT/100)
```

### Export cost formula
```
export_cost  = spot_price − export_margin − export_tasakaal
```
(No VAT is applied to export.)

### Forecast extension
When the **Forecast Source** is not `None`, the chosen forecast's hourly values are expanded into 15-minute blocks and appended after the last actual EE period, up to **Forecast Extend Days** into the future. Extended periods are flagged with `is_forecast: true` in the price arrays and flow through every downstream calculation (import/export cost, EMHASS, etc.).

---

## Entities Created

All entities are grouped under a single **Nordpool EE Prices** device, so their IDs are prefixed with `nordpool_ee_prices_`.

### Sensors

| Entity ID | Name | State | Key Attributes |
| --- | --- | --- | --- |
| `sensor.nordpool_ee_prices_raw_prices` | Raw Prices | `N periods loaded` | `prices` (full array of `{start, end, value}`, incl. forecast blocks), `last_poll_time` |
| `sensor.nordpool_ee_prices_prices_state` | Prices State | `Waiting` / `Preliminary` / `Final` | `status_today`, `http_code_today`, `status_tomorrow`, `http_code_tomorrow`, `forecast_source`, `forecast_status`, `http_code_forecast` |
| `sensor.nordpool_ee_prices_import_cost` | Import Cost | `N calculated` | `prices` (import cost per period, incl. VAT & transmission) |
| `sensor.nordpool_ee_prices_export_cost` | Export Cost | `N calculated` | `prices` (export yield per period) |
| `sensor.nordpool_ee_prices_prices_from_now` | Prices From Now | count of remaining 15-min periods | `timestamps_left`, `import_prices`, `export_prices` (future-only value arrays; consumed by EMHASS MPC) |
| `sensor.nordpool_ee_prices_solcast_forecast_15min` | Solcast Forecast 15min | count of forecast values | `values` (PV power forecast in **W**, 15-min resolution, aligned to the remaining price horizon) |
| `sensor.nordpool_ee_prices_last_poll_time` | Last Poll Time | timestamp | — |
| `sensor.nordpool_ee_prices_next_poll_time` | Next Poll Time | timestamp | — |
| `sensor.nordpool_ee_prices_emhass_next_run` | EMHASS Next Run | timestamp (ETA of next auto MPC) | `auto_mpc_enabled`, `interval_minutes`, `last_scheduled_run` |
| `sensor.nordpool_ee_prices_emhass_last_mpc` | EMHASS Last MPC | timestamp of last MPC call | `status`, `http_code`, `duration_seconds`, `error`, `response`, `payload` |
| `sensor.nordpool_ee_prices_emhass_last_fit` | EMHASS Last Fit | timestamp of last fit call | *(same as above)* |
| `sensor.nordpool_ee_prices_emhass_last_tune` | EMHASS Last Tune | timestamp of last tune call | *(same as above)* |
| `sensor.nordpool_ee_prices_emhass_last_predict` | EMHASS Last Predict | timestamp of last predict call | *(same as above)* |

### Controls

| Entity ID | Type | Purpose |
| --- | --- | --- |
| `button.nordpool_ee_prices_force_update_prices` | Button | Force an immediate poll, bypassing polling throttles. |
| `select.nordpool_ee_prices_forecast_source` | Select | Choose the active forecast source: **None**, **Finland (FI)**, or **Estonia (EE)**. |
| `number.nordpool_ee_prices_forecast_extend_days` | Number (1–7) | How many days beyond the last actual EE hour to extend using the selected forecast. |
| `switch.nordpool_ee_prices_emhass_auto_mpc` | Switch | Enable/disable the integration's automatic EMHASS MPC schedule. |
| `number.nordpool_ee_prices_emhass_mpc_interval` | Number (1–120 min) | Minutes between automatic MPC runs. |

---

## Forecast Sources

Selecting a forecast source extends the price curve beyond the last published EE spot hour. If the required data is unavailable, the sensors fall back to actual prices only.

### Finland (FI) forecast
Reads `sensor.nordpool_predict_fi_price` (its `forecast` attribute — a list of `{timestamp, value}` in **cents/kWh**), converts each hourly value into four 15-minute blocks, and appends the blocks that fall after the last known EE period up to the **Forecast Extend Days** cutoff.

> Requires a separate integration/sensor that publishes `sensor.nordpool_predict_fi_price`.

### Estonia (EE) forecast — eupowerprices.com
Fetches the EE price forecast from the [eupowerprices.com](https://eupowerprices.com) API and merges it the same way as the FI forecast. This is an EE-native forecast, so no cross-border assumptions are needed.

* **Endpoint:** `GET https://api.eupowerprices.com/v1/forecasts/EE/latest`
* **Auth:** `X-API-Key: <your key>` header — set the key in the integration's configuration (see below).
* **Data:** hourly `series` in `EUR/MWh`; the coordinator converts to `€/kWh`, stores it, and refreshes it about once per hour (or immediately when you switch the source or press Force Update).

The API status is surfaced on the **Prices State** sensor's attributes (`forecast_status`, `http_code_forecast`). If no API key is configured, selecting **Estonia (EE)** simply yields no extension.

### Solcast PV forecast reshaping
The **Solcast Forecast 15min** sensor reads the standard [Solcast HA integration](https://github.com/BJReplay/ha-solcast-solar) sensors:

* `sensor.solcast_pv_forecast_forecast_today` … `_day_7`
* `select.solcast_pv_forecast_use_forecast_field` (chooses `estimate` / `estimate10` / `estimate90`)

It flattens their 30-minute `detailedForecast` (kW), doubles each value into 15-minute W buckets, and slices from the current interval to match the number of remaining price periods — producing a `pv_power_forecast` array ready for EMHASS.

---

## EMHASS Integration

The integration registers four services (domain `nordpool_ee_scraper`) that talk to a locally running [EMHASS](https://emhass.readthedocs.io/) instance at **`http://localhost:5001/action`**. These are optional — they only matter if you run EMHASS and want to drive it from the data this integration produces.

> **Note:** The MPC service and the ML services are wired to specific entity IDs from the author's setup (an EV, a house-power sensor, Solcast, etc. — see below). Treat them as a working reference and adapt the entity names in `__init__.py` to your own home.

### Services

| Service | EMHASS endpoint | Description |
| --- | --- | --- |
| `nordpool_ee_scraper.fit_ml_model` | `/action/forecast-model-fit` | Train the ML load forecaster on Home Assistant history. |
| `nordpool_ee_scraper.tune_ml_model` | `/action/forecast-model-tune` | Bayesian hyperparameter/lag search (slow). |
| `nordpool_ee_scraper.predict_ml_model` | `/action/forecast-model-predict` | Predict and publish load to `sensor.p_load_forecast_custom_model`. |
| `nordpool_ee_scraper.run_mpc_optim` | `/action/naive-mpc-optim` | Run the battery + EV charging MPC optimization. |

#### `fit_ml_model` / `tune_ml_model` fields
| Field | Default | Notes |
| --- | --- | --- |
| `historic_days_to_retrieve` | `30` | Days of HA history to pull (9–365). |
| `sklearn_model` | `KNeighborsRegressor` | One of `KNeighborsRegressor`, `RandomForestRegressor`, `GradientBoostingRegressor`, `RidgeRegression`, `MLPRegressor`. |
| `n_trials` *(tune only)* | `10` | Number of optimization trials (5–100). |

Both use `var_model = sensor.house_power_without_deferrable` and `model_type = load_forecast`.

### Automatic horizon / lag sizing
To keep the ML lags consistent with the forecast horizon (and avoid EMHASS clipping arrays), the integration derives its parameters from the current forecast settings:

* **Max lags / horizon:** `192 + (extend_days × 96)` 15-minute steps (192 ≈ 48 h base).
* **Daily horizon limit:** `2 + extend_days` days.
* **History required:** `max(7, lags/96 + 2)` days.
* **Test split length:** `lags / 4` hours.

`extend_days` is `0` when the Forecast Source is **None**, otherwise it equals the **Forecast Extend Days** value.

### MPC optimization (`run_mpc_optim`)
This service assembles a full `naive-mpc-optim` payload from live Home Assistant state:

| Source entity | Role in the payload |
| --- | --- |
| `sensor.nordpool_ee_prices_prices_from_now` | `load_cost_forecast`, `prod_price_forecast`, `prediction_horizon` |
| `sensor.nordpool_ee_prices_solcast_forecast_15min` | `pv_power_forecast` |
| `sensor.ev6_battery_soc` | `soc_init` (÷100) |
| `input_number.emhass_target_soc` | `soc_final` (÷100) |
| `input_boolean.ev_charging_enabled` | Whether the EV is a deferrable load (nominal power 11 kW vs 0) |
| `input_boolean.ev_force_continuous_charging` | `set_deferrable_load_single_constant` |
| `sensor.ev_operating_hours` | `operating_hours_of_each_deferrable_load` |
| `sensor.ev_charging_timesteps` | `end_timesteps_of_each_deferrable_load` |

It also sets a battery deficit penalty (`battery_soc_deficit_threshold = 0.3`, `battery_soc_deficit_cost = 1.5`) so the optimizer is discouraged from leaving the battery below 30% SOC, and passes `publish_data: true` so EMHASS generates its result graphs.

All four services return a response (`SupportsResponse.OPTIONAL`) containing `status`, the HTTP code, the payload that was sent, and the EMHASS response body — useful for debugging from **Developer Tools → Actions**.

### Automatic MPC scheduling & debug sensors

Rather than triggering `run_mpc_optim` from your own automation, the integration can run it on a fixed cadence and expose an accurate ETA:

* **`switch.nordpool_ee_prices_emhass_auto_mpc`** — turn the automatic schedule on/off.
* **`number.nordpool_ee_prices_emhass_mpc_interval`** — minutes between runs (1–120, default 15).
* **`sensor.nordpool_ee_prices_emhass_next_run`** — a timestamp sensor showing when the next MPC run is due (a live countdown in the UI). Its attributes report whether auto MPC is enabled, the interval, and the last scheduled run.

The scheduler is evaluated on the coordinator's 1-minute tick: when enabled, it fires `run_mpc_optim` whenever `now − last_run ≥ interval`. It survives restarts (the last run time and settings are cached to disk). If you enable this, remove any external automation that was calling `run_mpc_optim`, or MPC will run twice.

Every EMHASS call — whether triggered by the schedule, by an automation, or manually — records its outcome, surfaced as timestamp sensors (`EMHASS Last MPC / Fit / Tune / Predict`). Each carries the last call's `status`, `http_code`, `duration_seconds`, `error`, a bounded excerpt of the EMHASS `response`, and the `payload` that was sent, so you can see exactly what happened without digging through logs.

---

## Installation

### Method 1: Custom Repository via HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed and working.
2. Go to **HACS** > **Integrations**.
3. Click the three dots in the top-right corner and select **Custom repositories**.
4. Paste this repository's URL into the **Repository** field.
5. Choose **Integration** as the category and click **Add**.
6. Find **HomeAssistant EE Nordpool** in the list, click **Download**, and restart Home Assistant.

### Method 2: Manual Installation

1. Download / clone this repository.
2. Copy the `nordpool_ee_scraper` folder from this repo's `custom_components/` into your Home Assistant `config/custom_components/` directory:
   ```text
   config/custom_components/nordpool_ee_scraper/
   ```
   (The folder name must remain `nordpool_ee_scraper` — Home Assistant requires the directory name to equal the integration domain.)
3. Restart Home Assistant.

---

## Setup & Configuration

1. In Home Assistant, go to **Settings** > **Devices & Services**.
2. Click **+ Add Integration** and search for **Nordpool EE Prices**.
3. Fill out the setup form.

To adjust parameters later, click **Configure** on the integration's card.

### Available Parameters

* **Fast Polling Interval (minutes):** Retry frequency during the 13:45–15:00 publish window (default `5`, range 1–60).
* **Slow Polling Interval (hours):** Steady-state update frequency (default `1`, range 1–24).
* **eupowerprices.com API Key:** *(optional)* Required only to use the **Estonia (EE)** forecast source. Leave blank if unused.
* **Broker Import Margin (€/kWh):** default `0.00328`.
* **Renewable Energy Fee / Taastuvenergiatasu (€/kWh):** default `0.0084`.
* **Electricity Excise / Elektriaktsiis (€/kWh):** default `0.0021`.
* **Elektrilevi Daytime Transmission (€/kWh):** default `0.0369`.
* **Elektrilevi Night/Weekend/Holiday Transmission (€/kWh):** default `0.021`.
* **Import Balancing Fee / Tasakaalustusosa (€/kWh):** default `0.00373`.
* **Security of Supply Fee / Varustuskindluse tasu (€/kWh):** default `0.00758`.
* **VAT / Käibemaks (%):** default `24.0`.
* **Broker Export Margin Deduction (€/kWh):** default `0.01`.
* **Export Balancing Service Fee (€/kWh):** default `0.00373`.

> All €/kWh fields expect the value in euros (e.g. 1.2 cents = `0.012`).

The **Forecast Source** and **Forecast Extend Days** are controlled live via their entities (no reconfiguration needed).

---

## Frontend Dashboard Visualization

Because Home Assistant's native history graphs cannot display future price arrays, use the custom [ApexCharts Card](https://github.com/RomRider/apexcharts-card) (available in HACS Frontend) to chart the price outlook.

Add a **Manual Card** and paste the following to compare Import vs. Export trajectories:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Nordpool Import vs. Export Cost
  show_states: true
  colorize_states: true
graph_span: 48h
span:
  start: day
now:
  show: true
  label: Now
  color: red
series:
  - entity: sensor.nordpool_ee_prices_import_cost
    type: line
    curve: stepline
    name: Import Cost
    unit: €/kWh
    float_precision: 3
    color: '#e91e63'
    stroke_width: 2
    data_generator: |
      if (!entity.attributes.prices) return [];
      return entity.attributes.prices.map((entry) => {
        return [new Date(entry.start).getTime(), entry.value];
      });
  - entity: sensor.nordpool_ee_prices_export_cost
    type: line
    curve: stepline
    name: Export Cost
    unit: €/kWh
    float_precision: 3
    color: '#4caf50'
    stroke_width: 2
    data_generator: |
      if (!entity.attributes.prices) return [];
      return entity.attributes.prices.map((entry) => {
        return [new Date(entry.start).getTime(), entry.value];
      });
```

---

## Disclaimer

> [!IMPORTANT]
> This integration fetches data via public endpoints and performs calculations strictly for automation and reference purposes. The EMHASS services target a locally hosted EMHASS instance and are wired to entity IDs from the author's own setup — adapt them before use. Always verify values against your official utility portal before running heavy load automations.
