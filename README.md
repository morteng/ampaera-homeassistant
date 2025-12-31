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

## Requirements

- Home Assistant 2024.1.0 or newer
- Ampæra account with active subscription
- API key from Ampæra web app

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
5. Select which sites to add

### Step 3: Configure Energy Dashboard (Optional)

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

| Entity | Description |
|--------|-------------|
| Water heater | Temperature and mode control |
| Device switch | On/off control |

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

## Troubleshooting

### Cannot connect to Ampæra

- Verify your API key is correct
- Check your internet connection
- Ensure Ampæra services are online

### Entities show "unavailable"

- The integration may be temporarily disconnected
- Check Settings → Devices & Services → Ampæra for status
- Try reloading the integration

### Missing entities

- Not all device types are supported in MVP
- EV charger support coming in v0.2.0

## Support

- [Report issues](https://github.com/morteng/amp/issues?q=label%3Ahomeassistant)
- [Ampæra documentation](https://docs.ampaera.no)

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

---

*This integration is developed by the Ampæra team and is not affiliated with Home Assistant or Nabu Casa.*



