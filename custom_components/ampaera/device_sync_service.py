"""Device sync service for Ampæra HA integration.

Periodically syncs the device list from Home Assistant to Ampæra,
keeping devices in sync as they are added, removed, or changed in HA.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DEFAULT_DEVICE_SYNC_INTERVAL
from .device_discovery import AmperaDeviceDiscovery

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .api import AmperaApiClient

_LOGGER = logging.getLogger(__name__)


class AmperaDeviceSyncService:
    """Periodically sync HA devices to Ampæra.

    This service:
    - Discovers devices in Home Assistant using AmperaDeviceDiscovery
    - Syncs them to Ampæra via the /ha/devices/sync endpoint
    - Keeps device_mappings updated for telemetry push
    - Runs periodically and on HA startup/reload
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api_client: AmperaApiClient,
        site_id: str,
        selected_entities: list[str],
        sync_interval: int = DEFAULT_DEVICE_SYNC_INTERVAL,
    ) -> None:
        """Initialize the device sync service.

        Args:
            hass: Home Assistant instance
            entry: Config entry (for updating device_mappings)
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            selected_entities: List of entity IDs selected for sync
            sync_interval: Seconds between sync cycles (default: 5 minutes)
        """
        self._hass = hass
        self._entry = entry
        self._api = api_client
        self._site_id = site_id
        self._selected_entities = set(selected_entities)
        self._sync_interval = sync_interval
        self._discovery = AmperaDeviceDiscovery(hass)
        self._unsub_timer: asyncio.TimerHandle | None = None
        self._running = False
        self._device_mappings: dict[str, str] = {}

    @property
    def device_mappings(self) -> dict[str, str]:
        """Return current device mappings (ha_entity_id -> ampera_device_id)."""
        return self._device_mappings

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
            "Device sync service started (interval: %ds, %d entities selected)",
            self._sync_interval,
            len(self._selected_entities),
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

    @callback
    def _sync_devices_callback(self, _now: Event | None = None) -> None:
        """Callback for scheduled sync (wraps async method)."""
        self._hass.async_create_task(self._sync_devices())

    async def _sync_devices(self) -> None:
        """Sync devices to Ampæra.

        Discovers current devices, filters by selected entities,
        and syncs to Ampæra backend.
        """
        if not self._running:
            return

        try:
            # Discover all devices
            all_devices = self._discovery.discover_devices()

            # Filter to selected entities only
            selected_devices = [
                d for d in all_devices if d.entity_id in self._selected_entities
            ]

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

            # Update device mappings
            new_mappings = result.get("device_mappings", {})
            if new_mappings:
                self._device_mappings = new_mappings

                # Update config entry data with new mappings
                # This ensures push_service and command_service have current mappings
                new_data = {**self._entry.data, "device_mappings": new_mappings}
                self._hass.config_entries.async_update_entry(
                    self._entry, data=new_data
                )

            created = result.get("created", 0)
            updated = result.get("updated", 0)
            removed = result.get("removed", 0)

            if created or removed:
                _LOGGER.info(
                    "Device sync complete: created=%d, updated=%d, removed=%d",
                    created,
                    updated,
                    removed,
                )
            else:
                _LOGGER.debug(
                    "Device sync complete: created=%d, updated=%d, removed=%d",
                    created,
                    updated,
                    removed,
                )

        except Exception as err:
            _LOGGER.error("Device sync failed: %s", err)

    async def async_force_sync(self) -> dict[str, str]:
        """Force an immediate device sync.

        Returns:
            Updated device mappings dict
        """
        await self._sync_devices()
        return self._device_mappings
