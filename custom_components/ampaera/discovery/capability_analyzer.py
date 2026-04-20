"""Stage 2: Capability analysis for discovered entities.

Examines each DiscoveredEntity and determines its Ampaera capability
based on domain, device_class, and name patterns. Pure Python - no
Home Assistant dependencies.
"""

from __future__ import annotations

import logging

from .models import (
    AmperaCapability,
    DiscoveredEntity,
    DiscoveryReport,
    UnmappedEntity,
)

_LOGGER = logging.getLogger(__name__)

# Domains where we expect to map capabilities
SUPPORTED_DOMAINS = {"sensor", "water_heater", "switch", "climate"}

# --- Name-pattern tables for energy sub-types ---

_ENERGY_HOUR_PATTERNS: tuple[str, ...] = (
    "hour_used",
    "hour used",
    "hourly_energy",
    "hourly energy",
    "hour_energy",
    "hour energy",
    "this_hour",
    "this hour",
    "current_hour",
    "current hour",
    "accumulated_hour",
    "accumulated hour",
    "denne time",
    "denne_time",
    "time brukt",
    "time_brukt",
)

_ENERGY_DAY_PATTERNS: tuple[str, ...] = (
    "day_used",
    "day used",
    "daily_energy",
    "daily energy",
    "day_energy",
    "day energy",
    "today",
    "this_day",
    "this day",
    "current_day",
    "current day",
    "accumulated_day",
    "accumulated day",
    "i dag",
    "i_dag",
    "dag brukt",
    "dag_brukt",
    "daglig",
    "daily",
)

_ENERGY_MONTH_PATTERNS: tuple[str, ...] = (
    "month_used",
    "month used",
    "monthly_energy",
    "monthly energy",
    "month_energy",
    "month energy",
    "this_month",
    "this month",
    "current_month",
    "current month",
    "accumulated_month",
    "accumulated month",
    "denne m",
    "maaned",
    "måned",
    "monthly",
    "month_consumption",
    "month consumption",
)

_PEAK_1_PATTERNS: tuple[str, ...] = (
    "peak 1",
    "peak_1",
    "topp 1",
    "topp_1",
    "current month peak 1",
    "current_month_peak_1",
)

_PEAK_2_PATTERNS: tuple[str, ...] = (
    "peak 2",
    "peak_2",
    "topp 2",
    "topp_2",
    "current month peak 2",
    "current_month_peak_2",
)

_PEAK_3_PATTERNS: tuple[str, ...] = (
    "peak 3",
    "peak_3",
    "topp 3",
    "topp_3",
    "current month peak 3",
    "current_month_peak_3",
)

_COST_DAY_PATTERNS: tuple[str, ...] = (
    "day cost",
    "day_cost",
    "today",
    "current day",
    "dagens kostnad",
    "dagskostnad",
    "dagens_kostnad",
)

_ENERGY_SKIP_PATTERNS: frozenset[str] = frozenset({"max"})


