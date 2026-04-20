"""Device type signatures for the Ampæra discovery pipeline.

Consolidates all integration-name, semantic-signal, and keyword data
used to classify Home Assistant devices into Ampæra device types.
"""

from __future__ import annotations

from .models import AmperaDeviceType

# =============================================================================
# Known Integration Mapping
# =============================================================================
# Maps HA integration platform names to their Ampæra device type.
# Checked via entity.platform attribute during the classification stage.

KNOWN_INTEGRATIONS: dict[str, AmperaDeviceType] = {
    # --- EV Chargers ---
    # Norwegian market leaders
    "easee": AmperaDeviceType.EV_CHARGER,
    "zaptec": AmperaDeviceType.EV_CHARGER,
    "garo": AmperaDeviceType.EV_CHARGER,
    # Scandinavian/Nordic brands
    "elko": AmperaDeviceType.EV_CHARGER,
    "ctek": AmperaDeviceType.EV_CHARGER,
    "charge_amps": AmperaDeviceType.EV_CHARGER,
    # European/International
    "wallbox": AmperaDeviceType.EV_CHARGER,
    "ocpp": AmperaDeviceType.EV_CHARGER,
    "tesla_wall_connector": AmperaDeviceType.EV_CHARGER,
    "ohme": AmperaDeviceType.EV_CHARGER,
    "myenergi": AmperaDeviceType.EV_CHARGER,
    "hypervolt": AmperaDeviceType.EV_CHARGER,
    "go_echarger": AmperaDeviceType.EV_CHARGER,
    "evbox": AmperaDeviceType.EV_CHARGER,
    "alfen": AmperaDeviceType.EV_CHARGER,
    "abb": AmperaDeviceType.EV_CHARGER,
    "schneider_evlink": AmperaDeviceType.EV_CHARGER,
    "enelion": AmperaDeviceType.EV_CHARGER,
    "keba": AmperaDeviceType.EV_CHARGER,
    "mennekes": AmperaDeviceType.EV_CHARGER,
    # --- Water Heaters ---
    # Norwegian market leaders
    "hoiax": AmperaDeviceType.WATER_HEATER,
    "oso": AmperaDeviceType.WATER_HEATER,
    "ouman": AmperaDeviceType.WATER_HEATER,
    "mill": AmperaDeviceType.WATER_HEATER,
    "adax": AmperaDeviceType.WATER_HEATER,
    "nobo": AmperaDeviceType.WATER_HEATER,
    "glen_dimplex": AmperaDeviceType.WATER_HEATER,
    "sensibo": AmperaDeviceType.WATER_HEATER,
    # Generic/International
    "generic_thermostat": AmperaDeviceType.WATER_HEATER,
    "aquanta": AmperaDeviceType.WATER_HEATER,
    "rheem": AmperaDeviceType.WATER_HEATER,
    "ao_smith": AmperaDeviceType.WATER_HEATER,
    "bosch_shc": AmperaDeviceType.WATER_HEATER,
    "netatmo": AmperaDeviceType.WATER_HEATER,
    "tado": AmperaDeviceType.WATER_HEATER,
    # --- Power Meters ---
    # Norwegian AMS/HAN integrations
    "tibber": AmperaDeviceType.POWER_METER,
    "elvia": AmperaDeviceType.POWER_METER,
    "amshan": AmperaDeviceType.POWER_METER,
    "futurehome": AmperaDeviceType.POWER_METER,
    "heatit": AmperaDeviceType.POWER_METER,
    # Nordic/European P1 meters
    "p1_monitor": AmperaDeviceType.POWER_METER,
    "homewizard": AmperaDeviceType.POWER_METER,
    "dsmr": AmperaDeviceType.POWER_METER,
    "ams_reader": AmperaDeviceType.POWER_METER,
    # International smart plugs with power monitoring
    "shelly": AmperaDeviceType.POWER_METER,
    "tasmota": AmperaDeviceType.POWER_METER,
    "tuya": AmperaDeviceType.POWER_METER,
    "sonoff": AmperaDeviceType.POWER_METER,
    "athom": AmperaDeviceType.POWER_METER,
    "nous": AmperaDeviceType.POWER_METER,
    # Energy monitoring systems
    "iotawatt": AmperaDeviceType.POWER_METER,
    "emporia_vue": AmperaDeviceType.POWER_METER,
    "sense": AmperaDeviceType.POWER_METER,
}

