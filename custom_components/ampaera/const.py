"""Constants for the Ampæra Energy integration."""

import json
from pathlib import Path
from typing import Final

DOMAIN: Final = "ampaera"


def _get_integration_version() -> str:
    """Read version from VERSION file or manifest.json fallback.

    VERSION file is the source of truth for releases.
    manifest.json uses 0.0.0 placeholder that gets replaced during publish.
    """
    try:
        # Try VERSION file first (in integrations/homeassistant/)
        version_path = Path(__file__).parent.parent.parent.parent / "VERSION"
        if version_path.exists():
            return version_path.read_text().strip()

        # Fall back to manifest.json (for installed copies via HACS)
        manifest_path = Path(__file__).parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        version = manifest.get("version", "unknown")
        # Don't return placeholder
        if version == "0.0.0":
            return "dev"
        return version
    except Exception:
        return "unknown"


INTEGRATION_VERSION: Final = _get_integration_version()

# Configuration - Authentication
CONF_API_KEY: Final = "api_key"

# Configuration - Site (v2.0 push architecture)
CONF_SITE_ID: Final = "site_id"
CONF_SITE_NAME: Final = "site_name"
CONF_HA_INSTANCE_ID: Final = "ha_instance_id"
CONF_GRID_REGION: Final = "grid_region"

# Configuration - Devices (v2.0 push architecture)
CONF_DEVICE_MAPPINGS: Final = "device_mappings"
CONF_SELECTED_ENTITIES: Final = "selected_entities"

# Configuration - Options
CONF_POLLING_INTERVAL: Final = "polling_interval"
CONF_COMMAND_POLL_INTERVAL: Final = "command_poll_interval"
CONF_DEVICE_SYNC_INTERVAL: Final = "device_sync_interval"
CONF_ENABLE_VOLTAGE_SENSORS: Final = "enable_voltage_sensors"
CONF_DEV_MODE: Final = "dev_mode"

# Configuration - Installation Mode
CONF_INSTALLATION_MODE: Final = "installation_mode"

# Installation modes - mutually exclusive
INSTALLATION_MODE_REAL: Final = "real"  # Real physical devices only
INSTALLATION_MODE_SIMULATION: Final = "simulation"  # Simulated devices for demos/testing

# Installation mode choices for config flow
INSTALLATION_MODES: Final = [
    (INSTALLATION_MODE_REAL, "Real Devices"),
    (INSTALLATION_MODE_SIMULATION, "Simulation (Demo/Testing)"),
]

# Configuration - Simulation
CONF_ENABLE_SIMULATION: Final = "enable_simulation"
CONF_SIMULATION_HOUSEHOLD_PROFILE: Final = "simulation_household_profile"
CONF_SIMULATION_WATER_HEATER_TYPE: Final = "simulation_water_heater_type"

# Simulation household profiles
SIMULATION_PROFILES: Final = [
    ("family", "Family (2 adults, 2 kids)"),
    ("couple", "Couple (2 adults)"),
    ("single", "Single"),
    ("retiree", "Retiree"),
    ("student", "Student"),
]

# Simulation water heater types
SIMULATION_WH_TYPES: Final = [
    ("old", "Old (On/Off only, no temp sensor)"),
    ("standard", "Standard (Basic thermostat)"),
    ("smart", "Smart (Full temperature control)"),
]

# Legacy configuration (kept for migration)
CONF_SITE_IDS: Final = "site_ids"
CONF_ENABLE_SSE: Final = "enable_sse"

# Configuration - API URL (for development override)
CONF_API_URL: Final = "api_url"

# Defaults
DEFAULT_POLLING_INTERVAL: Final = 30  # seconds (telemetry push debounce)
DEFAULT_COMMAND_POLL_INTERVAL: Final = 10  # seconds (command polling)
DEFAULT_DEVICE_SYNC_INTERVAL: Final = 300  # seconds (device sync - 5 minutes)
# Production API URL (use CONF_API_URL to override for development)
DEFAULT_API_BASE_URL: Final = "https://ampæra.no"

# Grid regions (Norwegian price zones)
GRID_REGIONS: Final = [
    ("NO1", "Oslo (Øst-Norge)"),
    ("NO2", "Kristiansand (Sør-Norge)"),
    ("NO3", "Trondheim (Midt-Norge)"),
    ("NO4", "Tromsø (Nord-Norge)"),
    ("NO5", "Bergen (Vest-Norge)"),
]

# Device types
DEVICE_TYPE_WATER_HEATER: Final = "water_heater"
DEVICE_TYPE_EV_CHARGER: Final = "ev_charger"
DEVICE_TYPE_POWER_METER: Final = "power_meter"
DEVICE_TYPE_SWITCH: Final = "switch"
DEVICE_TYPE_CLIMATE: Final = "climate"

# Attribution
ATTRIBUTION: Final = "Data provided by Ampæra"
