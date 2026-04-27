"""Stage 3: Device classification for the Ampæra discovery pipeline.

Groups DiscoveredEntity objects by parent device_id, classifies each
group into an AmperaDeviceType, maps capabilities to entity IDs, and
handles orphan entities without a parent device. Pure Python - no
Home Assistant dependencies.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from .models import (
    AmperaCapability,
    AmperaDeviceType,
    ClassificationDetail,
    DiscoveredDevice,
    DiscoveredEntity,
    DiscoveryReport,
)
from .signatures import (
    KEYWORDS,
    KNOWN_INTEGRATIONS,
    NON_ENERGY_INTEGRATIONS,
    NON_ENERGY_KEYWORDS,
    SEMANTIC_SIGNALS,
)

_LOGGER = logging.getLogger(__name__)

# Keywords for detecting control-only devices (input helpers)
_CONTROL_KEYWORDS: set[str] = {
    # EV charger controls
    "ev",
    "charger",
    "lader",
    "elbil",
    "charging",
    # Water heater controls
    "water",
    "heater",
    "varmtvann",
    "bereder",
    "boiler",
    # Generic device controls
    "smart",
    "power",
    "enable",
    "disable",
    "boost",
    "eco",
}

# Virtual device type names mapped to AmperaDeviceType and display name
_VIRTUAL_DEVICE_MAP: dict[str, tuple[AmperaDeviceType, str]] = {
    "virtual_power_meter": (AmperaDeviceType.POWER_METER, "Power Meter"),
    "virtual_water_heater": (AmperaDeviceType.WATER_HEATER, "Water Heater"),
    "virtual_ev_charger": (AmperaDeviceType.EV_CHARGER, "EV Charger"),
    "virtual_climate": (AmperaDeviceType.CLIMATE, "Climate Control"),
}

# Virtual device types to skip in simulation mode
_SIMULATION_SKIP_TYPES: set[str] = {
    "virtual_water_heater",
    "virtual_ev_charger",
    "virtual_power_meter",
}


class DeviceClassifier:
    """Stage 3: Group entities by device and classify each device."""

    def __init__(self, simulation_mode: bool = False) -> None:
        self._simulation_mode = simulation_mode

    def classify(
        self,
        entities: list[DiscoveredEntity],
        device_info: dict[str, tuple[str | None, str | None, str | None]],
        report: DiscoveryReport,
    ) -> list[DiscoveredDevice]:
        """Group entities by device_id and classify each group.

        Args:
            entities: Entities with capabilities set (from CapabilityAnalyzer)
            device_info: dict mapping device_id -> (name, manufacturer, model)
                         from HA device registry. Provided by orchestrator.
            report: Discovery report to update

        Returns:
            List of classified devices
        """
        # Step 1: Group entities by device_id
        device_groups: dict[str, list[DiscoveredEntity]] = defaultdict(list)
        orphan_entities: list[DiscoveredEntity] = []

        for entity in entities:
            if entity.device_id:
                device_groups[entity.device_id].append(entity)
            else:
                orphan_entities.append(entity)

        # Step 2: Build devices from groups
        devices: list[DiscoveredDevice] = []

        for device_id, group in device_groups.items():
            name, manufacturer, model = device_info.get(device_id, (None, None, None))
            device = self._build_device(device_id, group, name, manufacturer, model)
            if device:
                devices.append(device)

        # Step 3: Handle orphan entities
        orphan_groups = self._group_orphan_entities(orphan_entities)
        orphan_groups_created = 0

        for group_id, orphan_group in orphan_groups.items():
            if group_id.startswith("skip_"):
                continue
            if self._simulation_mode and group_id in _SIMULATION_SKIP_TYPES:
                _LOGGER.debug(
                    "Skipping virtual device %s in simulation mode",
                    group_id,
                )
                continue
            device = self._build_orphan_device(group_id, orphan_group)
            if device:
                devices.append(device)
                orphan_groups_created += 1

        # Step 4: Update report
        report.devices_found = len(devices)
        report.orphan_entities = len(orphan_entities)
        report.orphan_groups_created = orphan_groups_created
        for device in devices:
            type_key = device.device_type.value
            report.devices_by_type[type_key] = report.devices_by_type.get(type_key, 0) + 1
            report.classification_details.append(
                ClassificationDetail(
                    device_id=device.ha_device_id,
                    device_name=device.name,
                    device_type=device.device_type.value,
                    detection_tier=(
                        device.classification_reason.split(":")[0]
                        if ":" in device.classification_reason
                        else device.classification_reason
                    ),
                    confidence=(
                        "high"
                        if device.classification_reason.startswith("integration")
                        else "medium"
                    ),
                    entity_count=len(device.entities),
                )
            )

        _LOGGER.info(
            "Classified %d devices (%d from parent devices, %d orphan groups)",
            len(devices),
            len(devices) - orphan_groups_created,
            orphan_groups_created,
        )
        return devices

    # ------------------------------------------------------------------
    # Device building
    # ------------------------------------------------------------------

    def _build_device(
        self,
        device_id: str,
        entities: list[DiscoveredEntity],
        device_name: str | None,
        manufacturer: str | None,
        model: str | None,
    ) -> DiscoveredDevice | None:
        """Build a DiscoveredDevice from a group of entities."""
        if not entities:
            return None

        # Skip control-only devices (input helpers)
        if self._is_control_only_device(entities):
            _LOGGER.debug("Skipping control-only device: %s", device_id)
            return None

        # Determine device type (3-tier detection)
        device_type, reason = self._determine_device_type(device_name, entities, manufacturer)

        # Build capability mapping
        capabilities, entity_mapping, primary_entity_id = self._map_capabilities(entities)

        if not capabilities:
            return None

        # Resolve display name
        if not device_name:
            device_name = entities[0].friendly_name or entities[0].entity_id

        device = DiscoveredDevice(
            ha_device_id=device_id,
            name=device_name,
            device_type=device_type,
            manufacturer=manufacturer,
            model=model,
            entities=entities,
            capabilities=capabilities,
            entity_mapping=entity_mapping,
            primary_entity_id=primary_entity_id,
            classification_reason=reason,
        )
        device.is_energy_relevant = self._is_energy_relevant(device)
        device.is_recommended = self._is_recommended(device)

        # Surface the mapped/total gap so users can see exactly which HA
        # entities Ampæra is skipping for a given device. Logged at INFO so
        # it shows up in the default HA log without enabling debug.
        enabled_entities = [e for e in entities if e.enabled]
        dropped = [e for e in enabled_entities if e.capability is None]
        if dropped:
            _LOGGER.info(
                "Ampaera: %s (%s) — mapping %d/%d HA sensors; dropping %d unmapped: %s",
                device_name,
                device_type.value,
                len(entity_mapping),
                len(enabled_entities),
                len(dropped),
                ", ".join(sorted(e.entity_id for e in dropped)),
            )
        return device

    # ------------------------------------------------------------------
    # 3-tier device type detection
    # ------------------------------------------------------------------

    def _determine_device_type(
        self,
        device_name: str | None,
        entities: list[DiscoveredEntity],
        manufacturer: str | None,
    ) -> tuple[AmperaDeviceType, str]:
        """Determine device type using 3-tier detection hierarchy.

        Returns:
            Tuple of (device_type, classification_reason)
        """
        # Tier 1: Known integration detection
        result = self._detect_from_integration(entities)
        if result:
            return result, f"integration: {entities[0].platform}"

        # Tier 2: Semantic signal detection
        result = self._detect_from_signals(entities)
        if result:
            return result, f"signal: {result.value}"

        # Tier 3: Keyword detection
        result = self._detect_from_keywords(device_name, entities, manufacturer)
        if result:
            return result, f"keyword: {result.value}"

        # Tier 4: Domain fallback
        return self._detect_from_domain(entities)

    def _detect_from_integration(self, entities: list[DiscoveredEntity]) -> AmperaDeviceType | None:
        """Tier 1: Check entity platforms against KNOWN_INTEGRATIONS."""
        for entity in entities:
            if not entity.platform:
                continue
            platform_lower = entity.platform.lower()
            device_type = KNOWN_INTEGRATIONS.get(platform_lower)
            if device_type is not None:
                _LOGGER.debug(
                    "Detected %s from integration: %s",
                    device_type.value,
                    entity.platform,
                )
                return device_type
        return None

    def _detect_from_signals(self, entities: list[DiscoveredEntity]) -> AmperaDeviceType | None:
        """Tier 2: Check entity names against SEMANTIC_SIGNALS patterns."""
        all_names: list[str] = []
        for entity in entities:
            entity_name = entity.entity_id.split(".")[1].lower()
            friendly = entity.friendly_name.lower()
            all_names.extend([entity_name, friendly])

        all_text = " ".join(all_names)

        matches: list[tuple[int, AmperaDeviceType]] = []
        for device_type, signals in SEMANTIC_SIGNALS.items():
            count = sum(1 for sig in signals if sig in all_text)
            matches.append((count, device_type))

        best = max(matches, key=lambda x: x[0])
        if best[0] >= 2:
            _LOGGER.debug(
                "Detected %s from signals (%d matches)",
                best[1].value,
                best[0],
            )
            return best[1]
        return None

    def _detect_from_keywords(
        self,
        device_name: str | None,
        entities: list[DiscoveredEntity],
        manufacturer: str | None,
    ) -> AmperaDeviceType | None:
        """Tier 3: Check device name, manufacturer, entity names against KEYWORDS."""
        search_parts = [
            device_name or "",
            manufacturer or "",
        ]
        for entity in entities:
            search_parts.append(entity.friendly_name)
            search_parts.append(entity.entity_id.split(".")[1])

        search_text = " ".join(search_parts).lower()

        for device_type, kws in KEYWORDS.items():
            if any(kw in search_text for kw in kws):
                return device_type
        return None

    def _detect_from_domain(self, entities: list[DiscoveredEntity]) -> tuple[AmperaDeviceType, str]:
        """Tier 4: Domain-based fallback."""
        for entity in entities:
            if entity.domain == "water_heater":
                return AmperaDeviceType.WATER_HEATER, "domain: water_heater"
        for entity in entities:
            if entity.domain == "climate":
                return AmperaDeviceType.CLIMATE, "domain: climate"
        for entity in entities:
            if entity.domain == "switch":
                return AmperaDeviceType.SWITCH, "domain: switch"
        for entity in entities:
            if entity.device_class in ("power", "energy"):
                return AmperaDeviceType.POWER_METER, "domain: power/energy device_class"
        return AmperaDeviceType.SENSOR, "domain: fallback"

    # ------------------------------------------------------------------
    # Capability mapping & primary entity selection
    # ------------------------------------------------------------------

    def _map_capabilities(
        self, entities: list[DiscoveredEntity]
    ) -> tuple[list[AmperaCapability], dict[str, str], str]:
        """Map entity capabilities and select primary entity.

        Returns:
            (capabilities, entity_mapping, primary_entity_id)
        """
        capabilities: list[AmperaCapability] = []
        entity_mapping: dict[str, str] = {}
        best_power_entity = ""
        best_consumption_entity = ""

        for entity in entities:
            cap = entity.capability
            if cap is None:
                continue

            if cap not in capabilities:
                capabilities.append(cap)
                entity_mapping[cap.value] = entity.entity_id
            else:
                # Prefer higher capability_confidence first — this is what
                # disqualifies derived sensors like Tibber's _average_power
                # (confidence 0.6) when the live _power sensor (1.0) exists
                # for the same device. Fall back to the existing zero/non-zero
                # heuristic when confidences match.
                current_id = entity_mapping.get(cap.value, "")
                current_conf = next(
                    (e.capability_confidence for e in entities if e.entity_id == current_id),
                    0.0,
                )
                if entity.capability_confidence > current_conf:
                    entity_mapping[cap.value] = entity.entity_id
                elif entity.capability_confidence == current_conf and self._entity_has_better_value(
                    entity, current_id, entities
                ):
                    entity_mapping[cap.value] = entity.entity_id

            # Track power entities for primary selection
            if cap == AmperaCapability.POWER:
                name_lower = entity.friendly_name.lower()
                eid_lower = entity.entity_id.lower()
                if any(kw in name_lower or kw in eid_lower for kw in ("consumption", "total")):
                    best_consumption_entity = entity.entity_id
                elif not best_power_entity:
                    best_power_entity = entity.entity_id

        # Select primary: consumption > power > first entity
        if best_consumption_entity:
            primary = best_consumption_entity
        elif best_power_entity:
            primary = best_power_entity
        elif entities:
            primary = entities[0].entity_id
        else:
            primary = ""

        return capabilities, entity_mapping, primary

    @staticmethod
    def _entity_has_better_value(
        candidate: DiscoveredEntity,
        current_entity_id: str,
        all_entities: list[DiscoveredEntity],
    ) -> bool:
        """Check if candidate has a better (non-zero) value than current."""
        try:
            candidate_val = float(candidate.state_value or "")
        except (ValueError, TypeError):
            return False
        if candidate_val == 0.0:
            return False
        # Candidate is non-zero; check if current reads zero
        for entity in all_entities:
            if entity.entity_id == current_entity_id:
                try:
                    current_val = float(entity.state_value or "")
                    return current_val == 0.0
                except (ValueError, TypeError):
                    return True
        return False

    # ------------------------------------------------------------------
    # Control-only device detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_control_only_device(entities: list[DiscoveredEntity]) -> bool:
        """Check if device is a control-only device (input helper).

        Returns True if the device contains ONLY switch/input_* entities
        AND entity names match known device type keywords.
        """
        has_sensors = False
        switch_entities: list[DiscoveredEntity] = []

        for entity in entities:
            if entity.domain == "sensor":
                has_sensors = True
                break
            if entity.domain in ("switch", "input_boolean", "input_number", "input_select"):
                switch_entities.append(entity)

        if has_sensors or not switch_entities:
            return False

        for entity in switch_entities:
            entity_name = entity.entity_id.split(".")[1].lower()
            friendly = entity.friendly_name.lower()
            search_text = f"{entity_name} {friendly}"
            if any(kw in search_text for kw in _CONTROL_KEYWORDS):
                return True

        return False

    # ------------------------------------------------------------------
    # Orphan entity handling
    # ------------------------------------------------------------------

    def _group_orphan_entities(
        self, orphan_entities: list[DiscoveredEntity]
    ) -> dict[str, list[DiscoveredEntity]]:
        """Group orphan entities by their detected type."""
        groups: dict[str, list[DiscoveredEntity]] = defaultdict(list)

        for entity in orphan_entities:
            if entity.capability is None:
                continue

            if entity.domain == "sensor":
                group_id = self._detect_orphan_type(entity)
            elif entity.domain == "water_heater":
                group_id = "virtual_water_heater"
            elif entity.domain == "climate":
                group_id = "virtual_climate"
            elif entity.domain == "switch":
                group_id = self._detect_orphan_switch_type(entity)
            else:
                group_id = f"orphan_{entity.entity_id}"

            groups[group_id].append(entity)

        return groups

    def _detect_orphan_type(self, entity: DiscoveredEntity) -> str:
        """Detect device type for an orphan sensor entity."""
        entity_name = entity.entity_id.split(".")[1].lower()
        friendly = entity.friendly_name.lower()

        # Tier 1: Integration platform
        if entity.platform:
            platform_lower = entity.platform.lower()
            device_type = KNOWN_INTEGRATIONS.get(platform_lower)
            if device_type is not None:
                return f"virtual_{device_type.value}"

        # Tier 2: Semantic signal matching
        search_text = f"{entity_name} {friendly}"
        best_type = None
        best_count = 0
        for device_type, signals in SEMANTIC_SIGNALS.items():
            count = sum(1 for sig in signals if sig in search_text)
            if count >= 2 and count > best_count:
                best_count = count
                best_type = device_type
        if best_type is not None:
            return f"virtual_{best_type.value}"

        # Tier 3: Keyword matching
        for device_type, kws in KEYWORDS.items():
            if any(kw in search_text for kw in kws):
                return f"virtual_{device_type.value}"

        # Domain-based fallback
        if entity.device_class in ("power", "energy", "voltage", "current"):
            return "virtual_power_meter"

        if entity.device_class == "temperature":
            wh_kws = KEYWORDS.get(AmperaDeviceType.WATER_HEATER, set())
            if any(kw in search_text for kw in wh_kws):
                return "virtual_water_heater"
            return f"orphan_{entity.entity_id}"

        return f"orphan_{entity.entity_id}"

    @staticmethod
    def _detect_orphan_switch_type(entity: DiscoveredEntity) -> str:
        """Detect device type for an orphan switch entity."""
        entity_name = entity.entity_id.split(".")[1].lower()
        friendly = entity.friendly_name.lower()
        search_text = f"{entity_name} {friendly}"

        # Check platform
        if entity.platform:
            platform_lower = entity.platform.lower()
            device_type = KNOWN_INTEGRATIONS.get(platform_lower)
            if device_type is not None:
                return f"virtual_{device_type.value}"

        # EV charger keywords
        ev_kws = {"ev", "charger", "lader", "elbil", "easee", "zaptec", "wallbox"}
        if any(kw in search_text for kw in ev_kws):
            return "virtual_ev_charger"

        # Water heater keywords
        wh_kws = {"water", "heater", "varmtvann", "bereder", "boiler", "hot_water"}
        if any(kw in search_text for kw in wh_kws):
            return "virtual_water_heater"

        return f"skip_{entity.entity_id}"

    def _build_orphan_device(
        self, group_id: str, entities: list[DiscoveredEntity]
    ) -> DiscoveredDevice | None:
        """Build a DiscoveredDevice from a group of orphan entities."""
        if not entities:
            return None

        capabilities, entity_mapping, primary_entity_id = self._map_capabilities(entities)
        if not capabilities:
            return None

        # Resolve type and name from group_id
        if group_id in _VIRTUAL_DEVICE_MAP:
            device_type, name = _VIRTUAL_DEVICE_MAP[group_id]
        elif group_id.startswith("virtual_switch_"):
            device_type = AmperaDeviceType.SWITCH
            name = group_id.replace("virtual_switch_", "").replace("_", " ").title()
        else:
            # Single orphan
            device_type = AmperaDeviceType.SENSOR
            name = entities[0].friendly_name or entities[0].entity_id

        device = DiscoveredDevice(
            ha_device_id=group_id,
            name=name,
            device_type=device_type,
            manufacturer=None,
            model=None,
            entities=entities,
            capabilities=capabilities,
            entity_mapping=entity_mapping,
            primary_entity_id=primary_entity_id,
            classification_reason=f"orphan: {device_type.value}",
        )
        device.is_energy_relevant = self._is_energy_relevant(device)
        device.is_recommended = self._is_recommended(device)
        return device

    # ------------------------------------------------------------------
    # Energy relevance & recommendation
    # ------------------------------------------------------------------

    @staticmethod
    def _is_energy_relevant(device: DiscoveredDevice) -> bool:
        """Return True if the device looks relevant to energy management.

        A device is considered non-energy when its name or any of its
        entity names contain a keyword from NON_ENERGY_KEYWORDS (camera,
        microphone, motion detection, notification, etc.) AND it has no
        energy/power capabilities to back it up. Devices with real power
        or energy capabilities always pass the filter, even if the name
        accidentally matches a non-energy keyword.

        Hard exclusion: any entity sourced from an integration in
        NON_ENERGY_INTEGRATIONS (HA add-ons, our own integration, security
        cameras, ...) is unconditionally non-energy, even if a capability
        accidentally matched. HA add-ons surface as switches from the
        ``hassio`` platform and should never appear in the energy picker.
        """
        for entity in device.entities:
            if entity.platform and entity.platform.lower() in NON_ENERGY_INTEGRATIONS:
                return False

        energy_caps = {
            AmperaCapability.POWER,
            AmperaCapability.POWER_L1,
            AmperaCapability.POWER_L2,
            AmperaCapability.POWER_L3,
            AmperaCapability.ENERGY,
            AmperaCapability.ENERGY_IMPORT,
            AmperaCapability.ENERGY_EXPORT,
            AmperaCapability.ENERGY_HOUR,
            AmperaCapability.ENERGY_DAY,
            AmperaCapability.ENERGY_MONTH,
            AmperaCapability.SESSION_ENERGY,
            AmperaCapability.PEAK_MONTH_1,
            AmperaCapability.PEAK_MONTH_2,
            AmperaCapability.PEAK_MONTH_3,
        }
        if any(cap in energy_caps for cap in device.capabilities):
            return True

        name_parts = [device.name.lower()]
        for entity in device.entities:
            name_parts.append(entity.friendly_name.lower())
            name_parts.append(entity.entity_id.lower())
        haystack = " ".join(name_parts)

        return not any(kw in haystack for kw in NON_ENERGY_KEYWORDS)

    @staticmethod
    def _is_recommended(device: DiscoveredDevice) -> bool:
        """Return True if the device should be pre-selected by default.

        We recommend pre-selecting devices that are unambiguously energy
        infrastructure: power meters (AMS, Tibber, Shelly, EM-style),
        EV chargers, and water heaters. Generic switches and sensors are
        excluded so users opt in deliberately.
        """
        if not device.is_energy_relevant:
            return False
        return device.device_type in {
            AmperaDeviceType.POWER_METER,
            AmperaDeviceType.EV_CHARGER,
            AmperaDeviceType.WATER_HEATER,
        }