# =============================================================================
# Semantic Signal Detection
# =============================================================================
# Entity name patterns that indicate specific device types.
# Checked when integration detection fails.

SEMANTIC_SIGNALS: dict[AmperaDeviceType, set[str]] = {
    AmperaDeviceType.WATER_HEATER: {
        # High confidence (unique to water heaters)
        "tank_temperature",
        "water_temperature",
        "hot_water",
        "legionella",
        "away_mode_temperature",
        "boost_mode",
        "heating_state",
        # Medium confidence
        "varmtvann",
        "bereder",
        "boiler",
        "water_heater",
    },
    AmperaDeviceType.POWER_METER: {
        # AMSHAN OBIS fields (high confidence)
        "active_power_import",
        "active_power_import_l1",
        "active_power_import_l2",
        "active_power_import_l3",
        "active_power_export",
        "reactive_power_import",
        "reactive_power_export",
        "voltage_l1",
        "voltage_l2",
        "voltage_l3",
        "current_l1",
        "current_l2",
        "current_l3",
        "power_factor",
        "power_factor_l1",
        "power_factor_l2",
        "power_factor_l3",
        "active_power_import_total",
        "meter_id",
        "meter_manufacturer",
        "obis",
        # Hourly/daily/monthly energy registers (English + Norwegian)
        "hour_used",
        "day_used",
        "month_used",
        "hourly_energy",
        "daily_energy",
        "monthly_energy",
        "today",
        "this_hour",
        "this_day",
        "this_month",
        "daily",
        "daglig",
        "i_dag",
        # Peak demand registers
        "current_month_peak",
        "month_peak",
        "peak_1",
        "peak_2",
        "peak_3",
        "topp_1",
        "topp_2",
        "topp_3",
        # Cost registers
        "day_cost",
        "dagens_kostnad",
        "dagskostnad",
        "today_cost",
        # Norwegian keywords (medium confidence)
        "ams",
        "han",
        "strømmåler",
        "power_consumption",
    },
    AmperaDeviceType.EV_CHARGER: {
        # Easee/Zaptec entities (high confidence)
        "status",
        "session_energy",
        "total_energy",
        "power",
        "cable_connected",
        "cable_locked",
        "ev_connected",
        "available_current_l1",
        "available_current_l2",
        "available_current_l3",
        "actual_current_l1",
        "actual_current_l2",
        "actual_current_l3",
        "charge_mode",
        "pilot_level",
        "operating_mode",
        "max_charging_current",
        "dynamic_charger_limit",
        # Generic EV charger signals (medium confidence)
        "charging_power",
        "charging_current",
        "charging_status",
        "charger_status",
        # Norwegian keywords
        "charger",
        "lader",
        "elbil",
        "ev_",
    },
}

# =============================================================================
# Keyword Detection (Fallback)
# =============================================================================
# Used when both integration and signal detection fail.

KEYWORDS: dict[AmperaDeviceType, set[str]] = {
    AmperaDeviceType.EV_CHARGER: {
        # English
        "charger",
        "ev",
        "ev_charger",
        "electric vehicle",
        # Brand names
        "easee",
        "zaptec",
        "wallbox",
        "garo",
        "ctek",
        "charge_amps",
        # Norwegian
        "lader",
        "elbillader",
        "elbil",
        "ladestasjon",
    },
    AmperaDeviceType.POWER_METER: {
        # Technical terms
        "ams",
        "han",
        "meter",
        "power_meter",
        "energy_meter",
        # Norwegian
        "strømmåler",
        "strøm",
        "effekt",
        "forbruk",
        # Brand/protocol
        "tibber",
        "p1",
        "obis",
        "dsmr",
    },
    AmperaDeviceType.WATER_HEATER: {
        # English
        "water heater",
        "water_heater",
        "boiler",
        "hot water",
        "hot_water",
        # Norwegian
        "varmtvannsbereder",
        "bereder",
        "varmtvann",
        "varmt vann",
        # Brand names
        "hoiax",
        "høiax",
        "oso",
    },
}

