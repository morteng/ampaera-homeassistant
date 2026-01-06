"""Device sync service for Ampæra HA integration.

Periodically syncs the device list from Home Assistant to Ampæra,
keeping devices in sync as they are added, removed, or changed in HA.

Supports entity-to-device mapping where multiple HA entities
(sensors) are grouped under a single parent device.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DEFAULT_DEVICE_SYNC_INTERVAL
from .device_discovery import AmperaDeviceDiscovery, DiscoveredDevice
from .push_service import EntityMapping

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .api import AmperaApiClient

# Type alias for sync callback
SyncCallback = Callable[[dict[str, str], dict[str, EntityMapping]], None]

_LOGGER = logging.getLogger(__name__)


class AmperaDeviceSyncService:
    """Periodically sync HA devices to Ampæra.

    This service:
    - Discovers devices in Home Assistant using AmperaDeviceDiscovery
    - Groups entities by parent device_id from HA device registry
    - Syncs them to Ampæra via the /ha/devices/sync endpoint
    - Keeps entity_mappings updated for telemetry push
    - Runs periodically and on HA startup/reload
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api_client: AmperaApiClient,
        site_id: str,
        selected_device_ids: list[str],
        sync_interval: int = DEFAULT_DEVICE_SYNC_INTERVAL,
    ) -> None:
        """Initialize the device sync service.

        Args:
            hass: Home Assistant instance
            entry: Config entry (for updating device_mappings)
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            selected_device_ids: List of HA device IDs selected for sync
            sync_interval: Seconds between sync cycles (default: 5 minutes)
        """
        self._hass = hass
        self._entry = entry
        self._api = api_client
        self._site_id = site_id
        self._selected_device_ids = set(selected_device_ids)
        self._sync_interval = sync_interval
        self._discovery = AmperaDeviceDiscovery(hass)
        self._unsub_timer: asyncio.TimerHandle | None = None
        self._running = False
        # Maps ha_device_id → ampera_device_id
        self._device_id_mappings: dict[str, str] = {}
        # Maps entity_id → EntityMapping (for push service)
        self._entity_mappings: dict[str, EntityMapping] = {}
        # Callbacks to invoke after each sync
        self._sync_callbacks: list[SyncCallback] = []

    @property
    def device_id_mappings(self) -> dict[str, str]:
        """Return current device ID mappings (ha_device_id -> ampera_device_id)."""
        return self._device_id_mappings

    @property
    def entity_mappings(self) -> dict[str, EntityMapping]:
        """Return entity mappings for telemetry push."""
        return self._entity_mappings

    def register_sync_callback(self, callback: SyncCallback) -> None:
        """Register a callback to be called after each sync.

        The callback receives (device_id_mappings, entity_mappings).
        """
        self._sync_callbacks.append(callback)

    async def async_start(self) -> None:
        """Start the device sync service.

        Performs initial sync and schedules periodic sync.
        """
        if self._running:
            return

        self._running = True

        # Perform initial sync
        await self._sync_devices()

        # Schedule periodic sync
        from datetime import timedelta

        self._unsub_timer = async_track_time_interval(
            self._hass,
            self._sync_devices_callback,
            timedelta(seconds=self._sync_interval),
        )

        _LOGGER.info(
            "Device sync service started (interval: %ds, %d devices selected)",
            self._sync_interval,
            len(self._selected_device_ids),
        )

    async def async_stop(self) -> None:
        """Stop the device sync service."""
        self._running = False

        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

        _LOGGER.info("Device sync service stopped")

    def set_sync_interval(self, interval: int) -> None:
        """Update the sync interval.

        Args:
            interval: New interval in seconds
        """
        if interval == self._sync_interval:
            return

        self._sync_interval = interval

        # Restart timer with new interval if running
        if self._running and self._unsub_timer:
            self._unsub_timer()
            from datetime import timedelta

            self._unsub_timer = async_track_time_interval(
                self._hass,
                self._sync_devices_callback,
                timedelta(seconds=self._sync_interval),
            )

        _LOGGER.debug("Device sync interval updated to %ds", interval)

    async def async_sync_now(self) -> None:
        """Trigger an immediate device sync (for service call)."""
        _LOGGER.info("Manual device sync triggered")
        # Temporarily set running to allow sync
        was_running = self._running
        self._running = True
        try:
            await self._sync_devices()
        finally:
            self._running = was_running

    @callback
    def _sync_devices_callback(self, _now: Event | None = None) -> None:
        """Callback for scheduled sync (wraps async method)."""
        self._hass.async_create_task(self._sync_devices())

    async def _sync_devices(self) -> None:
        """Sync devices to Ampæra.

        Discovers current devices, filters by selected device/entity IDs,
        and syncs to Ampæra backend. Updates entity mappings for push service.
        """
        if not self._running:
            return

        try:
            # Discover all devices (grouped by parent device_id)
            all_devices = self._discovery.discover_devices()

            # Filter to selected devices
            # Support both device IDs (new) and entity IDs (legacy config)
            selected_devices = self._filter_selected_devices(all_devices)

            if not selected_devices:
                _LOGGER.debug("No selected devices found for sync")
                return

            # Convert to API format
            devices_data = [d.to_dict() for d in selected_devices]

            # Sync to Ampæra
            result = await self._api.async_sync_devices(
                site_id=self._site_id,
                devices=devices_data,
            )

            # Update device ID mappings (ha_device_id → ampera_device_id)
            new_device_mappings = result.get("device_mappings", {})
            if new_device_mappings:
                self._device_id_mappings = new_device_mappings

                # Build entity mappings for push service
                self._entity_mappings = self._build_entity_mappings(
                    selected_devices, new_device_mappings
                )

                # Update config entry data with new mappings
                new_data = {**self._entry.data, "device_mappings": new_device_mappings}
                self._hass.config_entries.async_update_entry(self._entry, data=new_data)

            created = result.get("created", 0)
            updated = result.get("updated", 0)
            removed = result.get("removed", 0)

            if created or removed:
                _LOGGER.info(
                    "Device sync complete: created=%d, updated=%d, removed=%d, entities=%d",
                    created,
                    updated,
                    removed,
                    len(self._entity_mappings),
                )
            else:
                _LOGGER.debug(
                    "Device sync complete: created=%d, updated=%d, removed=%d",
                    created,
                    updated,
                    removed,
                )

            # Invoke sync callbacks to notify other services of updated mappings
            for cb in self._sync_callbacks:
                try:
                    cb(self._device_id_mappings, self._entity_mappings)
                except Exception as cb_err:
                    _LOGGER.warning("Sync callback error: %s", cb_err)

        except Exception as err:
            _LOGGER.error("Device sync failed: %s", err)

    def _filter_selected_devices(
        self, all_devices: list[DiscoveredDevice]
    ) -> list[DiscoveredDevice]:
        """Filter devices to only those selected by user.

        Supports both:
        - Device IDs (ha_device_id): New configs with device grouping
        - Entity IDs (sensor.xxx): Legacy configs before device grouping

        Args:
            all_devices: All discovered devices

        Returns:
            List of devices that match the selection
        """
        if not self._selected_device_ids:
            return []

        selected_devices: list[DiscoveredDevice] = []

        for device in all_devices:
            # Check 1: Direct match on ha_device_id (new device-based selection)
            if device.ha_device_id in self._selected_device_ids:
                selected_devices.append(device)
                continue

            # Check 2: Match on primary_entity_id (legacy entity-based selection)
            if device.primary_entity_id in self._selected_device_ids:
                selected_devices.append(device)
                continue

            # Check 3: Any entity in entity_mapping matches (legacy with grouped entities)
            if any(
                entity_id in self._selected_device_ids
                for entity_id in device.entity_mapping.values()
            ):
                selected_devices.append(device)
                continue

        _LOGGER.debug(
            "Filtered %d devices from %d total (selection has %d items)",
            len(selected_devices),
            len(all_devices),
            len(self._selected_device_ids),
        )

        return selected_devices

    def _build_entity_mappings(
        self,
        devices: list[DiscoveredDevice],
        device_id_mappings: dict[str, str],
    ) -> dict[str, EntityMapping]:
        """Build entity mappings from discovered devices.

        Args:
            devices: List of discovered devices with entity_mapping
            device_id_mappings: Mapping of ha_device_id → ampera_device_id

        Returns:
            Dict of entity_id → EntityMapping for push service
        """
        entity_mappings: dict[str, EntityMapping] = {}

        for device in devices:
            ampera_device_id = device_id_mappings.get(device.ha_device_id)
            if not ampera_device_id:
                continue

            # Create EntityMapping for each entity in the device
            for capability, entity_id in device.entity_mapping.items():
                entity_mappings[entity_id] = EntityMapping(
                    device_id=ampera_device_id,
                    capability=capability,
                    ha_device_id=device.ha_device_id,
                )

        return entity_mappings

    async def async_force_sync(self) -> tuple[dict[str, str], dict[str, EntityMapping]]:
        """Force an immediate device sync.

        Returns:
            Tuple of (device_id_mappings, entity_mappings)
        """
        await self._sync_devices()
        return self._device_id_mappings, self._entity_mappings
