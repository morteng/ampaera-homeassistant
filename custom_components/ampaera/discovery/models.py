"""Data models for the Ampæra discovery pipeline.

Defines the core dataclasses and enums used throughout the discovery
pipeline stages: entity scanning, capability mapping, device classification,
and reporting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class AmperaDeviceType(StrEnum):
    """Device types supported by Ampæra."""

    POWER_METER = "power_meter"
    WATER_HEATER = "water_heater"
    EV_CHARGER = "ev_charger"
    SWITCH = "switch"
    CLIMATE = "climate"
    SENSOR = "sensor"


class AmperaCapability(StrEnum):
    """Capabilities a device can have."""

    POWER = "power"
    POWER_L1 = "power_l1"
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
    ENERGY_HOUR = "energy_hour"
    ENERGY_DAY = "energy_day"
    ENERGY_MONTH = "energy_month"
    COST_DAY = "cost_day"
    PEAK_MONTH_1 = "peak_month_1"
    PEAK_MONTH_2 = "peak_month_2"
    PEAK_MONTH_3 = "peak_month_3"


@dataclass
class DiscoveredEntity:
    """An entity discovered during the scanning stage."""

    entity_id: str
    domain: str
    device_id: str | None
    platform: str | None
    device_class: str | None
    friendly_name: str
    unit: str | None
    enabled: bool
    disabled_by: str | None
    state_value: str | None
    capability: AmperaCapability | None = None
    capability_confidence: float = 0.0
    channel_id: str | None = None


@dataclass
class DiscoveredDevice:
    """A device discovered in Home Assistant.

    Represents a physical device (grouped by HA device_id) with
    multiple entities mapped to capabilities.
    """

    ha_device_id: str
    name: str
    device_type: AmperaDeviceType
    manufacturer: str | None
    model: str | None
    entities: list[DiscoveredEntity]
    capabilities: list[AmperaCapability]
    entity_mapping: dict[str, str]  # capability_value -> entity_id
    primary_entity_id: str
    classification_reason: str
    channel_id: str | None = None
    # Whether this device is relevant to energy management. Devices like
    # camera switches, notification toggles, motion-detection sensors etc.
    # are filtered out of the default selection list. Set to False to hide
    # by default; users can opt in via the "show all devices" toggle.
    is_energy_relevant: bool = True
    # Whether this device should be pre-selected by default in the picker.
    # True for AMS meters, EV chargers, water heaters, EM-style energy
    # meters; False for ambiguous or supplementary devices.
    is_recommended: bool = False

    def display_name(self) -> str:
        """Return a human-readable label for the device picker.

        Strips redundant capability codes ("(MONTHUSE)", "(CH_1)", etc.)
        from the raw HA name and translates known AMS/OBIS suffixes to
        Norwegian labels via OBIS_LABEL_MAP.
        """
        # Local import to avoid circular dependency with signatures.
        from .signatures import OBIS_LABEL_MAP

        name = self.name

        # Replace any "(CODE)" suffix with the human-readable label when known.
        def _replace_code(match: "re.Match[str]") -> str:
            code = match.group(1)
            label = OBIS_LABEL_MAP.get(code.upper())
            if label:
                return f"({label})"
            # CH_n channel suffixes: drop them — they're noise in the picker.
            if re.match(r"^CH_\d+$", code, re.IGNORECASE):
                return ""
            return match.group(0)

        cleaned = re.sub(r"\(([A-Za-z0-9_]+)\)", _replace_code, name)
        # Collapse double spaces left by removed channel suffixes.
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned or name

    def to_dict(self) -> dict:
        """Convert to API format.

        MUST match the current DiscoveredDevice.to_dict() output format
        used by the API registration endpoint.
        """
        result = {
            "ha_device_id": self.ha_device_id,
            "ha_entity_id": self.primary_entity_id,
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


# ---------------------------------------------------------------------------
# Discovery report dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExcludedEntity:
    """An entity that was excluded from discovery."""

    entity_id: str
    reason: str


@dataclass
class UnmappedEntity:
    """An entity that could not be mapped to a capability."""

    entity_id: str
    device_class: str | None
    reason: str


@dataclass
class ClassificationDetail:
    """Details about how a device was classified."""

    device_id: str
    device_name: str
    device_type: str
    detection_tier: str
    confidence: str
    entity_count: int


@dataclass
class SplitDetail:
    """Details about a channel split operation."""

    device_id: str
    action: str
    reason: str
    channels: list[str] | None = None


@dataclass
class DiscoveryReport:
    """Full report from a discovery pipeline run."""

    # Timing
    timestamp: datetime | None = None
    duration_ms: float = 0.0

    # Entity scanning
    total_entities_scanned: int = 0
    enabled_entities: int = 0
    disabled_entities: int = 0
    entities_by_domain: dict[str, int] = field(default_factory=dict)
    entities_by_platform: dict[str, int] = field(default_factory=dict)
    excluded_entities: list[ExcludedEntity] = field(default_factory=list)

    # Capability mapping
    entities_with_capability: int = 0
    entities_without_capability: int = 0
    unmapped_entities: list[UnmappedEntity] = field(default_factory=list)
    capability_distribution: dict[str, int] = field(default_factory=dict)

    # Device classification
    devices_found: int = 0
    devices_by_type: dict[str, int] = field(default_factory=dict)
    orphan_entities: int = 0
    orphan_groups_created: int = 0
    classification_details: list[ClassificationDetail] = field(default_factory=list)

    # Channel splitting
    channel_splits_performed: int = 0
    channel_splits_skipped: int = 0
    split_details: list[SplitDetail] = field(default_factory=list)

    # Sync
    auto_enabled_entities: list[str] = field(default_factory=list)
    devices_synced: int = 0
    devices_filtered_out: int = 0
