# Nordpool EE 15-Minute Price Scraper

A custom Home Assistant integration that fetches 15-minute interval Nordpool Day-Ahead electricity prices for the Estonian (`EE`) delivery area. It automatically computes real-time **Import Costs** (factoring in Elektrilevi transmission, excise duties, renewable energy fees, and VAT) and **Export Costs** (for net-metering solar or battery configurations) via an easy-to-use user interface.

---

## Features

* **15-Minute Resolution:** Fully compatible with the updated 15-minute Nordpool market intervals for Estonia.
* **Persistent Storage:** Caches data directly to disk (`.storage/`). It recovers instantly after a Home Assistant reboot without hitting the API again or hitting rate limits.
* **Smart Polling Logic:** Intelligently checks for tomorrow's prices after 13:45 and automatically locks out redundant requests once prices are marked as `Final`.
* **Dynamic Import Tariffs:** Handles complex split day/night Elektrilevi transmission grids, automatic Estonian holiday detection (via `holidays` library), and custom margin multipliers.
* **Adjustable Export Tariffs:** Dynamically deducts custom broker margins and balancing fees from the raw spot price for precise solar/battery yield tracking.
* **UI Configurable:** No YAML configuration required. All thresholds, fees, and intervals are adjustable via **Settings > Devices & Services > Configure**.

---

## Sensors Created

The integration populates the following entities:

| Sensor Name | Unique ID | Description |
| --- | --- | --- |
| `sensor.nordpool_raw_prices_ee` | `nordpool_prices_ee_sensor` | The raw spot price straight from the Nordpool API (converted to €/kWh). Contains the entire 48-hour price array in its extra state attributes. |
| `sensor.nordpool_prices_state` | `nordpool_prices_state_sensor` | Displays the current API status for tomorrow's price window (`Waiting`, `Preliminary`, or `Final`). |
| `sensor.nordpool_import_cost_ee` | `nordpool_import_cost_ee_sensor` | Computed grid-delivery price including your current time-of-use transmission, excise, margin, and VAT. |
| `sensor.nordpool_export_cost_ee` | `nordpool_export_cost_ee_sensor` | Computed net production yield price (`Spot - Margin - Balancing Fee`). |

---

## Installation

### Method 1: Custom Repository via HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed and working.
2. Go to **HACS** > **Integrations**.
3. Click the three dots in the top right corner and select **Custom repositories**.
4. Paste the URL of this GitHub repository into the **Repository** field.
5. Choose **Integration** as the Category and click **Add**.
6. Find **Nordpool EE Prices** in the list, click **Download**, and restart Home Assistant.

### Method 2: Manual Installation

1. Download the source code as a `.zip` file.
2. Extract the archive and copy the `nordpool_ee_scraper` folder.
3. Paste it into your Home Assistant directory inside `custom_components/` (create the folder if it does not exist):
```text
config/custom_components/nordpool_ee_scraper/

```


4. Restart Home Assistant.

---

## Setup & Configuration

1. In Home Assistant, navigate to **Settings** > **Devices & Services**.
2. Click **+ Add Integration** in the bottom right.
3. Search for **Nordpool EE Prices** and select it.
4. Fill out your initial setup options in the form wrapper.

To adjust parameters down the line, click **Configure** directly on the integration's card.

### Available Parameters

* **Fast Polling Interval:** Frequency (in minutes) the scraper retries when waiting for the price window to open (Default: `5`).
* **Slow Polling Interval:** Frequency (in hours) the scraper updates under normal steady conditions (Default: `1`).
* **Import Fees (€/kWh):** Broker Margin, Renewable Energy Fee (*Taastuvenergiatasu*), Electricity Excise (*Elektriaktsiis*), Balancing Service Fee (*Tasakaalustusosa*), and Security of Supply Fee.
* **Elektrilevi Transmission (€/kWh):** Split fields for Daytime and Nighttime/Weekend/Holiday pricing rates.
* **VAT (%):** Your country's value-added tax percentage rate (e.g., `24.0`).
* **Export Fees (€/kWh):** Production margin overhead and outbound balancing service fees.

---

## Frontend Dashboard Visualization

Because Home Assistant's native history graphs cannot display future prediction arrays, it is highly recommended to use the custom [ApexCharts Card](https://github.com/RomRider/apexcharts-card) (available in HACS Frontend) to chart your 48-hour price outlook.

Add a **Manual Card** to your dashboard and paste the following configuration to easily compare Import vs. Export trajectories:

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
  - entity: sensor.nordpool_import_cost_ee
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
  - entity: sensor.nordpool_export_cost_ee
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
> This integration fetches data directly via public endpoints and performs calculations strictly for automation and reference purposes. Always verify values alongside your official utility portal statements before executing heavy structural load automations.
