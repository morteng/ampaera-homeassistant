"""Device discovery service for Ampæra HA integration.

Discovers Home Assistant devices suitable for syncing to Ampæra:
- Power/energy sensors (AMS meters, smart plugs)
- Water heaters
- Switches (smart relays)
- Climate devices (HVAC)

Groups multiple HA entities by their parent device_id to create
one logical Ampæra device per physical device.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

_LOGGER = logging.getLogger(__name__)


class AmperaDeviceType(str, Enum):
    """Device types supported by Ampæra."""

    POWER_METER = "power_meter"
    WATER_HEATER = "water_heater"
    EV_CHARGER = "ev_charger"
    SWITCH = "switch"
    CLIMATE = "climate"
    SENSOR = "sensor"


class AmperaCapability(str, Enum):
    """Capabilities a device can have."""

    POWER = "power"  # Total power (preferred for primary entity)
    POWER_L1 = "power_l1"  # Phase-specific power
    POWER_L2 = "power_l2"
    POWER_L3 = "power_l3"
    ENERGY = "energy"
    ENERGY_IMPORT = "energy_import"
    ENERGY_EXPORT = "energy_export"
    VOLTAGE_L1 = "voltage_l1"
    VOLTAGE_L2 = "voltage_l2"
    VOLTAGE_L3 = "voltage_l3"
    CURRENT_L1 = "current_l1"
    CURRENT_L2 = "current_l2"
    CURRENT_L3 = "current_l3"
    VOLTAGE = "voltage"
    CURRENT = "current"
    TEMPERATURE = "temperature"
    TARGET_TEMPERATURE = "target_temperature"
    ON_OFF = "on_off"
    HUMIDITY = "humidity"
    CHARGE_LIMIT = "charge_limit"
    SESSION_ENERGY = "session_energy"


@dataclass
class DiscoveredDevice:
    """A device discovered in Home Assistant.

    Represents a physical device (grouped by HA device_id) with
    multiple entities mapped to capabilities.
    """

    ha_device_id: str  # HA device registry ID (parent device)
    name: str
    device_type: AmperaDeviceType
    capabilities: list[AmperaCapability] = field(default_factory=list)
    entity_mapping: dict[str, str] = field(default_factory=dict)  # capability -> entity_id
    primary_entity_id: str = ""  # Main entity for backward compat
    manufacturer: str | None = None
    model: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API registration."""
        result = {
            "ha_device_id": self.ha_device_id,
            "ha_entity_id": self.primary_entity_id,  # Backward compat
            "device_type": self.device_type.value,
            "name": self.name,
            "capabilities": [c.value for c in self.capabilities],
            "entity_mapping": self.entity_mapping,
        }
        if self.manufacturer:
            result["manufacturer"] = self.manufacturer
        if self.model:
            result["model"] = self.model
        return result


# Device classes that indicate energy-related sensors
ENERGY_DEVICE_CLASSES = {
    "power",
    "energy",
    "voltage",
    "current",
}

# Domains we're interested in
SUPPORTED_DOMAINS = {
    "sensor",
    "water_heater",
    "switch",
    "climate",
}


# =============================================================================
# Norwegian Market Integration Detection
# =============================================================================
# Known HA integrations popular in Norway, mapped to device types.
# The integration platform name is checked against entity.platform attribute.

KNOWN_EV_CHARGER_INTEGRATIONS = {
    # Norwegian market leaders
    "easee": "Easee",           # Most popular in Norway
    "zaptec": "Zaptec",         # Strong in Norway
    "garo": "GARO",             # Swedish, popular in Nordics
    # European/International
    "wallbox": "Wallbox",
    "ocpp": "OCPP",             # Open Charge Point Protocol
    "tesla_wall_connector": "Tesla Wall Connector",
    "ohme": "Ohme",
    "myenergi": "myenergi zappi",
    "hypervolt": "Hypervolt",
    "go_echarger": "go-e Charger",
    "evbox": "EVBox",
    "charge_amps": "Charge Amps",
    "alfen": "Alfen",
}