class CapabilityAnalyzer:
    """Stage 2: Analyze entities and determine their Ampaera capabilities."""

    def analyze(
        self,
        entities: list[DiscoveredEntity],
        report: DiscoveryReport,
    ) -> list[DiscoveredEntity]:
        """Set capability on each entity based on device_class and name patterns.

        Modifies entities in place and returns the same list.
        Updates report with capability statistics.
        """
        with_cap = 0
        without_cap = 0
        cap_dist: dict[str, int] = {}

        for entity in entities:
            capability, confidence = self._analyze(entity)
            entity.capability = capability
            entity.capability_confidence = confidence

            if capability is not None:
                with_cap += 1
                cap_dist[capability.value] = cap_dist.get(capability.value, 0) + 1
            elif entity.domain in SUPPORTED_DOMAINS:
                without_cap += 1
                if entity.device_class is not None:
                    report.unmapped_entities.append(
                        UnmappedEntity(
                            entity_id=entity.entity_id,
                            device_class=entity.device_class,
                            reason=f"No capability mapping for device_class={entity.device_class}",
                        )
                    )

        report.entities_with_capability = with_cap
        report.entities_without_capability = without_cap
        report.capability_distribution = cap_dist

        return entities

    # ------------------------------------------------------------------
    # Internal analysis
    # ------------------------------------------------------------------

    def _analyze(self, entity: DiscoveredEntity) -> tuple[AmperaCapability | None, float]:
        """Return (capability, confidence) for a single entity."""
        domain = entity.domain

        if domain not in SUPPORTED_DOMAINS:
            return None, 0.0

        if domain == "sensor":
            return self._analyze_sensor(entity)
        if domain == "water_heater":
            return AmperaCapability.TEMPERATURE, 1.0
        if domain == "switch":
            return AmperaCapability.ON_OFF, 1.0
        if domain == "climate":
            return AmperaCapability.TEMPERATURE, 1.0

        return None, 0.0

    def _analyze_sensor(self, entity: DiscoveredEntity) -> tuple[AmperaCapability | None, float]:
        """Analyze a sensor entity."""
        device_class = entity.device_class
        if device_class is None:
            return None, 0.0

        friendly_name = (entity.friendly_name or entity.entity_id).lower()
        entity_name = (
            entity.entity_id.split(".")[1].lower()
            if "." in entity.entity_id
            else entity.entity_id.lower()
        )

        if device_class == "power":
            return self._analyze_power(friendly_name), 1.0

        if device_class == "energy":
            return self._analyze_energy(friendly_name, entity_name, entity.entity_id)

        if device_class == "voltage":
            return (
                self._analyze_phase(
                    friendly_name,
                    AmperaCapability.VOLTAGE_L1,
                    AmperaCapability.VOLTAGE_L2,
                    AmperaCapability.VOLTAGE_L3,
                    AmperaCapability.VOLTAGE,
                ),
                1.0,
            )

        if device_class == "current":
            return (
                self._analyze_phase(
                    friendly_name,
                    AmperaCapability.CURRENT_L1,
                    AmperaCapability.CURRENT_L2,
                    AmperaCapability.CURRENT_L3,
                    AmperaCapability.CURRENT,
                ),
                1.0,
            )

        if device_class == "temperature":
            return AmperaCapability.TEMPERATURE, 1.0

        if device_class == "monetary":
            if _matches_any(friendly_name, entity_name, _COST_DAY_PATTERNS):
                return AmperaCapability.COST_DAY, 0.8
            return None, 0.0

        return None, 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_power(friendly_name: str) -> AmperaCapability:
        if "l1" in friendly_name or "phase 1" in friendly_name:
            return AmperaCapability.POWER_L1
        if "l2" in friendly_name or "phase 2" in friendly_name:
            return AmperaCapability.POWER_L2
        if "l3" in friendly_name or "phase 3" in friendly_name:
            return AmperaCapability.POWER_L3
        return AmperaCapability.POWER

    @staticmethod
    def _analyze_phase(
        friendly_name: str,
        l1: AmperaCapability,
        l2: AmperaCapability,
        l3: AmperaCapability,
        generic: AmperaCapability,
    ) -> AmperaCapability:
        if "l1" in friendly_name or "phase 1" in friendly_name:
            return l1
        if "l2" in friendly_name or "phase 2" in friendly_name:
            return l2
        if "l3" in friendly_name or "phase 3" in friendly_name:
            return l3
        return generic

    @staticmethod
    def _analyze_energy(
        friendly_name: str, entity_name: str, entity_id: str
    ) -> tuple[AmperaCapability | None, float]:
        # Export/import/session first
        if "export" in friendly_name:
            return AmperaCapability.ENERGY_EXPORT, 1.0
        if "import" in friendly_name or "tpi" in entity_name:
            return AmperaCapability.ENERGY_IMPORT, 1.0
        if "session" in friendly_name:
            return AmperaCapability.SESSION_ENERGY, 1.0

        # Peak demand registers - check BEFORE period registers because
        # patterns like "current month peak 1" would otherwise match month
        if _matches_any(friendly_name, entity_name, _PEAK_1_PATTERNS):
            return AmperaCapability.PEAK_MONTH_1, 0.8
        if _matches_any(friendly_name, entity_name, _PEAK_2_PATTERNS):
            return AmperaCapability.PEAK_MONTH_2, 0.8
        if _matches_any(friendly_name, entity_name, _PEAK_3_PATTERNS):
            return AmperaCapability.PEAK_MONTH_3, 0.8

        # Period registers (hour/day/month)
        if _matches_any(friendly_name, entity_name, _ENERGY_HOUR_PATTERNS):
            return AmperaCapability.ENERGY_HOUR, 0.8
        if _matches_any(friendly_name, entity_name, _ENERGY_DAY_PATTERNS):
            return AmperaCapability.ENERGY_DAY, 0.8
        if _matches_any(friendly_name, entity_name, _ENERGY_MONTH_PATTERNS):
            return AmperaCapability.ENERGY_MONTH, 0.8

        # Skip non-cumulative energy sensors
        if any(p in friendly_name or p in entity_name for p in _ENERGY_SKIP_PATTERNS):
            _LOGGER.debug(
                "Skipping non-cumulative energy sensor: %s (likely max demand)",
                entity_id,
            )
            return None, 0.0

        # Generic energy
        return AmperaCapability.ENERGY, 1.0


def _matches_any(friendly_name: str, entity_name: str, patterns: tuple[str, ...]) -> bool:
    """Return True if any pattern matches friendly_name or entity_name."""
    return any(p in friendly_name or p in entity_name for p in patterns)
