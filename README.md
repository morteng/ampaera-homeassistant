<p align="center">
  <img src="custom_components/ampaera/logo.png" alt="Ampæra Energy" width="400">
</p>

<h1 align="center">Ampæra Energy - Home Assistant Integration</h1>

<p align="center">
  <a href="https://github.com/morteng/ampaera-homeassistant/releases"><img src="https://img.shields.io/github/release/morteng/ampaera-homeassistant.svg" alt="GitHub Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="https://github.com/hacs/default"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg" alt="HACS Custom"></a>
</p>

<p align="center">
  Home Assistant custom integration for the <strong>Ampæra Smart Home Energy Management Platform</strong>.
</p>

## Features

- **OAuth2 Authentication** - Secure sign-in with your Ampæra account (recommended)
- **Auto-Dashboard** - Ready-to-use Lovelace dashboard created automatically
- **Regenerate Dashboard** - Fix broken dashboards via Settings → Configure
- **Embedded Simulation** - Test without hardware (no separate integration needed)
- **Real-time power monitoring** from Norwegian AMS smart meters
- **Energy tracking** compatible with Home Assistant Energy Dashboard
- **Device control** for water heaters and EV chargers
- **Nord Pool spot prices** with cost calculations
- **Multi-site support** for homes with multiple properties (hytte)
- **Norwegian translations** (Bokmål)

## Requirements

- Home Assistant 2024.1.0 or newer
- Ampæra account (free or with active subscription)

---

## Installation

### HACS Installation (Recommended)

> **Note**: We're awaiting acceptance into the HACS default repository. Until then, add us as a custom repository (step 2-5 below).

1. Open **HACS** in Home Assistant
2. Click the **⋮** menu (top right) → **Custom repositories**
3. Add repository: `morteng/ampaera-homeassistant`
4. Select category: **Integration**
5. Click **Add**
6. Search for **"Ampæra"** in HACS Integrations
7. Click **Download** → **Download** again to confirm
8. Restart Home Assistant (Settings → System → Restart)

### Manual Installation

**Quick Install:**