KNOWN_WATER_HEATER_INTEGRATIONS = {
    # Norwegian market
    "ouman": "Ouman",           # Finnish, popular in Nordics
    "sensibo": "Sensibo",       # Can control water heaters
    "mill": "Mill",             # Norwegian brand
    # Generic
    "generic_thermostat": "Generic Thermostat",
    "aquanta": "Aquanta",
    "rheem": "Rheem",
    "ao_smith": "A.O. Smith",
}

KNOWN_POWER_METER_INTEGRATIONS = {
    # Norwegian AMS/HAN integrations
    "tibber": "Tibber",         # Tibber Pulse
    "elvia": "Elvia",           # Local utility
    "amshan": "AMS/HAN",        # Generic AMS reader
    "p1_monitor": "P1 Monitor",
    # International
    "shelly": "Shelly",
    "tasmota": "Tasmota",
    "tuya": "Tuya",
    "sonoff": "Sonoff",
}

# =============================================================================
# Semantic Signal Detection
# =============================================================================
# Entity name patterns that indicate specific device types, ordered by specificity.
# These are checked when integration detection fails.

WATER_HEATER_SIGNALS = {
    # High confidence (unique to water heaters)
    "tank_temperature", "water_temperature", "hot_water", "legionella",
    "away_mode_temperature", "boost_mode", "heating_state",
    # Medium confidence
    "varmtvann", "bereder", "boiler", "water_heater",
}

AMS_POWER_METER_SIGNALS = {
    # AMSHAN OBIS fields (high confidence)
    "active_power_import", "active_power_import_l1", "active_power_import_l2", "active_power_import_l3",
    "active_power_export",  # Will always be 0 for our simulation (no PV)
    "reactive_power_import", "reactive_power_export",
    "voltage_l1", "voltage_l2", "voltage_l3",
    "current_l1", "current_l2", "current_l3",
    "power_factor", "power_factor_l1", "power_factor_l2", "power_factor_l3",
    "active_power_import_total",  # Cumulative Wh counter
    "meter_id", "meter_manufacturer",
    "obis",  # OBIS code reference
    # Norwegian keywords (medium confidence)
    "ams", "han", "strømmåler", "power_consumption",
}

EV_CHARGER_SIGNALS = {
    # Easee/Zaptec entities (high confidence)
    "status", "session_energy", "total_energy", "power",
    "cable_connected", "cable_locked", "ev_connected",
    "available_current_l1", "available_current_l2", "available_current_l3",
    "actual_current_l1", "actual_current_l2", "actual_current_l3",
    "charge_mode", "pilot_level", "operating_mode",
    "max_charging_current", "dynamic_charger_limit",
    # Generic EV charger signals (medium confidence)
    "charging_power", "charging_current", "charging_status", "charger_status",
    # Norwegian keywords
    "charger", "lader", "elbil", "ev_",
}

# =============================================================================
# Keywords (fallback detection)
# =============================================================================
# Used when both integration and signal detection fail.

EV_CHARGER_KEYWORDS = {"charger", "ev", "easee", "zaptec", "wallbox", "lader", "elbil"}
AMS_KEYWORDS = {"ams", "han", "meter", "strømmåler", "power consumption"}
WATER_HEATER_KEYWORDS = {"water heater", "varmtvannsbereder", "boiler", "hot water"}


