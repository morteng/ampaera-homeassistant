"""Device discovery service for Ampæra HA integration.

Discovers Home Assistant devices suitable for syncing to Ampæra:
- Power/energy sensors (AMS meters, smart plugs)
- Water heaters
- Switches (smart relays)
- Climate devices (HVAC)

Also extracts device metadata (manufacturer, model) from HA device registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    SWITCH = "switch"
    CLIMATE = "climate"
    SENSOR = "sensor"


class AmperaCapability(str, Enum):
    """Capabilities a device can have."""

    POWER = "power"
    ENERGY = "energy"
    VOLTAGE = "voltage"
    CURRENT = "current"
    TEMPERATURE = "temperature"
    ON_OFF = "on_off"
    HUMIDITY = "humidity"


@dataclass
class DiscoveredDevice:
    """A device discovered in Home Assistant."""

    entity_id: str
    name: str
    device_type: AmperaDeviceType
    capabilities: list[AmperaCapability]
    device_class: str | None = None
    unit: str | None = None
    manufacturer: str | None = None
    model: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API registration."""
        result = {
            "ha_entity_id": self.entity_id,
            "device_type": self.device_type.value,
            "name": self.name,
            "capabilities": [c.value for c in self.capabilities],
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


class AmperaDeviceDiscovery:
    """Discover HA devices suitable for Ampæra sync."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize device discovery."""
        self._hass = hass
        self._entity_registry: er.EntityRegistry | None = None
        self._device_registry: dr.DeviceRegistry | None = None

    def _get_device_info(self, entity_id: str) -> tuple[str | None, str | None]:
        """Get manufacturer and model from device registry for an entity.

        Returns tuple of (manufacturer, model), either may be None.
        """
        # Lazy load registries
        if self._entity_registry is None:
            self._entity_registry = er.async_get(self._hass)
        if self._device_registry is None:
            self._device_registry = dr.async_get(self._hass)

        # Get entity registry entry
        entity_entry = self._entity_registry.async_get(entity_id)
        if entity_entry is None or entity_entry.device_id is None:
            return None, None

        # Get device registry entry
        device_entry = self._device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            return None, None

        return device_entry.manufacturer, device_entry.model

    def discover_devices(self) -> list[DiscoveredDevice]:
        """Find all devices suitable for Ampæra sync.

        Returns list of discovered devices with their capabilities.
        """
        devices: list[DiscoveredDevice] = []

        for state in self._hass.states.async_all():
            device = self._analyze_entity(state)
            if device:
                devices.append(device)

        _LOGGER.info("Discovered %d devices for Ampæra sync", len(devices))
        return devices

    def discover_by_domain(self, domain: str) -> list[DiscoveredDevice]:
        """Discover devices in a specific domain."""
        devices: list[DiscoveredDevice] = []

        for state in self._hass.states.async_all(domain):
            device = self._analyze_entity(state)
            if device:
                devices.append(device)

        return devices

    def _analyze_entity(self, state: State) -> DiscoveredDevice | None:
        """Analyze an entity and determine if it's suitable for Ampæra.

        Returns DiscoveredDevice if suitable, None otherwise.
        """
        entity_id = state.entity_id
        domain = entity_id.split(".")[0]

        if domain not in SUPPORTED_DOMAINS:
            return None

        # Get device class and unit
        device_class = state.attributes.get("device_class")
        unit = state.attributes.get("unit_of_measurement")
        friendly_name = state.attributes.get("friendly_name", entity_id)

        # Get manufacturer and model from device registry
        manufacturer, model = self._get_device_info(entity_id)

        # Analyze based on domain
        if domain == "sensor":
            return self._analyze_sensor(
                entity_id, friendly_name, device_class, unit, manufacturer, model
            )
        elif domain == "water_heater":
            return self._analyze_water_heater(
                entity_id, friendly_name, state, manufacturer, model
            )
        elif domain == "switch":
            return self._analyze_switch(
                entity_id, friendly_name, state, manufacturer, model
            )
        elif domain == "climate":
            return self._analyze_climate(
                entity_id, friendly_name, state, manufacturer, model
            )

        return None

    def _analyze_sensor(
        self,
        entity_id: str,
        name: str,
        device_class: str | None,
        unit: str | None,
        manufacturer: str | None,
        model: str | None,
    ) -> DiscoveredDevice | None:
        """Analyze a sensor entity."""
        if device_class not in ENERGY_DEVICE_CLASSES:
            return None

        capabilities: list[AmperaCapability] = []

        if device_class == "power":
            capabilities.append(AmperaCapability.POWER)
        elif device_class == "energy":
            capabilities.append(AmperaCapability.ENERGY)
        elif device_class == "voltage":
            capabilities.append(AmperaCapability.VOLTAGE)
        elif device_class == "current":
            capabilities.append(AmperaCapability.CURRENT)

        if not capabilities:
            return None

        return DiscoveredDevice(
            entity_id=entity_id,
            name=name,
            device_type=AmperaDeviceType.POWER_METER,
            capabilities=capabilities,
            device_class=device_class,
            unit=unit,
            manufacturer=manufacturer,
            model=model,
        )

    def _analyze_water_heater(
        self,
        entity_id: str,
        name: str,
        state: State,  # noqa: ARG002
        manufacturer: str | None,
        model: str | None,
    ) -> DiscoveredDevice | None:
        """Analyze a water heater entity."""
        capabilities = [
            AmperaCapability.TEMPERATURE,
            AmperaCapability.ON_OFF,
        ]

        return DiscoveredDevice(
            entity_id=entity_id,
            name=name,
            device_type=AmperaDeviceType.WATER_HEATER,
            capabilities=capabilities,
            manufacturer=manufacturer,
            model=model,
        )

    def _analyze_switch(
        self,
        entity_id: str,
        name: str,
        state: State,
        manufacturer: str | None,
        model: str | None,
    ) -> DiscoveredDevice | None:
        """Analyze a switch entity.

        Only include switches that look like they control energy devices.
        """
        # Check if switch has power monitoring
        has_power = "current_power_w" in state.attributes
        has_energy = "total_energy_kwh" in state.attributes

        capabilities = [AmperaCapability.ON_OFF]

        if has_power:
            capabilities.append(AmperaCapability.POWER)
        if has_energy:
            capabilities.append(AmperaCapability.ENERGY)

        # Include all switches - let the user decide which to sync during config flow
        # Previously used hardcoded keywords, but this violated anti-hardcoding principles
        # and missed devices with non-English names or unconventional naming
        return DiscoveredDevice(
            entity_id=entity_id,
            name=name,
            device_type=AmperaDeviceType.SWITCH,
            capabilities=capabilities,
            manufacturer=manufacturer,
            model=model,
        )

    def _analyze_climate(
        self,
        entity_id: str,
        name: str,
        state: State,
        manufacturer: str | None,
        model: str | None,
    ) -> DiscoveredDevice | None:
        """Analyze a climate entity."""
        capabilities = [
            AmperaCapability.TEMPERATURE,
            AmperaCapability.ON_OFF,
        ]

        # Check for humidity
        if "current_humidity" in state.attributes:
            capabilities.append(AmperaCapability.HUMIDITY)

        return DiscoveredDevice(
            entity_id=entity_id,
            name=name,
            device_type=AmperaDeviceType.CLIMATE,
            capabilities=capabilities,
            manufacturer=manufacturer,
            model=model,
        )

    def get_device_options(self) -> list[dict]:
        """Get devices formatted for config flow selection.

        Returns list of dicts with 'value' and 'label' for SelectSelector.
        """
        devices = self.discover_devices()

        return [
            {
                "value": device.entity_id,
                "label": f"{device.name} ({device.device_type.value})",
            }
            for device in devices
        ]

    def get_devices_by_ids(self, entity_ids: list[str]) -> list[DiscoveredDevice]:
        """Get discovered device info for specific entity IDs."""
        all_devices = self.discover_devices()
        return [d for d in all_devices if d.entity_id in entity_ids]