# =============================================================================
# Filtering & Domain Constants
# =============================================================================

# Integrations to exclude from discovery
EXCLUDED_INTEGRATIONS: set[str] = set()

# Integrations whose devices/entities are never relevant to energy management.
# Used by DeviceClassifier to mark devices as is_energy_relevant=False so they
# are hidden from the default picker. Covers HA add-ons (hassio), our own
# integration (to avoid self-discovery loops), and common security/media
# integrations that surface as switches or sensors without energy signals.
NON_ENERGY_INTEGRATIONS: set[str] = {
    "hassio",  # HA add-ons: HACS, Samba, FTP, Mosquitto, File editor, Terminal & SSH, ...
    "hacs",  # HACS frontend switches
    "ampaera",  # our own entities — never re-discover them
    "eufy_security",
    "eufy_security_ws",
    "ring",
    "nest",
    "unifi_protect",
    "frigate",
    "reolink",
    "blink",
    "arlo",
}

# Device classes that indicate energy-related sensors
ENERGY_DEVICE_CLASSES: set[str] = {
    "power",
    "energy",
    "voltage",
    "current",
}

# Domains we're interested in
SUPPORTED_DOMAINS: set[str] = {
    "sensor",
    "water_heater",
    "switch",
    "climate",
}

# =============================================================================
# Non-Energy Device Filter
# =============================================================================
# Substring patterns (lowercase) that indicate a device/entity is NOT relevant
# to energy management. Used to mark devices as is_energy_relevant=False so
# they're hidden from the default selection list. Users can still opt in via
# the "show all devices" toggle.
#
# Detection is intentionally aggressive — false positives (a real water
# heater hidden) are recoverable via the toggle, while false negatives
# (Rolf's 180+ camera switches) drown the picker.

NON_ENERGY_KEYWORDS: set[str] = {
    # Camera-related
    "camera",
    "kamera",
    "nightvision",
    "rtsp",
    "antitheft",
    "motion detection",
    "motion_detection",
    "motion tracking",
    "motion_tracking",
    "pet detection",
    "pet_detection",
    "person detected",
    "person_detected",
    "crying detected",
    "sound detected",
    "indoor chime",
    "indoor_chime",
    "audio recording",
    "audio_recording",
    # Security / access
    "doorbell",
    "ringeklokke",
    "alarm",
    "siren",
    "lock",
    "unlock",
    # Media / IO
    "microphone",
    "speaker",
    "status led",
    "status_led",
    # Notifications
    "notification",
    "varsel",
}

# =============================================================================
# Label Translation
# =============================================================================
# Map cryptic AMS / OBIS / vendor codes to human-readable labels.
# Keys are uppercase suffixes found in entity friendly names, e.g. "MONTHUSE".
# Used by the config flow to render readable device names.

OBIS_LABEL_MAP: dict[str, str] = {
    "MONTHUSE": "Månedsforbruk",
    "DAYUSE": "Dagsforbruk",
    "HOURUSE": "Timesforbruk",
    "PEAKS0": "Topp 1 (denne måneden)",
    "PEAKS1": "Topp 2 (denne måneden)",
    "PEAKS2": "Topp 3 (denne måneden)",
    "THRESHOLD": "Effektgrense",
    "THRESHOLDS0": "Effektgrense trinn 1",
    "THRESHOLDS1": "Effektgrense trinn 2",
    "THRESHOLDS2": "Effektgrense trinn 3",
    "THRESHOLDS3": "Effektgrense trinn 4",
    "ACCUMULATED": "Akkumulert forbruk (time)",
    "ESTIMATED": "Estimert forbruk (time)",
    "PHASE1": "Spenning fase 1",
    "PHASE2": "Spenning fase 2",
    "PHASE3": "Spenning fase 3",
}
