# Changelog

All notable changes to the Ampæra Home Assistant integration.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.3] - 2026-01-22

### Added
- **Regenerate Dashboard Button**: New option in integration settings to regenerate dashboard
  - Accessible via Settings → Devices & Services → Ampæra → Configure → "Regenerate Dashboard"
  - Deletes existing dashboard and recreates with correct entity IDs
  - Useful for users upgrading from older versions with broken dashboards
  - Fully translated in English and Norwegian

### Fixed
- **Upgrade Path for Existing Users**: Users with older versions can now fix "Entity not found" errors
  without removing and re-adding the integration

## [1.5.2] - 2026-01-22

### Fixed
- **Simulation Entity Registration**: Replaced EntityComponent approach with proper Home Assistant platform forwarding
  - Simulation entities now correctly register in the entity registry
  - Dashboard entities resolve properly instead of showing "Entitet ikke funnet"
  - Platform files (sensor.py, switch.py, number.py, select.py, water_heater.py) now act as simulation wrappers
  - Uses `async_forward_entry_setups()` for proper HA integration

### Changed
- **Water Heater Modes**: Standardized operation modes to "Normal", "Eco", "Boost", "Off"
- **Test Updates**: Updated test fixtures to properly mock coordinator's direct `water_heater` attribute

## [1.5.1] - 2026-01-22

### Fixed
- **Simulation Mode Activation**: Fixed bug where simulation entities weren't created when `installation_mode` was set to "simulation"
  - Now correctly checks both `installation_mode == "simulation"` AND `enable_simulation` toggle
  - Users selecting "Simulation" mode during setup will now have simulation entities created

## [1.5.0] - 2026-01-22

### Added
- **Embedded Simulation Module**: Simulation mode now works out of the box without a separate integration
  - When "Simulation" mode is selected during setup, all simulated devices are created automatically
  - Simulated AMS meter, water heater, and EV charger with physics-based behavior
  - No need to install ampaera_sim separately via HACS
- **Auto Lovelace Reload**: Dashboard now appears immediately without requiring HA restart
  - Fires lovelace_updated event after dashboard creation
  - Calls lovelace.reload_resources service for immediate UI update
  - Improved notification messages to guide users

### Fixed
- Dashboard entity type: EV charger status now correctly references `select.simulated_ev_charger_status`
- Simulation entities now register properly in Home Assistant

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.29.0+

## [1.4.0] - 2026-01-19

### Added
- **Simulation Dashboard Template**: New dedicated dashboard for simulation mode
  - Uses correct entity IDs (`sensor.simulated_ams_meter_*`, `sensor.simulated_water_heater_*`, etc.)
  - Automatically selected when installation mode is "Simulation"
  - Includes all simulation devices: AMS meter, water heater, EV charger

### Changed
- **Dashboard Localization**: Converted dashboards to Norwegian language
  - "Overview" → "Oversikt", "Energy" → "Energi", "Devices" → "Enheter"
  - All labels and titles now in Norwegian
- **Entity ID Generation**: Dashboard templates now use `{site_name_slug}` for proper HA entity ID matching
- **Improved Notifications**: Better user guidance for dashboard creation and restart requirements

### Fixed
- Simulation mode dashboard now correctly displays simulated device data
- Entity references match HA's slugified naming convention

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.29.0+

## [1.3.0] - 2026-01-17

### Added
- **Icon Translations (icons.json)**: Added HA 2024.2+ compliant icon definitions
  - State-based icons for water heater modes (comfort, eco, boost, off)
  - State-based icons for binary sensors (connected, charging)
  - Service icons for force_sync, push_telemetry, send_command
  - Default icons for all sensor types (power, energy, cost, voltage, current)

### Changed
- **ampaera_sim**: Household simulation is now internal-only
  - Household power consumption is aggregated into AMS meter readings
  - No longer exposes separate "Simulated Household" device/entities
  - Provides more realistic simulation without cluttering device list

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.29.0+

## [1.2.0] - 2026-01-16

### Added
- **OAuth2 Authentication**: Support for OAuth2 authorization code flow with PKCE
  - Multi-instance OAuth with direct callbacks per entry
  - Pre-registered Home Assistant OAuth client (no manual credentials needed)
  - Secure token refresh handling
- **Auto-Dashboard**: Automatic dashboard creation for Ampæra devices on first setup
- **Open Source**: Released under MIT license for community contributions
- **ampaera_sim Enhancements**:
  - Presence-based household simulation patterns
  - Household status sensors for monitoring simulation state
  - Support for building_type and presence_mode configuration options

### Fixed
- OAuth flow tests and pre-registered HA client configuration
- ampaera_sim config flow tests for better validation
- Import sorting and lint issues

### Changed
- Lint fixes for ruff compliance (contextlib.suppress, unused arguments)

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.28.0+

## [1.1.0] - 2026-01-06

### Added
- **Installation Mode Selection**: Users now choose between "Real Devices" and "Simulation" modes during setup
  - Real Device Mode: For production use with physical hardware
  - Simulation Mode: For demos and testing with simulated devices
  - Modes are mutually exclusive to prevent mixing simulated and real devices
- **Enhanced Device Discovery**: Expanded support for Norwegian and European smart devices
  - EV Chargers: Added ELKO, CTEK, ABB Terra, Schneider EVlink, KEBA, MENNEKES (24 total integrations)
  - Water Heaters: Added Høiax, OSO, Adax, Nobø, Glen Dimplex, Tado, Netatmo (14 total integrations)
  - Power Meters: Added Futurehome, Heatit, HomeWizard, IoTaWatt, Emporia Vue (18 total integrations)
- **Norwegian Language Keywords**: Improved detection using Norwegian terms ("elbillader", "varmtvannsbereder", "strømmåler")
- **EV Charger Commands**: Full support for start_charge, stop_charge, set_current_limit commands
- **Entity Resolution**: Smart mapping of commands to correct entity types (sensors → switches/input_numbers)

### Changed
- Config flow now routes to mode-specific steps (simulation skips device discovery)
- Options flow shows mode-specific settings only
- Entry title includes "(Simulation)" suffix for simulation mode installations

### Fixed
- Command routing: Commands now correctly target switch/input_number entities instead of sensors
- Backward compatibility: ConfigFlowResult import works with HA 2024.3.3+
- Entity mapping callback: Device sync service properly notifies command service of mapping updates

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.21.0+

## [1.0.0] - 2026-01-01

### Added
- Push architecture: HA pushes telemetry to Ampæra cloud
- Device discovery: Automatic detection of compatible HA devices
- Device sync: Keeps HA devices synchronized with Ampæra
- Command polling: Remote control from Ampæra dashboard
- Diagnostics: Debug info via Developer Tools
- Services: `ampaera.force_sync` and `ampaera.push_telemetry`
- Multi-region support: NO1-NO5 Norwegian grid regions
- Translations: English and Norwegian (Bokmål)
- Entity mapping: Groups sensors under parent devices

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.21.0+

## [Previous versions]

Prior to v1.0.0, the integration used version numbers matching the amp repo.
See [amp releases](https://github.com/morteng/amp/releases) for historical changes.
