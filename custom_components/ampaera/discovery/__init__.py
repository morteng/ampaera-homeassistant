"""Discovery pipeline for Ampæra HA integration."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr

from .capability_analyzer import CapabilityAnalyzer
from .channel_splitter import ChannelSplitter
from .device_classifier import DeviceClassifier
from .entity_scanner import EntityScanner
from .models import (
    AmperaCapability,
    AmperaDeviceType,
    DiscoveredDevice,
    DiscoveredEntity,
    DiscoveryReport,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Re-export public API for backward compatibility
__all__ = [
    "AmperaCapability",
    "AmperaDeviceType",
    "DiscoveredDevice",
    "DiscoveredEntity",
    "DiscoveryOrchestrator",
    "DiscoveryReport",
]


class DiscoveryOrchestrator:
    """Run the full discovery pipeline and collect diagnostics."""

    def __init__(self, hass: HomeAssistant, simulation_mode: bool = False) -> None:
        self._hass = hass
        self._scanner = EntityScanner(hass)
        self._analyzer = CapabilityAnalyzer()
        self._classifier = DeviceClassifier(simulation_mode=simulation_mode)
        self._splitter = ChannelSplitter()
        self._report: DiscoveryReport | None = None

    def discover(self) -> tuple[list[DiscoveredDevice], DiscoveryReport]:
        """Run the full discovery pipeline."""
        report = DiscoveryReport()
        report.timestamp = datetime.now(UTC)
        start = time.monotonic()

        # Stage 1: Scan entities
        entities = self._scanner.scan(report)
        _LOGGER.info(
            "Stage 1 (scan): %d entities found (%d enabled, %d disabled)",
            report.total_entities_scanned,
            report.enabled_entities,
            report.disabled_entities,
        )

        # Stage 2: Analyze capabilities
        self._analyzer.analyze(entities, report)
        _LOGGER.info(
            "Stage 2 (analyze): %d with capability, %d without",
            report.entities_with_capability,
            report.entities_without_capability,
        )

        # Stage 3: Classify devices
        device_info = self._build_device_info(entities)
        devices = self._classifier.classify(entities, device_info, report)
        _LOGGER.info("Stage 3 (classify): %d devices found", report.devices_found)

        # Stage 4: Split channels
        devices = self._splitter.split(devices, report)
        if report.channel_splits_performed:
            _LOGGER.info(
                "Stage 4 (split): %d devices split into channels",
                report.channel_splits_performed,
            )

        report.duration_ms = (time.monotonic() - start) * 1000
        self._report = report

        _LOGGER.info(
            "Discovery pipeline complete in %.0fms: %d devices",
            report.duration_ms,
            len(devices),
        )
        return devices, report

    @property
    def last_report(self) -> DiscoveryReport | None:
        """Return the report from the last discovery run."""
        return self._report

    def _build_device_info(
        self, entities: list[DiscoveredEntity]
    ) -> dict[str, tuple[str | None, str | None, str | None]]:
        """Build device info dict from HA device registry."""
        device_registry = dr.async_get(self._hass)
        device_ids = {e.device_id for e in entities if e.device_id}
        info: dict[str, tuple[str | None, str | None, str | None]] = {}

        for dev_id in device_ids:
            # Handle synthetic channel IDs
            lookup_id = ChannelSplitter._resolve_base_device_id(dev_id)
            entry = device_registry.async_get(lookup_id)
            if entry:
                name = entry.name_by_user or entry.name
                info[dev_id] = (name, entry.manufacturer, entry.model)
            else:
                info[dev_id] = (None, None, None)

        return info
