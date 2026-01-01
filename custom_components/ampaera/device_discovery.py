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

    POWER = "power"
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

# Keywords to identify device types from device/entity names
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

    def _determine_device_type(
        self,
        device_name: str | None,
        entities: list[State],
        manufacturer: str | None,
    ) -> AmperaDeviceType:
        """Determine the Ampæra device type based on device info and entities.

        Uses device name, manufacturer, and entity characteristics to classify.
        """
        # Build searchable text from device name, manufacturer, and entity names
        search_text = " ".join(
            filter(
                None,
                [
                    device_name,
                    manufacturer,
                    *[e.attributes.get("friendly_name", "") for e in entities],
                ],
            )
        ).lower()

        # Check for EV charger
        if any(kw in search_text for kw in EV_CHARGER_KEYWORDS):
            return AmperaDeviceType.EV_CHARGER

        # Check for water heater domain or keywords
        if any(e.entity_id.startswith("water_heater.") for e in entities):
            return AmperaDeviceType.WATER_HEATER
        if any(kw in search_text for kw in WATER_HEATER_KEYWORDS):
            return AmperaDeviceType.WATER_HEATER

        # Check for AMS/power meter
        if any(kw in search_text for kw in AMS_KEYWORDS):
            return AmperaDeviceType.POWER_METER

        # Check for climate
        if any(e.entity_id.startswith("climate.") for e in entities):
            return AmperaDeviceType.CLIMATE

        # Check for switch
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

    def _build_device_from_entities(
        self, device_id: str, entities: list[State]
    ) -> DiscoveredDevice | None:
        """Build a DiscoveredDevice from a group of entities.

        Analyzes all entities belonging to a parent device and combines
        their capabilities into a single device.
        """
        if not entities:
            return None

        # Get device info from registry
        device_name, manufacturer, model = self._get_device_info(device_id)

        # Determine device type
        device_type = self._determine_device_type(device_name, entities, manufacturer)

        # Analyze each entity and build capability mapping
        capabilities: list[AmperaCapability] = []
        entity_mapping: dict[str, str] = {}
        primary_entity_id: str = ""

        for state in entities:
            capability, device_class = self._analyze_entity_capability(state)
            if capability:
                # Avoid duplicate capabilities
                if capability not in capabilities:
                    capabilities.append(capability)
                    entity_mapping[capability.value] = state.entity_id

                # Set primary entity (prefer power sensor, then first entity)
                if not primary_entity_id or device_class == "power":
                    primary_entity_id = state.entity_id

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

    def _group_orphan_entities(
        self, orphan_entities: list[State]
    ) -> dict[str, list[tuple[State, AmperaCapability]]]:
        """Group orphan entities by their logical type for consolidation.

        Groups orphan entities that should belong together:
        - All power/energy sensors → "power_meter" group
        - All water_heater entities → "water_heater" group
        - All switch entities → by switch name prefix
        - All climate entities → "climate" group

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
            friendly_name = state.attributes.get("friendly_name", entity_id).lower()

            # Determine group based on domain and device class
            if domain == "sensor" and device_class in ("power", "energy", "voltage", "current"):
                # Group all power/energy sensors together as a power meter
                group_id = "virtual_power_meter"
            elif domain == "water_heater":
                group_id = "virtual_water_heater"
            elif domain == "climate":
                group_id = "virtual_climate"
            elif domain == "switch":
                # Try to group switches by name prefix (e.g., "living_room_")
                name_parts = entity_id.split(".")[1].split("_")
                if len(name_parts) >= 2:
                    group_id = f"virtual_switch_{name_parts[0]}"
                else:
                    group_id = f"virtual_switch_{entity_id}"
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

        # Collect all capabilities and entity mappings
        capabilities: list[AmperaCapability] = []
        entity_mapping: dict[str, str] = {}
        primary_entity_id: str = ""

        for state, capability in entities:
            if capability not in capabilities:
                capabilities.append(capability)
                entity_mapping[capability.value] = state.entity_id

            # Set primary entity (prefer power sensor)
            if not primary_entity_id or capability == AmperaCapability.POWER:
                primary_entity_id = state.entity_id

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