class AmperaDeviceDiscovery:
    """Discover HA devices suitable for Ampæra sync.

    Groups multiple HA entities by their parent device_id to create
    one logical Ampæra device per physical device.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize device discovery."""
        self._hass = hass
        self._entity_registry: er.EntityRegistry | None = None
        self._device_registry: dr.DeviceRegistry | None = None

    def _ensure_registries(self) -> None:
        """Lazy load registries."""
        if self._entity_registry is None:
            self._entity_registry = er.async_get(self._hass)
        if self._device_registry is None:
            self._device_registry = dr.async_get(self._hass)

    def _get_parent_device_id(self, entity_id: str) -> str | None:
        """Get the parent device_id for an entity.

        Returns the HA device registry ID, or None if entity has no parent device.
        """
        self._ensure_registries()
        assert self._entity_registry is not None

        entity_entry = self._entity_registry.async_get(entity_id)
        if entity_entry is None:
            return None

        return entity_entry.device_id

    def _get_device_info(self, device_id: str) -> tuple[str | None, str | None, str | None]:
        """Get device info from device registry.

        Returns tuple of (name, manufacturer, model), any may be None.
        """
        self._ensure_registries()
        assert self._device_registry is not None

        device_entry = self._device_registry.async_get(device_id)
        if device_entry is None:
            return None, None, None

        # Use name_by_user if set, otherwise name
        name = device_entry.name_by_user or device_entry.name
        return name, device_entry.manufacturer, device_entry.model

    def _get_entity_platform(self, entity_id: str) -> str | None:
        """Get the integration platform name for an entity.

        This is the integration that created the entity (e.g., 'easee', 'zaptec', 'tibber').
        Used for known-integration detection.
        """
        self._ensure_registries()
        assert self._entity_registry is not None

        entity_entry = self._entity_registry.async_get(entity_id)
        if entity_entry is None:
            return None

        return entity_entry.platform

    def _detect_device_type_from_integration(
        self, entities: list[State]
    ) -> AmperaDeviceType | None:
        """Detect device type from known integration platforms.

        This is the most reliable detection method - if an entity comes from
        a known integration (e.g., 'easee', 'zaptec'), we can confidently
        classify the device.

        Returns:
            Device type if detected from known integration, None otherwise.
        """
        for state in entities:
            platform = self._get_entity_platform(state.entity_id)
            if not platform:
                continue

            platform_lower = platform.lower()

            # Check EV charger integrations
            if platform_lower in KNOWN_EV_CHARGER_INTEGRATIONS:
                _LOGGER.debug(
                    "Detected EV charger from integration: %s (%s)",
                    platform,
                    KNOWN_EV_CHARGER_INTEGRATIONS[platform_lower],
                )
                return AmperaDeviceType.EV_CHARGER

            # Check water heater integrations
            if platform_lower in KNOWN_WATER_HEATER_INTEGRATIONS:
                _LOGGER.debug(
                    "Detected water heater from integration: %s (%s)",
                    platform,
                    KNOWN_WATER_HEATER_INTEGRATIONS[platform_lower],
                )
                return AmperaDeviceType.WATER_HEATER

            # Check power meter integrations
            if platform_lower in KNOWN_POWER_METER_INTEGRATIONS:
                _LOGGER.debug(
                    "Detected power meter from integration: %s (%s)",
                    platform,
                    KNOWN_POWER_METER_INTEGRATIONS[platform_lower],
                )
                return AmperaDeviceType.POWER_METER

        return None

    def _detect_device_type_from_signals(
        self, entities: list[State]
    ) -> AmperaDeviceType | None:
        """Detect device type from semantic entity name signals.

        Checks entity names and friendly names for patterns that indicate
        specific device types. More robust than simple keyword matching.

        Returns:
            Device type if detected from signals, None otherwise.
        """
        # Collect all searchable text from entities
        all_names: list[str] = []
        for state in entities:
            entity_id = state.entity_id
            entity_name = entity_id.split(".")[1].lower()
            friendly_name = state.attributes.get("friendly_name", "").lower()
            all_names.extend([entity_name, friendly_name])

        all_text = " ".join(all_names)

        # Count signal matches for each type
        ev_charger_matches = sum(1 for sig in EV_CHARGER_SIGNALS if sig in all_text)
        water_heater_matches = sum(1 for sig in WATER_HEATER_SIGNALS if sig in all_text)
        ams_meter_matches = sum(1 for sig in AMS_POWER_METER_SIGNALS if sig in all_text)

        # Return type with most matches (threshold: at least 2 matches)
        matches = [
            (ev_charger_matches, AmperaDeviceType.EV_CHARGER),
            (water_heater_matches, AmperaDeviceType.WATER_HEATER),
            (ams_meter_matches, AmperaDeviceType.POWER_METER),
        ]
        best_match = max(matches, key=lambda x: x[0])

        if best_match[0] >= 2:
            _LOGGER.debug(
                "Detected %s from signals (%d matches)",
                best_match[1].value,
                best_match[0],
            )
            return best_match[1]

        return None

    def _determine_device_type(
        self,
        device_name: str | None,
        entities: list[State],
        manufacturer: str | None,
    ) -> AmperaDeviceType:
        """Determine the Ampæra device type based on device info and entities.

        Uses a three-tier detection hierarchy:
        1. Known integration detection (most reliable) - e.g., 'easee', 'zaptec'
        2. Semantic signal matching - entity name patterns like 'session_energy'
        3. Keyword matching (fallback) - simple text search

        This approach prioritizes specificity and reduces false positives.
        """
        # Tier 1: Known integration detection (most reliable)
        device_type = self._detect_device_type_from_integration(entities)
        if device_type:
            return device_type

        # Tier 2: Semantic signal detection
        device_type = self._detect_device_type_from_signals(entities)
        if device_type:
            return device_type

        # Tier 3: Keyword-based detection (fallback)
        # Build searchable text from device name, manufacturer, and entity names
        search_text = " ".join(
            filter(
                None,
                [
                    device_name,
                    manufacturer,
                    *[e.attributes.get("friendly_name", "") for e in entities],
                    *[e.entity_id.split(".")[1] for e in entities],
                ],
            )
        ).lower()

        # Check for EV charger keywords
        if any(kw in search_text for kw in EV_CHARGER_KEYWORDS):
            return AmperaDeviceType.EV_CHARGER

        # Check for water heater domain or keywords
        if any(e.entity_id.startswith("water_heater.") for e in entities):
            return AmperaDeviceType.WATER_HEATER
        if any(kw in search_text for kw in WATER_HEATER_KEYWORDS):
            return AmperaDeviceType.WATER_HEATER

        # Check for AMS/power meter keywords
        if any(kw in search_text for kw in AMS_KEYWORDS):
            return AmperaDeviceType.POWER_METER

        # Check for climate domain
        if any(e.entity_id.startswith("climate.") for e in entities):
            return AmperaDeviceType.CLIMATE

        # Check for switch domain
        if any(e.entity_id.startswith("switch.") for e in entities):
            return AmperaDeviceType.SWITCH

        # Default to power_meter if has power/energy sensors
        if any(e.attributes.get("device_class") in ("power", "energy") for e in entities):
            return AmperaDeviceType.POWER_METER

        return AmperaDeviceType.SENSOR

    def _analyze_entity_capability(
        self, state: State
    ) -> tuple[AmperaCapability | None, str | None]:
        """Analyze an entity and determine its capability.

        Returns (capability, device_class) or (None, None) if not relevant.
        """
        entity_id = state.entity_id
        domain = entity_id.split(".")[0]

        if domain not in SUPPORTED_DOMAINS:
            return None, None

        device_class = state.attributes.get("device_class")
        friendly_name = state.attributes.get("friendly_name", entity_id).lower()

        # Sensor domain
        if domain == "sensor":
            if device_class == "power":
                # Check for phase-specific power sensors
                # Phase indicators: l1, l2, l3, phase 1, phase 2, phase 3
                if "l1" in friendly_name or "phase 1" in friendly_name:
                    return AmperaCapability.POWER_L1, device_class
                elif "l2" in friendly_name or "phase 2" in friendly_name:
                    return AmperaCapability.POWER_L2, device_class
                elif "l3" in friendly_name or "phase 3" in friendly_name:
                    return AmperaCapability.POWER_L3, device_class
                # Total power (no phase indicator) - this is preferred
                return AmperaCapability.POWER, device_class
            elif device_class == "energy":
                # Check if it's import/export or session energy
                if "export" in friendly_name:
                    return AmperaCapability.ENERGY_EXPORT, device_class
                elif "import" in friendly_name:
                    return AmperaCapability.ENERGY_IMPORT, device_class
                elif "session" in friendly_name:
                    return AmperaCapability.SESSION_ENERGY, device_class
                return AmperaCapability.ENERGY, device_class
            elif device_class == "voltage":
                # Check for phase-specific voltage
                if "l1" in friendly_name or "phase 1" in friendly_name:
                    return AmperaCapability.VOLTAGE_L1, device_class
                elif "l2" in friendly_name or "phase 2" in friendly_name:
                    return AmperaCapability.VOLTAGE_L2, device_class
                elif "l3" in friendly_name or "phase 3" in friendly_name:
                    return AmperaCapability.VOLTAGE_L3, device_class
                return AmperaCapability.VOLTAGE, device_class
            elif device_class == "current":
                # Check for phase-specific current
                if "l1" in friendly_name or "phase 1" in friendly_name:
                    return AmperaCapability.CURRENT_L1, device_class
                elif "l2" in friendly_name or "phase 2" in friendly_name:
                    return AmperaCapability.CURRENT_L2, device_class
                elif "l3" in friendly_name or "phase 3" in friendly_name:
                    return AmperaCapability.CURRENT_L3, device_class
                return AmperaCapability.CURRENT, device_class
            elif device_class == "temperature":
                return AmperaCapability.TEMPERATURE, device_class

        # Water heater domain
        elif domain == "water_heater":
            return AmperaCapability.TEMPERATURE, "water_heater"

        # Switch domain
        elif domain == "switch":
            return AmperaCapability.ON_OFF, "switch"

        # Climate domain
        elif domain == "climate":
            return AmperaCapability.TEMPERATURE, "climate"

        return None, None

    def discover_devices(self) -> list[DiscoveredDevice]:
        """Find all devices suitable for Ampæra sync.

        Groups entities by their parent device_id and returns one
        DiscoveredDevice per physical device with combined capabilities.

        Note: All entity types are included (real hardware, templates, helpers)
        to support demo/development environments with simulated devices.
        """
        self._ensure_registries()

        # Step 1: Group entities by parent device_id
        device_entities: dict[str, list[State]] = {}
        orphan_entities: list[State] = []  # Entities without parent device

        for state in self._hass.states.async_all():
            entity_id = state.entity_id
            domain = entity_id.split(".")[0]

            if domain not in SUPPORTED_DOMAINS:
                continue

            device_id = self._get_parent_device_id(entity_id)
            if device_id:
                device_entities.setdefault(device_id, []).append(state)
            else:
                # Entity without parent device - treat as standalone
                orphan_entities.append(state)

        # Step 2: Build DiscoveredDevice per parent device
        devices: list[DiscoveredDevice] = []

        for device_id, entities in device_entities.items():
            device = self._build_device_from_entities(device_id, entities)
            if device:
                devices.append(device)

        # Step 3: Handle orphan entities - GROUP by type instead of individual devices
        # This creates virtual parent devices for orphan sensors of the same type
        orphan_groups = self._group_orphan_entities(orphan_entities)
        for group_id, orphan_group in orphan_groups.items():
            device = self._build_orphan_group_device(group_id, orphan_group)
            if device:
                devices.append(device)

        _LOGGER.info(
            "Discovered %d devices for Ampæra sync (from %d parent devices, %d orphan entities)",
            len(devices),
            len(device_entities),
            len(orphan_entities),
        )
        return devices

    def _is_control_only_device(self, entities: list[State]) -> bool:
        """Check if device is a control-only device (input helper) for another device.

        Returns True if the device:
        1. Contains ONLY switch/input_* entities (no sensors)
        2. AND entity names match known device type keywords (water, ev, charger, etc.)

        These are likely HA input helpers used to control water heaters, EV chargers, etc.
        and should not be discovered as separate devices.
        """
        # Check if all entities are switches or input helpers
        has_sensors = False
        switch_entities: list[State] = []

        for state in entities:
            domain = state.entity_id.split(".")[0]
            if domain == "sensor":
                has_sensors = True
                break
            elif domain in ("switch", "input_boolean", "input_number", "input_select"):
                switch_entities.append(state)

        # If has sensors, it's a real device
        if has_sensors:
            return False

        # If no switch-like entities, not a control device
        if not switch_entities:
            return False

        # Check if entity names match known device type keywords
        # These keywords indicate the switch is a control for another device type
        control_keywords = {
            # EV charger controls
            "ev", "charger", "lader", "elbil", "charging",
            # Water heater controls
            "water", "heater", "varmtvann", "bereder", "boiler",
            # Generic device controls (these shouldn't be separate devices)
            "smart", "power", "enable", "disable", "boost", "eco",
        }

        for state in switch_entities:
            entity_name = state.entity_id.split(".")[1].lower()
            friendly_name = state.attributes.get("friendly_name", "").lower()
            search_text = f"{entity_name} {friendly_name}"

            if any(kw in search_text for kw in control_keywords):
                return True

        return False

    def _build_device_from_entities(
        self, device_id: str, entities: list[State]
    ) -> DiscoveredDevice | None:
        """Build a DiscoveredDevice from a group of entities.

        Analyzes all entities belonging to a parent device and combines
        their capabilities into a single device.
        """
        if not entities:
            return None

        # Skip devices that are ONLY switches with names matching other device types
        # These are likely input helpers used to control other devices (water heaters, EV chargers)
        # and should not be discovered as separate devices
        if self._is_control_only_device(entities):
            _LOGGER.debug(
                "Skipping control-only device (likely input helper): %s",
                device_id,
            )
            return None

        # Get device info from registry
        device_name, manufacturer, model = self._get_device_info(device_id)

        # Determine device type
        device_type = self._determine_device_type(device_name, entities, manufacturer)

        # Analyze each entity and build capability mapping
        capabilities: list[AmperaCapability] = []
        entity_mapping: dict[str, str] = {}
        primary_entity_id: str = ""

        # Track power entities for primary selection
        best_power_entity: str = ""
        best_consumption_entity: str = ""

        for state in entities:
            capability, device_class = self._analyze_entity_capability(state)
            if capability:
                # Avoid duplicate capabilities
                if capability not in capabilities:
                    capabilities.append(capability)
                    entity_mapping[capability.value] = state.entity_id

                # Track power entities for primary selection
                if capability == AmperaCapability.POWER:
                    friendly_name = state.attributes.get("friendly_name", "").lower()
                    entity_id_lower = state.entity_id.lower()
                    # Prefer "consumption" or "total" entities as they represent total power
                    if "consumption" in friendly_name or "consumption" in entity_id_lower:
                        best_consumption_entity = state.entity_id
                    elif "total" in friendly_name or "total" in entity_id_lower:
                        best_consumption_entity = state.entity_id
                    elif not best_power_entity:
                        best_power_entity = state.entity_id

        # Select primary: prefer consumption > any power > first entity
        if best_consumption_entity:
            primary_entity_id = best_consumption_entity
        elif best_power_entity:
            primary_entity_id = best_power_entity
        elif entities:
            primary_entity_id = entities[0].entity_id

        # Skip devices with no relevant capabilities
        if not capabilities:
            return None

        # Use device registry name if available, else first entity's friendly name
        if not device_name:
            device_name = entities[0].attributes.get("friendly_name", entities[0].entity_id)

        return DiscoveredDevice(
            ha_device_id=device_id,
            name=device_name,
            device_type=device_type,
            capabilities=capabilities,
            entity_mapping=entity_mapping,
            primary_entity_id=primary_entity_id,
            manufacturer=manufacturer,
            model=model,
        )

    def _detect_orphan_device_type(
        self, state: State, device_class: str | None
    ) -> str:
        """Detect device type for an orphan entity using smart detection.

        Uses the same hierarchical detection as parent devices:
        1. Integration platform detection
        2. Semantic signal matching
        3. Keyword matching

        Returns group_id for the entity.
        """
        entity_id = state.entity_id
        domain = entity_id.split(".")[0]
        entity_name = entity_id.split(".")[1].lower()
        friendly_name = state.attributes.get("friendly_name", "").lower()

        # Tier 1: Check integration platform
        platform = self._get_entity_platform(entity_id)
        if platform:
            platform_lower = platform.lower()
            if platform_lower in KNOWN_EV_CHARGER_INTEGRATIONS:
                return "virtual_ev_charger"
            if platform_lower in KNOWN_WATER_HEATER_INTEGRATIONS:
                return "virtual_water_heater"
            if platform_lower in KNOWN_POWER_METER_INTEGRATIONS:
                return "virtual_power_meter"

        # Tier 2: Semantic signal matching
        search_text = f"{entity_name} {friendly_name}"

        # Count signal matches
        ev_matches = sum(1 for sig in EV_CHARGER_SIGNALS if sig in search_text)
        wh_matches = sum(1 for sig in WATER_HEATER_SIGNALS if sig in search_text)
        ams_matches = sum(1 for sig in AMS_POWER_METER_SIGNALS if sig in search_text)

        # If strong signal match (2+), use that type
        if ev_matches >= 2:
            return "virtual_ev_charger"
        if wh_matches >= 2:
            return "virtual_water_heater"
        if ams_matches >= 2:
            return "virtual_power_meter"

        # Tier 3: Keyword matching for single matches
        # EV charger detection
        for kw in EV_CHARGER_KEYWORDS:
            if kw in search_text:
                return "virtual_ev_charger"

        # Water heater detection
        for kw in WATER_HEATER_KEYWORDS:
            if kw in search_text:
                return "virtual_water_heater"

        # Domain-based detection
        if domain == "water_heater":
            return "virtual_water_heater"

        # For power/energy sensors without specific signals, default to power meter
        if device_class in ("power", "energy", "voltage", "current"):
            return "virtual_power_meter"

        # Temperature sensors need more context
        if device_class == "temperature":
            # Check if water heater related
            if any(kw in search_text for kw in WATER_HEATER_KEYWORDS):
                return "virtual_water_heater"
            # Otherwise standalone
            return f"orphan_{entity_id}"

        return f"orphan_{entity_id}"

    def _detect_orphan_switch_type(self, state: State) -> str:
        """Detect device type for an orphan switch entity.

        Switches may belong to water heaters, EV chargers, or other devices.
        Uses keyword matching to associate them with their logical device type.

        Returns group_id for the entity.
        """
        entity_id = state.entity_id
        entity_name = entity_id.split(".")[1].lower()
        friendly_name = state.attributes.get("friendly_name", "").lower()
        search_text = f"{entity_name} {friendly_name}"

        # Check integration platform first
        platform = self._get_entity_platform(entity_id)
        if platform:
            platform_lower = platform.lower()
            if platform_lower in KNOWN_EV_CHARGER_INTEGRATIONS:
                return "virtual_ev_charger"
            if platform_lower in KNOWN_WATER_HEATER_INTEGRATIONS:
                return "virtual_water_heater"

        # EV charger keywords (check first - more specific)
        ev_keywords = {"ev", "charger", "lader", "elbil", "easee", "zaptec", "wallbox"}
        if any(kw in search_text for kw in ev_keywords):
            return "virtual_ev_charger"

        # Water heater keywords
        wh_keywords = {"water", "heater", "varmtvann", "bereder", "boiler", "hot_water"}
        if any(kw in search_text for kw in wh_keywords):
            return "virtual_water_heater"

        # For other switches, don't create separate devices - skip them
        # This prevents creating duplicate "Water", "Ev", "Smart" devices
        # These orphan switches without clear association should be ignored
        _LOGGER.debug(
            "Skipping orphan switch without device association: %s",
            entity_id,
        )
        return f"skip_{entity_id}"

    def _group_orphan_entities(
        self, orphan_entities: list[State]
    ) -> dict[str, list[tuple[State, AmperaCapability]]]:
        """Group orphan entities by their logical type for consolidation.

        Uses smart device type detection (integration → signals → keywords)
        to group orphan entities that should belong together:
        - EV charger sensors/switches → "virtual_ev_charger" group
        - Water heater sensors/switches → "virtual_water_heater" group
        - AMS/power meter sensors → "virtual_power_meter" group
        - Climate entities → "virtual_climate" group
        - Other switch entities → grouped by name prefix

        Returns:
            Dict of group_id → list of (state, capability) tuples
        """
        groups: dict[str, list[tuple[State, AmperaCapability]]] = {}

        for state in orphan_entities:
            capability, device_class = self._analyze_entity_capability(state)
            if not capability:
                continue

            entity_id = state.entity_id
            domain = entity_id.split(".")[0]

            # Use smart detection for sensors
            if domain == "sensor":
                group_id = self._detect_orphan_device_type(state, device_class)
            elif domain == "water_heater":
                group_id = "virtual_water_heater"
            elif domain == "climate":
                group_id = "virtual_climate"
            elif domain == "switch":
                # Use smart detection for switches too - they may belong to EV chargers, water heaters
                group_id = self._detect_orphan_switch_type(state)
            else:
                # Individual orphan - keep as separate device
                group_id = f"orphan_{entity_id}"

            groups.setdefault(group_id, []).append((state, capability))

        return groups

    def _build_orphan_group_device(
        self, group_id: str, entities: list[tuple[State, AmperaCapability]]
    ) -> DiscoveredDevice | None:
        """Build a DiscoveredDevice from a group of orphan entities.

        Creates a virtual parent device for grouped orphan entities.
        """
        if not entities:
            return None

        # Skip groups marked for exclusion (orphan switches without clear device association)
        if group_id.startswith("skip_"):
            return None

        # Collect all capabilities and entity mappings
        capabilities: list[AmperaCapability] = []
        entity_mapping: dict[str, str] = {}
        primary_entity_id: str = ""

        # First pass: find the best primary entity
        # Prefer: 1) "consumption" or "total" in name 2) any POWER capability
        best_power_entity: str = ""
        best_consumption_entity: str = ""

        for state, capability in entities:
            if capability not in capabilities:
                capabilities.append(capability)
                entity_mapping[capability.value] = state.entity_id

            # Track power entities for primary selection
            if capability == AmperaCapability.POWER:
                friendly_name = state.attributes.get("friendly_name", "").lower()
                entity_id_lower = state.entity_id.lower()
                # Prefer "consumption" or "total" entities as they represent total power
                if "consumption" in friendly_name or "consumption" in entity_id_lower:
                    best_consumption_entity = state.entity_id
                elif "total" in friendly_name or "total" in entity_id_lower:
                    best_consumption_entity = state.entity_id
                elif not best_power_entity:
                    best_power_entity = state.entity_id

        # Select primary: prefer consumption > any power > first entity
        if best_consumption_entity:
            primary_entity_id = best_consumption_entity
        elif best_power_entity:
            primary_entity_id = best_power_entity
        elif entities:
            primary_entity_id = entities[0][0].entity_id

        if not capabilities:
            return None

        # Determine device type and name based on group
        if group_id == "virtual_power_meter":
            device_type = AmperaDeviceType.POWER_METER
            name = "Power Meter"
            # Check entity names for better naming
            for state, _ in entities:
                friendly_name = state.attributes.get("friendly_name", "")
                if friendly_name:
                    # Use first entity's name as base
                    name = friendly_name.replace("Power", "").replace("Energy", "").strip()
                    if not name:
                        name = "Power Meter"
                    else:
                        name = f"{name} Power Meter"
                    break
        elif group_id == "virtual_water_heater":
            device_type = AmperaDeviceType.WATER_HEATER
            name = "Water Heater"
        elif group_id == "virtual_ev_charger":
            device_type = AmperaDeviceType.EV_CHARGER
            name = "EV Charger"
        elif group_id == "virtual_climate":
            device_type = AmperaDeviceType.CLIMATE
            name = "Climate Control"
        elif group_id.startswith("virtual_switch_"):
            device_type = AmperaDeviceType.SWITCH
            name = group_id.replace("virtual_switch_", "").replace("_", " ").title()
        else:
            # Single orphan entity
            device_type = AmperaDeviceType.SENSOR
            state, _ = entities[0]
            name = state.attributes.get("friendly_name", state.entity_id)

        return DiscoveredDevice(
            ha_device_id=group_id,
            name=name,
            device_type=device_type,
            capabilities=capabilities,
            entity_mapping=entity_mapping,
            primary_entity_id=primary_entity_id,
        )

    def discover_by_domain(self, domain: str) -> list[DiscoveredDevice]:
        """Discover devices that have entities in a specific domain.

        Note: Returns all devices that have at least one entity in the domain,
        with all their capabilities (not just those from the domain).
        """
        all_devices = self.discover_devices()
        return [
            d
            for d in all_devices
            if any(entity_id.startswith(f"{domain}.") for entity_id in d.entity_mapping.values())
        ]

    def get_device_options(self) -> list[dict]:
        """Get devices formatted for config flow selection.

        Returns list of dicts with 'value' and 'label' for SelectSelector.
        Now returns device_id as value (not entity_id).
        """
        devices = self.discover_devices()

        return [
            {
                "value": device.ha_device_id,
                "label": f"{device.name} ({device.device_type.value}) - {len(device.capabilities)} sensors",
            }
            for device in devices
        ]

    def get_devices_by_ids(self, device_ids: list[str]) -> list[DiscoveredDevice]:
        """Get discovered device info for specific device IDs.

        Args:
            device_ids: List of HA device registry IDs (or orphan pseudo-IDs)
        """
        all_devices = self.discover_devices()
        return [d for d in all_devices if d.ha_device_id in device_ids]
