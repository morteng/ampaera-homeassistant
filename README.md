# Ampæra Energy - Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/morteng/ampaera-homeassistant.svg)](https://github.com/morteng/ampaera-homeassistant/releases)
[![License](https://img.shields.io/github/license/morteng/ampaera-homeassistant.svg)](LICENSE)

Home Assistant custom integration for the **Ampæra Smart Home Energy Management Platform**.

## Features

- **Real-time power monitoring** from Norwegian AMS smart meters
- **Energy tracking** compatible with Home Assistant Energy Dashboard
- **Device control** for water heaters and EV chargers
- **Nord Pool spot prices** with cost calculations
- **Multi-site support** for homes with multiple properties (hytte)
- **Norwegian translations** (Bokmål)
- **Simulation mode** for demos and testing without real hardware

## Requirements

- Home Assistant 2024.1.0 or newer
- Ampæra account with active subscription
- API key from Ampæra web app

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

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click "Integrations"
3. Click the "+" button
4. Search for "Ampæra Energy"
5. Click "Download"
6. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/morteng/ampaera-homeassistant/releases)
2. Extract and copy `custom_components/ampaera` to your `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Step 1: Generate API Key

1. Log in to the [Ampæra web app](https://app.ampaera.no)
2. Go to **Settings → API**
3. Click **Generate Token**
4. Copy the API key (you'll only see it once)

### Step 2: Add Integration

1. Go to **Settings → Devices & Services**
2. Click **Add Integration**
3. Search for "Ampæra"
4. Enter your API key

### Step 3: Choose Installation Mode

After entering your API key, you'll choose between two modes:

#### Real Devices Mode
For production use with physical hardware:
- Discovers and connects to your actual smart devices
- Synchronizes device data with Ampæra cloud
- Enables remote control from Ampæra dashboard

#### Simulation Mode
For demos and testing:
- Creates simulated devices without real hardware
- Generates realistic telemetry patterns
- No physical device configuration needed
- Entry shows "(Simulation)" in title to distinguish

**Note**: Modes are mutually exclusive. You cannot mix simulated and real devices in the same installation.

### Step 4: Configure Location

Select your site name and Norwegian grid region (NO1-NO5) for accurate pricing.

### Step 5: Select Devices (Real Devices Mode only)

Choose which discovered devices to connect to Ampæra.

### Step 6: Configure Energy Dashboard (Optional)

1. Go to **Settings → Dashboards → Energy**
2. Click **Add consumption** under Electricity Grid
3. Select "Ampæra {site} Total Energy"

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

## Troubleshooting

### Cannot connect to Ampæra

- Verify your API key is correct
- Check your internet connection
- Ensure Ampæra services are online at [status.ampaera.no](https://status.ampaera.no)

### Entities show "unavailable"

- The integration may be temporarily disconnected
- Check Settings → Devices & Services → Ampæra for status
- Try reloading the integration

### Devices not discovered

- Ensure your device integration is properly configured in Home Assistant
- Check that the device has the correct device class (energy, power, etc.)
- Try adding the device manually if automatic discovery fails

### Commands not working

- Verify the device supports the command type
- Check that the entity is online and available
- EV chargers must be connected to a vehicle for charge commands

### Version checking

The integration version is displayed in:
- **Settings → Devices & Services → Ampæra → Configure**
- **Developer Tools → Downloads → Integrations → ampaera**

## Support

- [Report issues](https://github.com/morteng/amp/issues?q=label%3Ahomeassistant)
- [Ampæra documentation](https://docs.ampaera.no)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

---

*This integration is developed by the Ampæra team and is not affiliated with Home Assistant or Nabu Casa.*
