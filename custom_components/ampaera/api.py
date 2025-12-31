"""Ampæra API client for Home Assistant integration.

This module provides an async HTTP client for communicating with the
Ampæra Smart Home Energy Management Platform API.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiolimiter import AsyncLimiter

from .const import DEFAULT_API_BASE_URL

_LOGGER = logging.getLogger(__name__)

# Rate limiting: 60 requests per minute (1 per second average)
DEFAULT_RATE_LIMIT = 60
DEFAULT_RATE_PERIOD = 60.0


class AmperaApiError(Exception):
    """Base exception for Ampæra API errors."""


class AmperaAuthError(AmperaApiError):
    """Authentication error (401/403)."""


class AmperaConnectionError(AmperaApiError):
    """Connection error (network issues, timeouts)."""


class AmperaServerError(AmperaApiError):
    """Server error (5xx responses)."""


class AmperaApiClient:
    """Async client for Ampæra API.

    Handles authentication, rate limiting, and HTTP communication
    with the Ampæra backend API.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_API_BASE_URL,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            api_key: API token for authentication (amp_sk_live_...)
            base_url: Base URL for the API (default: https://api.ampaera.no)
            session: Optional aiohttp session (creates one if not provided)
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None
        self._limiter = AsyncLimiter(DEFAULT_RATE_LIMIT, DEFAULT_RATE_PERIOD)

    @property
    def _headers(self) -> dict[str, str]:
        """Get default headers for API requests."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AmperaHomeAssistant/0.1.0",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the API client session."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make an API request with rate limiting and error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/api/v1/sites")
            data: Request body for POST/PUT/PATCH
            params: Query parameters

        Returns:
            Parsed JSON response

        Raises:
            AmperaAuthError: On 401/403 responses
            AmperaServerError: On 5xx responses
            AmperaConnectionError: On network errors
            AmperaApiError: On other errors
        """
        url = f"{self._base_url}{path}"

        async with self._limiter:
            session = await self._get_session()

            try:
                async with session.request(
                    method,
                    url,
                    headers=self._headers,
                    json=data,
                    params=params,
                ) as response:
                    _LOGGER.debug(
                        "API %s %s -> %s", method, path, response.status
                    )

                    if response.status == 401:
                        raise AmperaAuthError("Invalid or expired API token")

                    if response.status == 403:
                        raise AmperaAuthError("Access forbidden - insufficient permissions")

                    if response.status == 404:
                        raise AmperaApiError(f"Resource not found: {path}")

                    if response.status >= 500:
                        text = await response.text()
                        raise AmperaServerError(
                            f"Server error {response.status}: {text[:200]}"
                        )

                    if response.status >= 400:
                        text = await response.text()
                        raise AmperaApiError(
                            f"API error {response.status}: {text[:200]}"
                        )

                    # Handle empty responses (204 No Content)
                    if response.status == 204:
                        return {}

                    return await response.json()

            except aiohttp.ClientError as err:
                raise AmperaConnectionError(
                    f"Connection error: {err}"
                ) from err
            except TimeoutError as err:
                raise AmperaConnectionError(
                    "Request timed out"
                ) from err

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def async_validate_token(self) -> bool:
        """Validate the API token by fetching sites.

        Returns:
            True if token is valid

        Raises:
            AmperaAuthError: If token is invalid
        """
        try:
            await self.async_get_sites()
            return True
        except AmperaAuthError:
            return False

    # -------------------------------------------------------------------------
    # Sites
    # -------------------------------------------------------------------------

    async def async_get_sites(self) -> list[dict[str, Any]]:
        """Get all sites for the authenticated user.

        Returns:
            List of site dictionaries
        """
        response = await self._request("GET", "/api/v1/sites")
        # Handle both list and paginated response formats
        if isinstance(response, list):
            return response
        return response.get("sites", response.get("items", []))

    async def async_get_site(self, site_id: str) -> dict[str, Any]:
        """Get a single site by ID.

        Args:
            site_id: Site UUID

        Returns:
            Site dictionary
        """
        response = await self._request("GET", f"/api/v1/sites/{site_id}")
        return response if isinstance(response, dict) else {}

    # -------------------------------------------------------------------------
    # Telemetry
    # -------------------------------------------------------------------------

    async def async_get_telemetry(self, site_id: str) -> dict[str, Any]:
        """Get current telemetry for a site.

        Args:
            site_id: Site UUID

        Returns:
            Telemetry data with power, voltage, current readings
        """
        return await self._request(
            "GET", f"/api/v1/telemetry/sites/{site_id}/current"
        )

    async def async_get_portfolio(self) -> dict[str, Any]:
        """Get aggregated portfolio data for all sites.

        Returns:
            Portfolio statistics
        """
        return await self._request("GET", "/api/v1/telemetry/portfolio")

    # -------------------------------------------------------------------------
    # Devices
    # -------------------------------------------------------------------------

    async def async_get_devices(self, site_id: str) -> list[dict[str, Any]]:
        """Get all devices for a site.

        Args:
            site_id: Site UUID

        Returns:
            List of device dictionaries
        """
        response = await self._request(
            "GET", "/api/v1/devices", params={"site_id": site_id}
        )
        if isinstance(response, list):
            return response
        return response.get("devices", response.get("items", []))

    async def async_get_device(self, device_id: str) -> dict[str, Any]:
        """Get a single device by ID.

        Args:
            device_id: Device UUID

        Returns:
            Device dictionary with current state
        """
        return await self._request("GET", f"/api/v1/devices/{device_id}")

    # -------------------------------------------------------------------------
    # Device Commands
    # -------------------------------------------------------------------------

    async def async_send_command(
        self,
        device_id: str,
        command_type: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a command to a device.

        Args:
            device_id: Target device UUID
            command_type: Command type (turn_on, turn_off, set_temperature, etc.)
            parameters: Command parameters (e.g., target_temperature_c)

        Returns:
            Command response with status

        Command types:
            - turn_on: Turn device on
            - turn_off: Turn device off
            - set_temperature: Set target temperature (requires target_temperature_c)
            - set_charge_limit: Set EV charge limit (requires target_soc_percent)
            - start_charge: Start EV charging
            - stop_charge: Stop EV charging
        """
        data = {
            "device_id": device_id,
            "command_type": command_type,
            "source": "homeassistant",
        }
        if parameters:
            data["parameters"] = parameters

        return await self._request("POST", "/api/v1/device-commands", data=data)

    async def async_get_command_status(self, command_id: str) -> dict[str, Any]:
        """Get the status of a command.

        Args:
            command_id: Command UUID

        Returns:
            Command status (pending, sent, acknowledged, failed)
        """
        return await self._request(
            "GET", f"/api/v1/device-commands/{command_id}"
        )

    # -------------------------------------------------------------------------
    # Convenience methods for water heater
    # -------------------------------------------------------------------------

    async def async_turn_on_device(self, device_id: str) -> dict[str, Any]:
        """Turn a device on."""
        return await self.async_send_command(device_id, "turn_on")

    async def async_turn_off_device(self, device_id: str) -> dict[str, Any]:
        """Turn a device off."""
        return await self.async_send_command(device_id, "turn_off")

    async def async_set_temperature(
        self, device_id: str, temperature: float
    ) -> dict[str, Any]:
        """Set water heater target temperature.

        Args:
            device_id: Water heater device ID
            temperature: Target temperature in Celsius (40-85)
        """
        return await self.async_send_command(
            device_id,
            "set_temperature",
            {"target_temperature_c": temperature},
        )

    # -------------------------------------------------------------------------
    # Home Assistant Push Integration (v2.0)
    # -------------------------------------------------------------------------

    async def async_register_site(
        self,
        name: str,
        ha_instance_id: str,
        grid_region: str = "NO1",
        city: str | None = None,
        country: str = "NO",
        timezone: str = "Europe/Oslo",
    ) -> dict[str, Any]:
        """Register or update a site from Home Assistant.

        Called during config flow setup. Creates or updates a site
        associated with this HA instance.

        Args:
            name: Site name (e.g., "Home", "Cabin")
            ha_instance_id: Unique HA instance identifier
            grid_region: Norwegian grid region (NO1-NO5)
            city: City name
            country: Country code
            timezone: Timezone string

        Returns:
            dict with site_id, created (bool), message
        """
        data = {
            "name": name,
            "ha_instance_id": ha_instance_id,
            "grid_region": grid_region,
            "location": {
                "city": city,
                "country": country,
                "timezone": timezone,
            },
        }
        return await self._request("POST", "/api/v1/ha/sites/register", data=data)

    async def async_register_devices(
        self,
        site_id: str,
        devices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Register devices from Home Assistant.

        Called during config flow setup after device selection.

        Args:
            site_id: Ampæra site UUID
            devices: List of device dicts with:
                - ha_entity_id: HA entity ID
                - device_type: Device type (power_meter, water_heater, etc.)
                - name: Device name
                - capabilities: List of capabilities

        Returns:
            dict with registered count and device_mappings
        """
        data = {
            "site_id": site_id,
            "devices": devices,
        }
        return await self._request("POST", "/api/v1/ha/devices/register", data=data)

    async def async_push_telemetry(
        self,
        site_id: str,
        timestamp: str,
        readings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Push telemetry readings to Ampæra.

        Called by the push service when state changes occur.

        Args:
            site_id: Ampæra site UUID
            timestamp: ISO 8601 timestamp
            readings: List of reading dicts with device_id and measurements

        Returns:
            dict with ingested count and server timestamp
        """
        data = {
            "site_id": site_id,
            "timestamp": timestamp,
            "readings": readings,
        }
        return await self._request("POST", "/api/v1/ha/telemetry/ingest", data=data)

    async def async_get_pending_commands(
        self,
        site_id: str,
    ) -> list[dict[str, Any]]:
        """Get pending commands for this site.

        Called by the command service to poll for commands.

        Args:
            site_id: Ampæra site UUID

        Returns:
            List of command dicts to execute
        """
        response = await self._request(
            "GET",
            "/api/v1/ha/commands/pending",
            params={"site_id": site_id},
        )
        if isinstance(response, dict):
            return response.get("commands", [])
        return []

    async def async_acknowledge_command(
        self,
        command_id: str,
        success: bool,
        error_message: str | None = None,
        device_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Acknowledge command execution.

        Called after HA executes a command.

        Args:
            command_id: Command UUID
            success: Whether command executed successfully
            error_message: Error message if failed
            device_state: Current device state after command (optional)

        Returns:
            dict with acknowledged status
        """
        data: dict[str, Any] = {
            "success": success,
            "error_message": error_message,
        }
        if device_state is not None:
            data["device_state"] = device_state

        return await self._request(
            "POST",
            f"/api/v1/ha/commands/{command_id}/ack",
            data=data,
        )

    async def async_sync_devices(
        self,
        site_id: str,
        devices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Sync the current device list to Ampæra.

        Called periodically by the device sync service to keep devices
        in sync. Creates new devices, updates existing ones, and marks
        removed devices as offline.

        Args:
            site_id: Ampæra site UUID
            devices: List of device dicts with:
                - ha_entity_id: HA entity ID
                - device_type: Device type (power_meter, water_heater, etc.)
                - name: Device name
                - capabilities: List of capabilities
                - manufacturer: Optional manufacturer
                - model: Optional model

        Returns:
            dict with created, updated, removed counts and device_mappings
        """
        data = {
            "site_id": site_id,
            "devices": devices,
        }
        return await self._request("POST", "/api/v1/ha/devices/sync", data=data)
