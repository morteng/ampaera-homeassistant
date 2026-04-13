# Changelog

All notable changes to the Ampæra Home Assistant integration.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.2] - 2026-04-13

### Changed
- **Wider grouping regex**: The discovery picker now also collapses multi-channel meters that use unparen channel suffixes — `em16 A1`, `em16_phase_2`, `em16-CH3`, `em16 1`, `em16-2` and similar variants now cluster with their parenthetical siblings into a single group. Previously the regex only handled `em16 (A1)` style, which meant real-world HA installs with hybrid naming kept devices scattered across the picker.

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.34.0+

## [2.2.1] - 2026-04-13

### Fixed
- **Form crash on upgrade from v2.1.0**: Users with a cherry-picked selection of individual em16 channels saved before grouping existed saw `value must be one of [...]` voluptuous errors when reopening *Manage Devices*. The picker no longer exposes the individual member device IDs (they're behind the group), so the stored defaults failed validation. `collapse_to_group_ids` now promotes any partial-member match to the full group ID, and the renderer additionally filters defaults against the live option list as a safety net for genuinely-removed devices.
- **Onboarding count framing**: The "9 of 88 devices shown" line was technically correct (9 picker rows out of 88 raw devices) but read as if 79 devices had been silently dropped. Both *Select Devices* and *Manage Devices* now render the breakdown as `88 devices in HA → 62 energy-relevant shown as 9 picker rows (1 grouped meter rolling up 54 channels) + 26 hidden as non-energy`, with explicit ✓/✗ markers and the math spelled out.

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.34.0+

## [2.2.0] - 2026-04-13

### Added
- **Device Grouping**: Multi-channel meters like Shelly em16 (with 18 circuits) are now collapsed into a single grouped option in the picker. Selecting the group enables every channel at once. Triggers automatically when 3+ devices share base name + type + manufacturer + model.
- **Integration Denylist**: Devices from `hassio` (HA add-ons such as HACS, Samba, Mosquitto, File editor, FTP, Terminal & SSH), `eufy_security`, `ring`, `nest`, `unifi_protect`, `frigate`, `reolink`, `blink`, `arlo` and our own `ampaera` integration are now excluded at discovery time. Beta users with ~70 devices typically saw 10+ irrelevant rows from add-ons; these no longer appear.
- **Onboarding Step Copy Refresh**: The *Select Devices*, *Manage Devices* and *Configure Site* steps now show richer descriptions with explicit counts ("Found 72 devices, showing 12 — 10 hidden as non-energy, 2 groups collapse 36 similar devices"), Nord Pool grid region guidance (NO1–NO5), and `data_description` helpers explaining what *(grouped)* labels mean and what *Show all devices* reveals.

### Changed
- The picker now displays grouped meters first within each device type, followed by individual devices. Toggling *Show all devices* in *Manage Devices* disables grouping so advanced users can cherry-pick individual channels.
- Picker option labels for groups read `<base name> – <type>, <count> enheter (gruppert)` (e.g. `em16 – strømmåler, 18 enheter (gruppert)`).

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.34.0+

## [2.1.0] - 2026-04-13

### Added
- **Energy-Relevance Filter**: Devices that are clearly not energy-related (cameras, microphones, motion detection, audio recording, notification toggles, doorbells) are now hidden from the device picker by default. Users with many smart-home devices (e.g. 261 devices, ~70% of which were camera switches) get a focused list.
- **Smart Defaults**: Power meters (AMS, Tibber Pulse, Shelly, EM-style), EV chargers and water heaters are now pre-selected by default in the device picker. Generic sensors and switches remain visible but unselected so users opt in deliberately.
- **Device Grouping**: The picker now sorts devices by category (power meters first, then EV chargers, water heaters, climate, sensors, switches) instead of a flat alphabetical list.
- **AMS/OBIS Label Translation**: Cryptic codes like `MONTHUSE`, `PEAKS0-2`, `THRESHOLD`, `ACCUMULATED`, `PHASE1-3` are now translated to readable Norwegian labels (`Månedsforbruk`, `Topp 1 (denne måneden)`, `Effektgrense`, `Akkumulert forbruk (time)`, `Spenning fase 1`).
- **Channel Suffix Stripping**: Redundant `(CH_1)`, `(CH_2)` channel codes are removed from device labels in the picker — they were noise from the channel splitter.
- **"Show all devices" Toggle**: New checkbox in *Manage Devices* options flow lets advanced users opt into the unfiltered list when they need to control non-energy devices via Ampæra.

### Changed
- The initial device selection step now shows a focused, energy-only list with smart pre-selection. The full list is available later via *Manage Devices*.

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

## [2.0.0] - 2026-04-11

### Changed
- **Discovery Pipeline v2.0**: Replaced monolithic `device_discovery.py` with modular `discovery/` package comprising four stages: entity scanning, capability analysis, device classification, and channel splitting.
- **DiscoveryOrchestrator**: New orchestrator runs the full pipeline with timing diagnostics and structured `DiscoveryReport`.
- **HA Repairs Integration**: Discovery issues (auto-enabled entities, unmapped entities) now surface as HA Repair issues with Norwegian and English translations.
- **Diagnostics**: Discovery report data included in HA diagnostics export for troubleshooting.

### Deprecated
- `device_discovery.py` is deprecated. Use `from .discovery import DiscoveryOrchestrator` instead.

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

## [1.9.1] - 2026-04-11

### Fixed
- **Entity Discovery**: Use HA entity registry instead of `hass.states` for discovery, finding ALL entities including those disabled by their source integration (e.g., Refoss EM16 entities disabled by default). Previously only ~1/3 of entities were visible.
- **Channel Split False Positives**: Channel splitting now requires at least 2 duplicate capabilities AND clear channel naming patterns (a1/b1, 1/2, ch1/ch2). Prevents false splits on devices with accidentally duplicate capabilities.
- **Synthetic Device ID Lookup**: `_get_device_info` now resolves synthetic channel IDs (`device_id__ch_a1`) to the real device ID before HA registry lookup, fixing missing device name/manufacturer/model for channel-split devices.
- **Auto-Enable Disabled Entities**: Automatically enables entities that were disabled by their source integration (not by user choice) when they belong to synced Ampæra devices. Shows a persistent notification when entities are enabled. Requires one-time integration reload.

## [1.9.0] - 2026-03-30

### Added
- **Multi-Channel Device Support**: Devices with multiple channels (Refoss EM16, Shelly 3EM, multi-endpoint Zigbee) now produce one Ampæra device per channel instead of flattening to a single device
  - Channel IDs auto-detected from entity naming patterns (e.g., A1/B1, channel_1/channel_2)
  - All channels created, including those reading zero (no CT clamp)
  - Shared entities (e.g., device-wide temperature) distributed to all channels
  - Sync filter updated to match channel-split device IDs via parent prefix
- **Channel ID Extraction**: New `_extract_channel_ids` static method using segment-based comparison for robust channel detection across device types

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

## [1.8.0] - 2026-03-15

### Added
- **Data Lab Sensor Streams**: Push arbitrary HA sensor entities to Ampæra cloud for Data Lab visualization
  - New "Sensor Streams" options flow step: select any numeric HA sensor to forward
  - Configurable push interval (30–3600 seconds, default 60s)
  - MQTT publish to `telemetry/{site_id}/sensor-streams` topic
  - Enables multi-signal comparison charts in Data Lab (power + temperature + current etc.)
- **Entity Browser**: New options flow step to browse and map HA entities with usage categories

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

## [1.7.0] - 2026-03-10

### Added
- **Entity Browser Options Flow**: Browse all HA entities with usage category mapping
  - Categorize entities by usage type (power meter, temperature, EV charger, etc.)
  - Entity mappings stored in integration options for device sync

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

## [1.6.3] - 2026-03-02

### Fixed
- **Real-mode dashboard shows "Entity not found"**: Dashboard template referenced non-existent `sensor.{site_name}_*` entities. Real mode now builds dashboard dynamically from actual synced HA entities (Tibber, AMS, etc.)
- **Regenerate Dashboard uses actual entities**: The "Regenerate Dashboard" option now passes entity mappings from the running device sync service

## [1.6.2] - 2026-03-02

### Fixed
- **Reauth token field mismatch**: Options flow reauth now writes the new API key to the correct config field (oauth_token vs api_key) based on the original auth method
- **Reauth not reloading integration**: Options flow reauth now triggers an integration reload so the running API client picks up the new token immediately
- **Config flow reauth missing API URL**: Config flow reauth now uses the stored API URL from the config entry instead of hardcoding the default URL
- **Token fallback in setup**: Integration setup now checks both token fields (api_key and oauth_token) as a safety net, regardless of auth method
- **Better reauth diagnostics**: Added detailed logging to both config flow and options flow reauth paths for easier troubleshooting

### Changed
- Updated reauth UI descriptions (English and Norwegian) to guide users to Settings → API Tokens

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

## [1.6.0] - 2026-02-16

### Added
- **AMS Meter Register Support**: Auto-detect and forward hour/day/month energy registers from Norwegian AMS meters
  - New capabilities: `ENERGY_HOUR`, `ENERGY_DAY`, `ENERGY_MONTH`
  - Auto-detects AMS entities with "hour_used", "day_used", "month_used" patterns
  - Maps to `hour_energy_kwh`, `day_energy_kwh`, `month_energy_kwh` in MQTT payload
  - Enables cloud dashboard to show authoritative meter consumption instead of estimated aggregations
- **Simulation Register Sensors**: New simulated sensor entities for hour/day/month energy registers
  - `PowerMeterHourEnergySensor`, `PowerMeterDayEnergySensor`, `PowerMeterMonthEnergySensor`
  - Realistic period boundary resets (hourly, daily, monthly)

### Compatibility
- Home Assistant: 2024.1.0+
- Ampæra API: v0.33.0+

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
