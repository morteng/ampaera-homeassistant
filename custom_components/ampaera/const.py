"""Constants for the Ampæra Energy integration."""

from typing import Final

DOMAIN: Final = "ampaera"

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
