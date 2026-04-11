"""Stage 1: Entity scanner for the Ampæra discovery pipeline.

Scans the Home Assistant entity registry to find ALL relevant entities,
including disabled ones, and returns a list of DiscoveredEntity objects.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .models import DiscoveredEntity, DiscoveryReport, ExcludedEntity
from .signatures import EXCLUDED_INTEGRATIONS, SUPPORTED_DOMAINS

_LOGGER = logging.getLogger(__name__)


class EntityScanner:
    """Stage 1: Scan HA entity registry for all relevant entities."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def scan(self, report: DiscoveryReport) -> list[DiscoveredEntity]:
        """Scan entity registry and return all relevant entities.

        Uses entity registry (not hass.states) to find ALL entities including
        disabled ones. For enabled entities, reads current state value.
        For disabled entities, sets state_value=None.

        Updates report with scan statistics.
        """
        entity_registry = er.async_get(self._hass)
        active_states = {s.entity_id: s for s in self._hass.states.async_all()}

        discovered: list[DiscoveredEntity] = []
        enabled_count = 0
        disabled_count = 0
        excluded_count = 0
        entities_by_domain: dict[str, int] = {}
        entities_by_platform: dict[str, int] = {}

        for entry in entity_registry.entities.values():
            entity_id = entry.entity_id
            domain = entity_id.split(".")[0]

            # Skip unsupported domains
            if domain not in SUPPORTED_DOMAINS:
                report.excluded_entities.append(
                    ExcludedEntity(
                        entity_id=entity_id,
                        reason=f"unsupported domain: {domain}",
                    )
                )
                excluded_count += 1
                continue

            # Skip excluded integrations
            if entry.platform and entry.platform.lower() in EXCLUDED_INTEGRATIONS:
                report.excluded_entities.append(
                    ExcludedEntity(
                        entity_id=entity_id,
                        reason=f"excluded integration: {entry.platform}",
                    )
                )
                excluded_count += 1
                continue

            if entity_id in active_states:
                # Entity is enabled and has a state
                state = active_states[entity_id]
                device_class = state.attributes.get("device_class")
                friendly_name = state.attributes.get(
                    "friendly_name", entity_id
                )
                unit = state.attributes.get("unit_of_measurement")
                state_value = state.state
                enabled = True
                disabled_by = None
                enabled_count += 1
            elif entry.disabled_by is not None:
                # Entity is disabled — use registry metadata
                device_class = entry.device_class
                friendly_name = entry.original_name or entry.name or entity_id
                unit = entry.unit_of_measurement
                state_value = None
                enabled = False
                disabled_by = str(entry.disabled_by)
                disabled_count += 1
            else:
                # Entity is in registry but has no state and is not disabled
                # (e.g., integration not loaded yet). Skip it.
                continue

            entity = DiscoveredEntity(
                entity_id=entity_id,
                domain=domain,
                device_id=entry.device_id,
                platform=entry.platform,
                device_class=device_class,
                friendly_name=friendly_name,
                unit=unit,
                enabled=enabled,
                disabled_by=disabled_by,
                state_value=state_value,
            )
            discovered.append(entity)

            # Track domain and platform counts
            entities_by_domain[domain] = entities_by_domain.get(domain, 0) + 1
            if entry.platform:
                entities_by_platform[entry.platform] = (
                    entities_by_platform.get(entry.platform, 0) + 1
                )

        # Update report
        report.total_entities_scanned = len(discovered)
        report.enabled_entities = enabled_count
        report.disabled_entities = disabled_count
        report.entities_by_domain = entities_by_domain
        report.entities_by_platform = entities_by_platform

        if disabled_count > 0:
            _LOGGER.info(
                "Entity scan: %d enabled, %d disabled (total %d relevant entities)",
                enabled_count,
                disabled_count,
                len(discovered),
            )

        return discovered
