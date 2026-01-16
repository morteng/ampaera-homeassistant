# Changelog

All notable changes to the Ampæra Home Assistant integration.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
