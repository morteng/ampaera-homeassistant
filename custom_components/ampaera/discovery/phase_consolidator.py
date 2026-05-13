"""Stage 4: Merge phase-split sibling HA devices onto their parent.

Tibber's HA integration models a single 3-phase Pulse meter as multiple
HA devices: a parent meter (carrying power/energy/voltage_l1) plus one
or more phase-child devices (each carrying a single voltage entity for
L2/L3). Without consolidation, each child becomes its own Ampæra device
and its voltage readings get dropped on ingestion (no power_w → fails
the ingestion gate in :mod:`app.api.v1.ha_integration`).

This stage detects phase-child siblings and merges their entities,
capabilities, and entity_mapping onto the parent power meter. The
children are dropped from the output; the orchestrator then ships a
single Ampæra device per physical meter, and the orphan rows in
PostgreSQL get soft-deleted by the existing missing-device handling in
``sync_devices`` within one or two sync cycles.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Protocol

from .models import (
    AmperaCapability,
    AmperaDeviceType,
    DiscoveredDevice,
    DiscoveryReport,
    PhaseConsolidationDetail,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


_VOLTAGE_CAPS: frozenset[AmperaCapability] = frozenset(
    {
        AmperaCapability.VOLTAGE,
        AmperaCapability.VOLTAGE_L1,
        AmperaCapability.VOLTAGE_L2,
        AmperaCapability.VOLTAGE_L3,
    }
)

_DISQUALIFYING_CAPS: frozenset[AmperaCapability] = frozenset(
    {
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
        AmperaCapability.CURRENT,
        AmperaCapability.CURRENT_L1,
        AmperaCapability.CURRENT_L2,
        AmperaCapability.CURRENT_L3,
    }
)

# Matches a trailing phase suffix on a device name. Accepts space, underscore,
# or dash separators (or none) and is case-insensitive. Examples that match:
# "Tibber Pulse Phase2", "tibber-pulse-phase_3", "Pulse PHASE 1".
_NAME_SUFFIX_PATTERN = re.compile(r"[\s_\-]?phase[\s_\-]?([123])\s*$", re.IGNORECASE)


class _DeviceRegistryLike(Protocol):
    """Minimal interface we need from homeassistant.helpers.device_registry.DeviceRegistry."""

    def async_get(self, device_id: str):  # noqa: ANN201 - duck-typed
        ...


class PhaseConsolidator:
    """Pipeline stage 4 — merge phase-child HA devices onto their parent.

    See module docstring for the motivating problem.
    """

    def consolidate(
        self,
        devices: list[DiscoveredDevice],
        device_registry: _DeviceRegistryLike | None,
        report: DiscoveryReport,
    ) -> list[DiscoveredDevice]:
        """Return ``devices`` with phase-children merged into their parents.

        Pure passthrough when no phase children are detected.
        """
        if not devices:
            return devices

        by_id = {d.ha_device_id: d for d in devices}
        candidates = [d for d in devices if self._is_phase_child(d)]
        if not candidates:
            return devices

        # parent_id -> (parent_device, list[(child, signal)])
        merges: dict[str, tuple[DiscoveredDevice, list[tuple[DiscoveredDevice, str]]]] = {}

        for child in candidates:
            parent, signal = self._find_parent(child, by_id, device_registry)
            if parent is None:
                continue
            if parent.device_type != AmperaDeviceType.POWER_METER:
                _LOGGER.debug(
                    "Skip phase consolidation: parent %s is %s, not POWER_METER",
                    parent.ha_device_id,
                    parent.device_type.value,
                )
                continue
            slot = merges.setdefault(parent.ha_device_id, (parent, []))
            slot[1].append((child, signal))

        if not merges:
            return devices

        merged_child_ids: set[str] = set()
        for parent_id, (parent, child_pairs) in merges.items():
            children = [c for c, _ in child_pairs]
            signals = {s for _, s in child_pairs}
            # Prefer via_device_id over name_suffix when both contributed.
            signal: str = "via_device_id" if "via_device_id" in signals else "name_suffix"

            self._merge_into_parent(parent, children)
            merged_child_ids.update(c.ha_device_id for c in children)
            caps_merged = sorted(
                {
                    cap.value
                    for child in children
                    for cap in child.capabilities
                    if cap in _VOLTAGE_CAPS
                }
            )
            _LOGGER.info(
                "phase_consolidation parent=%s children=%s signal=%s caps_merged=%s",
                parent_id,
                [c.ha_device_id for c in children],
                signal,
                caps_merged,
            )
            report.phases_consolidated += len(children)
            report.consolidation_details.append(
                PhaseConsolidationDetail(
                    parent_id=parent_id,
                    child_ids=[c.ha_device_id for c in children],
                    signal=signal,  # type: ignore[arg-type]
                )
            )

        return [d for d in devices if d.ha_device_id not in merged_child_ids]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_phase_child(device: DiscoveredDevice) -> bool:
        """A phase child has only voltage capabilities (no power/energy/current)."""
        caps = set(device.capabilities)
        if not caps:
            return False
        if caps & _DISQUALIFYING_CAPS:
            return False
        return bool(caps & _VOLTAGE_CAPS)

    def _find_parent(
        self,
        child: DiscoveredDevice,
        by_id: dict[str, DiscoveredDevice],
        device_registry: _DeviceRegistryLike | None,
    ) -> tuple[DiscoveredDevice | None, str]:
        """Return (parent, signal_used). signal is 'via_device_id' or 'name_suffix'."""
        # 1) Primary signal: via_device_id from HA's device registry.
        if device_registry is not None:
            entry = device_registry.async_get(child.ha_device_id)
            via = getattr(entry, "via_device_id", None) if entry else None
            if via:
                parent = by_id.get(via)
                # If by_id doesn't have the parent (e.g. it was filtered out
                # earlier in the pipeline), fall through to name-suffix.
                if parent is not None and parent.ha_device_id != child.ha_device_id:
                    return parent, "via_device_id"

        # 2) Fallback: strip the phaseN suffix from the child name and find
        # a sibling device whose name matches the prefix.
        prefix = _strip_phase_suffix(child.name)
        if not prefix:
            return None, ""
        for candidate in by_id.values():
            if candidate.ha_device_id == child.ha_device_id:
                continue
            if candidate.name == prefix:
                return candidate, "name_suffix"
        return None, ""

    @staticmethod
    def _merge_into_parent(parent: DiscoveredDevice, children: list[DiscoveredDevice]) -> None:
        existing_caps = set(parent.capabilities)
        for child in children:
            for entity in child.entities:
                if entity.entity_id not in {e.entity_id for e in parent.entities}:
                    parent.entities.append(entity)
            for cap in child.capabilities:
                if cap not in existing_caps:
                    parent.capabilities.append(cap)
                    existing_caps.add(cap)
            for cap_value, entity_id in child.entity_mapping.items():
                parent.entity_mapping.setdefault(cap_value, entity_id)


def _strip_phase_suffix(name: str) -> str | None:
    """Return ``name`` minus its trailing ``phaseN`` suffix, or None if absent."""
    match = _NAME_SUFFIX_PATTERN.search(name)
    if not match:
        return None
    stripped = name[: match.start()].rstrip(" _-")
    return stripped or None