1. Download the [latest release](https://github.com/morteng/ampaera-homeassistant/releases) (`ampaera.zip`)
2. Extract and copy the `ampaera` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant (Settings → System → Restart)

**Your folder structure should look like:**
```
config/
└── custom_components/
    └── ampaera/
        ├── __init__.py
        ├── manifest.json
        └── ... (other files)
```

For detailed instructions, alternative installation methods, and troubleshooting, see the **[Full Installation Guide](docs/INSTALLATION.md)**.

### Step 2: Add the Integration

After restarting Home Assistant:

1. Go to **Settings → Devices & Services**
2. Click the **+ Add Integration** button (bottom right)
3. Search for **"Ampæra"** or **"Ampæra Energy"**
4. Click on it to start the setup wizard

### Step 3: Choose Authentication Method

You'll see two options:

| Method | Description | Recommended For |
|--------|-------------|-----------------|
| **Sign in with Ampæra** | OAuth2 - Click to authenticate with your Ampæra account | Most users ✅ |
| **API Key** | Manual entry of API key from Ampæra settings | Advanced users, local setups |

#### Option A: OAuth2 (Recommended)

1. Select **"Connect with Ampæra Account"**
2. Click **Submit**
3. You'll be redirected to Ampæra's login page
4. Log in with your Ampæra credentials
5. Click **Authorize** to grant Home Assistant access
6. You'll be redirected back to Home Assistant

#### Option B: API Key (Advanced)

1. Select **"Use API Key"**
2. Log in to [ampæra.no](https://xn--ampra-ura.no) → **Settings → API**
3. Click **Generate Token** and copy the key
4. Paste the API key in Home Assistant
5. Click **Submit**

### Step 4: Choose Installation Mode

| Mode | Description | Use Case |
|------|-------------|----------|
| **Real Devices** | Connects to your physical smart devices | Production use |
| **Simulation** | Creates embedded simulated devices | Demos, testing |

> **Simulation Mode**: Automatically creates simulated AMS meter, water heater, and EV charger with realistic behavior. No separate integration required.

> **Note**: Modes are mutually exclusive. You cannot mix simulated and real devices.

### Step 5: Configure Your Site

1. Enter a **Site Name** (e.g., "Home", "Cabin")
2. Select your **Grid Region** (NO1-NO5) for accurate spot pricing

### Step 6: Select Devices (Real Devices Mode)

Choose which discovered devices to sync with Ampæra:
- EV chargers
- Water heaters
- Power meters
- Smart plugs

### Step 7: Done! 🎉

After setup completes:

1. **Dashboard**: A ready-to-use Lovelace dashboard is automatically created
   - Go to **Settings → Dashboards** to enable it
   - Look for **"Ampæra Energy"** or **"Ampæra {site name}"**

2. **Notification**: You'll receive a notification with setup confirmation

3. **Energy Dashboard**: Optionally add to HA's Energy Dashboard:
   - Go to **Settings → Dashboards → Energy**
   - Click **Add consumption** under Electricity Grid
   - Select **"Ampæra {site} Total Energy"**

---

## Supported Devices

The integration automatically discovers and supports a wide range of smart energy devices.

### EV Chargers (24+ integrations)

| Brand | Integration | Region |
|-------|-------------|--------|
| Easee | `easee` | Nordic |
| Zaptec | `zaptec` | Nordic |
| Wallbox | `wallbox` | EU |
| DEFA | `defa` | Nordic |
| Garo | `garo` | Nordic |
| ELKO | `elko_wallbox` | Nordic |
| CTEK | `ctek` | Nordic |
| ABB | `abb_terra` | EU |
| Schneider | `schneider_evlink` | EU |
| KEBA | `keba` | EU |
| MENNEKES | `mennekes` | EU |
| Charge Amps | `charge_amps` | Nordic |
| Tesla Wall Connector | `tesla`, `teslafi` | Global |
| Ohme | `ohme` | UK/EU |
| Hypervolt | `hypervolt` | UK |
| myenergi | `myenergi_zappi` | UK/EU |
| go-eCharger | `go_e` | EU |
| OpenEVSE | `openevse` | Global |
| Juicebox | `juicebox` | US |
| *Generic OCPP* | `ocpp` | Standard |

### Water Heaters (14+ integrations)

| Brand | Integration | Region |
|-------|-------------|--------|
| Høiax | `hoiax`, `heatzy` | Norway |
| OSO | `oso_energy` | Nordic |
| Millheat | `mill` | Nordic |
| Adax | `adax` | Nordic |
| Nobø | `nobo_hub` | Nordic |
| Glen Dimplex | `dimplex` | EU |
| Tado | `tado` | EU |
| Netatmo | `netatmo` | EU |
| Shelly | `shelly` | Global |
| Aquanta | `aquanta` | US |
| Rheem | `rheem_eziset` | US |
| *Generic climate* | `climate`, `water_heater` | Standard |

### Power Meters (18+ integrations)

| Brand | Integration | Region |
|-------|-------------|--------|
| Tibber | `tibber` | Nordic |
| Elvia / Eloverblik | `eloverblik` | Nordic |
| Entur / Elhub | `elhub` | Norway |
| P1 Monitor | `p1_monitor` | Nordic |
| DSMR | `dsmr` | NL/EU |
| Futurehome | `futurehome` | Nordic |
| Heatit | `heatit` | Nordic |
| HomeWizard | `homewizard` | EU |
| IoTaWatt | `iotawatt` | Global |
| Emporia Vue | `emporia_vue` | US |
| Sense | `sense` | US |
| Shelly EM | `shelly` | Global |
| ESPHome | `esphome` | DIY |
| Growatt | `growatt_server` | Global |

### Detection Methods

The integration uses a three-tier detection hierarchy:

1. **Integration matching**: Identifies devices by their Home Assistant integration domain
2. **Device class signals**: Uses HA device classes (`energy`, `power`, `ev_charger`, `water_heater`)
3. **Keyword detection**: Norwegian and English keywords for flexible matching

Norwegian keywords supported: `elbillader`, `varmtvannsbereder`, `strømmåler`, `lader`, `ladestasjon`

---

## Entities

### Sensors

| Entity | Description | Unit |
|--------|-------------|------|
| Power | Current power consumption | W |
| Energy today | Energy consumed today | kWh |
| Total energy | Cumulative energy | kWh |
| Cost today | Cost for today | NOK |
| Spot price | Current Nord Pool price | NOK/kWh |
| Voltage L1/L2/L3 | Phase voltages | V |
| Current L1/L2/L3 | Phase currents | A |

### Controls

| Entity | Description | Commands |
|--------|-------------|----------|
| Water heater | Temperature and mode control | `turn_on`, `turn_off`, `set_temperature` |
| EV charger | Charging control | `turn_on`, `turn_off`, `start_charge`, `stop_charge`, `set_current_limit` |
| Device switch | On/off control | `turn_on`, `turn_off` |

---

## Example Automations

### Notify on high power usage

```yaml
automation:
  - alias: "Notify high power"
    trigger:
      - platform: numeric_state
        entity_id: sensor.ampaera_home_power
        above: 5000
    action:
      - service: notify.mobile_app
        data:
          message: "High power usage: {{ states('sensor.ampaera_home_power') }} W"
```

### Eco mode during peak prices

```yaml
automation:
  - alias: "Water heater eco during peak"
    trigger:
      - platform: numeric_state
        entity_id: sensor.ampaera_spot_price_no1
        above: 1.0
    action:
      - service: water_heater.set_operation_mode
        target:
          entity_id: water_heater.ampaera_water_heater
        data:
          operation_mode: eco
```

### Smart EV charging during low prices

```yaml
automation:
  - alias: "Start EV charging when prices are low"
    trigger:
      - platform: numeric_state
        entity_id: sensor.ampaera_spot_price_no1
        below: 0.50
    condition:
      - condition: state
        entity_id: binary_sensor.ev_connected
        state: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.ampaera_ev_charger
```

---

## Troubleshooting

### Cannot connect to Ampæra

- Verify your credentials are correct
- Check your internet connection
- Ensure Ampæra services are online at [status.ampaera.no](https://status.ampaera.no)

### OAuth authentication failed

- Clear your browser cache and try again
- Ensure you're logged in to your Ampæra account
- Try using the API key method as fallback

### Entities show "unavailable"

- The integration may be temporarily disconnected
- Check Settings → Devices & Services → Ampæra for status
- Try reloading the integration

### Devices not discovered

- Ensure your device integration is properly configured in Home Assistant
- Check that the device has the correct device class (energy, power, etc.)
- Try adding the device manually if automatic discovery fails

### Dashboard not appearing

- Go to **Settings → Dashboards**
- Look for the Ampæra dashboard and click to enable it
- The dashboard is created in `config/dashboards/` folder

### Dashboard shows "Entity not found" errors

This happens when upgrading from older versions with changed entity IDs:

1. Go to **Settings → Devices & Services**
2. Find **Ampæra** and click **Configure**
3. Select **Regenerate Dashboard**
4. Confirm to delete and recreate the dashboard with correct entity IDs

### Commands not working

- Verify the device supports the command type
- Check that the entity is online and available
- EV chargers must be connected to a vehicle for charge commands

---

## Version History

### v1.5.3 (Latest)
- **Regenerate Dashboard Button** - Fix broken dashboards via Settings → Configure
- Improved upgrade path for existing users with "Entity not found" errors

### v1.5.0
- **Embedded Simulation Module** - No separate `ampaera_sim` integration needed
- Simulated devices created automatically when selecting Simulation mode
- Dashboard appears immediately without requiring restart

### v1.4.0
- **Simulation Dashboard Template** - Dedicated dashboard for simulation mode
- Norwegian language dashboard labels

### v1.3.0
- **Icon Translations** - HA 2024.2+ compliant state-based icons
- Improved household simulation (internal aggregation)

### v1.2.0
- **OAuth2 Authentication** - Sign in with your Ampæra account (recommended)
- **Auto-Dashboard** - Lovelace dashboard created automatically after setup

### v1.1.0
- Simulation mode for demos and testing
- Multi-site support
- Installation mode selection (Real Devices vs Simulation)

### v1.0.0
- Initial release
- Real-time telemetry push
- Device discovery and control
- Norwegian grid region support

See [CHANGELOG.md](CHANGELOG.md) for full version history.

---

## Support

- [Report issues](https://github.com/morteng/amp/issues?q=label%3Ahomeassistant)
- [Ampæra documentation](https://docs.ampaera.no)
- [Ampæra web app](https://xn--ampra-ura.no)

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

---

*This integration is developed by the Ampæra team and is not affiliated with Home Assistant or Nabu Casa.*
