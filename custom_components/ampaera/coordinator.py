"""DataUpdateCoordinator for Ampæra Energy integration.

Manages periodic data fetching from the Ampæra API and provides
a centralized data source for all entities.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    AmperaApiClient,
    AmperaApiError,
    AmperaAuthError,
    AmperaConnectionError,
)
from .const import DEFAULT_POLLING_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AmperaDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for fetching Ampæra site data.

    Fetches:
    - Site information (name, region, etc.)
    - Current telemetry (power, voltage, current)
    - Device list with states
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: AmperaApiClient,
        site_id: str,
        site_name: str,
        polling_interval: int = DEFAULT_POLLING_INTERVAL,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            api: Ampæra API client
            site_id: Site UUID to fetch data for
            site_name: Human-readable site name
            polling_interval: Update interval in seconds
        """
        self.api = api
        self.site_id = site_id
        self.site_name = site_name

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{site_id}",
            update_interval=timedelta(seconds=polling_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Ampæra API.

        Returns:
            Dictionary with site, telemetry, and devices data

        Raises:
            ConfigEntryAuthFailed: If authentication fails
            UpdateFailed: If data cannot be fetched
        """
        try:
            # Fetch all data in parallel would be ideal, but sequential is safer
            site = await self.api.async_get_site(self.site_id)
            telemetry = await self.api.async_get_telemetry(self.site_id)
            devices = await self.api.async_get_devices(self.site_id)

            return {
                "site": site,
                "telemetry": telemetry,
                "devices": devices,
            }

        except AmperaAuthError as err:
            # Trigger reauthentication flow
            raise ConfigEntryAuthFailed(str(err)) from err

        except AmperaConnectionError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        except AmperaApiError as err:
            raise UpdateFailed(f"API error: {err}") from err

    @property
    def site_data(self) -> dict[str, Any]:
        """Get site information."""
        return self.data.get("site", {}) if self.data else {}

    @property
    def telemetry_data(self) -> dict[str, Any]:
        """Get current telemetry data."""
        return self.data.get("telemetry", {}) if self.data else {}

    @property
    def devices_data(self) -> list[dict[str, Any]]:
        """Get list of devices."""
        return self.data.get("devices", []) if self.data else []

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Get a specific device by ID."""
        for device in self.devices_data:
            if device.get("device_id") == device_id or device.get("id") == device_id:
                return device
        return None
