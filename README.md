# sim.de Home Assistant Integration

Track the data allowance of your sim.de (Drillisch Online) SIM from Home Assistant. The integration signs into the Servicewelt the same way your browser does, reads the current and previous billing month, and exposes how much data is left — so a dashboard can show the gauge and an automation can warn you before the Datenautomatik buys another 300 MB at 13× the in-plan rate.

[![Home Assistant][ha_badge]][ha_link] [![HACS][hacs_badge]][hacs_link] [![GitHub Release][release_badge]][release]

## Table of contents

**[`Installation`](#installation)** **[`Configuration`](#configuration)** **[`Entities`](#entities)** **[`Attributes`](#attributes)** **[`Examples`](#examples)** **[`How it works`](#how-it-works)** **[`Development`](#development)**
<br>

## Installation

#### HACS (Recommended)

This integration is not in the default HACS store, so add it as a custom repository first:

<div align="left">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=Rishi8078&repository=simde-homeassistant&category=integration" target="_blank" rel="noopener noreferrer">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS" width="200">
  </a>
</div>

Or manually: **HACS → Integrations → ⋮ → Custom repositories**, paste
`https://github.com/Rishi8078/simde-homeassistant`, choose category **Integration**, then install **sim.de** and restart Home Assistant.

#### Manual installation

1. Download the latest [release](https://github.com/Rishi8078/simde-homeassistant/releases).
2. Copy the `custom_components/sim_de` folder into your Home Assistant `config/custom_components/` directory, so that `config/custom_components/sim_de/manifest.json` exists.
3. Restart Home Assistant.

#### Add the integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **sim.de**.
3. Sign in with the credentials you use on [service.sim.de](https://service.sim.de).

The entry is named after the phone number the account belongs to, so a second SIM can be added as its own entry.

## Configuration

Everything is configured through the UI. No YAML is required.

| Option | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `username` | string | required | Your Servicewelt alias, email or customer number. |
| `password` | string | required | Your Servicewelt password. Used to obtain a session cookie and kept only in the config entry; it is never written to the log. |
| `scan_interval` | int | `1800` | Seconds between polls, set under **Configure**. Minimum 300. |

> [!NOTE]
> The Servicewelt refreshes its usage counters only a few times a day and explicitly says the display is not real-time. Polling every 30 minutes is already more often than the data changes; there is nothing to gain from going lower, and every poll is a full login-backed page load.

## Entities

Seven sensors on one device.

| Entity | State | Category |
| :-- | :-- | :-- |
| `sensor.<name>_data_used` | GB used this billing month | |
| `sensor.<name>_data_remaining` | GB left before the allowance runs out | |
| `sensor.<name>_data_usage` | % of the allowance used | |
| `sensor.<name>_data_allowance` | GB included this month, top-ups included | Diagnostic |
| `sensor.<name>_previous_month_data_used` | GB used last month | Diagnostic |
| `sensor.<name>_previous_month_data_usage` | % of last month's allowance | Diagnostic |
| `sensor.<name>_plan` | Tariff name, e.g. `Allnet Flat 10 + 6 GB` | Diagnostic |

`Data used` is a `total_increasing` sensor, so it feeds long-term statistics and resets cleanly when the billing month rolls over.

## Attributes

**Data used** and **Previous month data used**:

| Attribute | Example | Meaning |
| :-- | :-- | :-- |
| `used_gb` | `15.58` | Data used in the month |
| `allowance_gb` | `16.0` | Included volume, automatic top-ups included |
| `remaining_gb` | `0.42` | What is left, floored at zero |
| `auto_topup` | `davon 3 x 300,00 MB Datenautomatik` | Only present once the Datenautomatik has bought extra volume |

**Plan**:

| Attribute | Example |
| :-- | :-- |
| `tariff_code` | `5EF` |
| `package_code` | `V5L22` |
| `network` | `1&1 5G Netz` |
| `phone_number` | `017600000000` |
| `customer_number` | `C1234567` |
| `billing` | `Postpaid - Monatliche Rechnung` |
| `minimum_term` | `24 Monate` |
| `notice_period` | `1 Monat` |

## Examples

#### Warn before the Datenautomatik triggers

The automatic top-up buys 300 MB at a time, at roughly thirteen times the per-GB price of the plan itself. This fires once, while there is still time to switch to Wi-Fi:

```yaml
automation:
  - alias: "Mobile data almost used up"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.sim_de_data_remaining
        below: 1
    actions:
      - action: notify.mobile_app
        data:
          title: "Mobile data running out"
          message: >-
            {{ states('sensor.sim_de_data_remaining') }} GB left of
            {{ states('sensor.sim_de_data_allowance') }} GB.
```

#### Notice that it already triggered

```yaml
automation:
  - alias: "Datenautomatik bought extra data"
    triggers:
      - trigger: state
        entity_id: sensor.sim_de_data_used
        attribute: auto_topup
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.auto_topup is defined }}"
    actions:
      - action: notify.mobile_app
        data:
          message: "sim.de topped up: {{ trigger.to_state.attributes.auto_topup }}"
```

#### Dashboard card

```yaml
type: gauge
entity: sensor.sim_de_data_usage
name: Mobile data
min: 0
max: 100
severity:
  green: 0
  yellow: 75
  red: 95
```

## How it works

sim.de publishes no API, so the integration reads the same pages the Servicewelt serves to a browser:

1. `GET /start` renders the login form with a per-session Symfony CSRF token.
2. `POST /public/login_check` exchanges username, password and that token for a session cookie.
3. `GET /mytariff/tariff/showTariffInfo`, `/mytariff/overview` and `/mytariff/invoice/showGprsDataUsage` return the tariff and usage pages.

Two shapes are parsed out of the HTML. The tariff facts sit in labelled `c-key_value_container` rows (`Tarif`, `Mobilfunknetz`, `Kundennummer`, …). The usage figures sit in two tabs, `#tab-cur` and `#tab-mon`, each reading `15,58 GB von 16,00 GB verbraucht` — with `(davon 3 x 300,00 MB Datenautomatik)` appended once the automatic top-up has bought extra volume.

Three quirks of the Servicewelt shape the parsing:

- **The tariff name is only on `showTariffInfo`.** The overview page carries a `digitalData` object that looks promising but ships `"product.eppixTariffName" : ""` — empty. It is used only as a fallback, and only when non-empty.
- **The allowance moves.** `allowance_gb` is what the Servicewelt currently shows, so a month where the Datenautomatik fired reads 16.88 GB rather than the plan's 16 GB. That is why `data_usage` can exceed 100 %.
- **The session is a cookie.** The integration creates its own `aiohttp` session rather than sharing Home Assistant's, so its cookie jar stays isolated. If the session expires mid-poll, the Servicewelt answers with the login form instead of an error; that is detected and the login is repeated once.

Everything the integration does is read-only. It never changes a tariff, books an option or spends money.

There are no third-party requirements: the parsing runs on the standard library's `html.parser`, so nothing is installed into your Home Assistant environment.

## Development

The integration needs no build step and no third-party package. Copy `custom_components/sim_de` into a Home Assistant config directory, restart, and watch `home-assistant.log` — the client logs at debug level under `custom_components.sim_de`.

```yaml
logger:
  logs:
    custom_components.sim_de: debug
```

`models.py` holds all the parsing and touches no network, so it can be exercised on a saved page without Home Assistant running. When the Servicewelt markup changes, that is the file to update: its `HTMLParser` subclasses read the `c-key_value_container` rows and the `#tab-cur` / `#tab-mon` text, and everything downstream works on their output.

Every example value in this README is invented. No real customer number, phone number or password is in this repository.

## Disclaimer

Not affiliated with, endorsed by, or supported by sim.de, Drillisch Online GmbH or 1&1. It reads your own account through the public Servicewelt. If sim.de changes its pages, the integration can break until the parsing is updated.

[ha_badge]: https://img.shields.io/badge/Home%20Assistant-2024.11%2B-41BDF5?logo=home-assistant&logoColor=white
[ha_link]: https://www.home-assistant.io
[hacs_badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs_link]: https://hacs.xyz
[release_badge]: https://img.shields.io/github/v/release/Rishi8078/simde-homeassistant
[release]: https://github.com/Rishi8078/simde-homeassistant/releases
