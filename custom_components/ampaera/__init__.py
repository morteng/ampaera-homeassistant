"""The Ampæra Energy integration (v2.0 Push Architecture).

This integration syncs Home Assistant devices with the Ampæra Smart Home
Energy Management Platform, enabling:
- Real-time telemetry push from HA to Ampæra cloud
- Remote device control from Ampæra dashboard
- Cloud storage, analytics, and optimization

Architecture:
- HA is the source of truth for devices
- Telemetry is pushed TO Ampæra (not pulled)
- Commands are polled FROM Ampæra and executed in HA

For more information, see:
https://github.com/morteng/ampaera-homeassistant
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import AmperaApiClient, AmperaAuthError, AmperaConnectionError
from .command_service import AmperaCommandService
from .const import (
    CONF_API_KEY,
    CONF_API_URL,
    CONF_COMMAND_POLL_INTERVAL,
    CONF_DEVICE_MAPPINGS,
    CONF_DEVICE_SYNC_INTERVAL,
    CONF_POLLING_INTERVAL,
    CONF_SELECTED_ENTITIES,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_API_BASE_URL,
    DEFAULT_COMMAND_POLL_INTERVAL,
    DEFAULT_DEVICE_SYNC_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
)
from .device_sync_service import AmperaDeviceSyncService
from .push_service import AmperaTelemetryPushService

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ampæra from a config entry.

    This is called when the integration is added via the UI.
    It creates the API client, starts the push service for telemetry,
    and starts the command service for remote control.

    Note: We don't create any HA entities - we sync existing HA devices
    to the Ampæra cloud platform.
    """
    hass.data.setdefault(DOMAIN, {})

    # Get config data
    api_key = entry.data[CONF_API_KEY]
    api_url = entry.data.get(CONF_API_URL, DEFAULT_API_BASE_URL)
    site_id = entry.data[CONF_SITE_ID]
    site_name = entry.data.get(CONF_SITE_NAME, "Home")
    device_mappings = entry.data.get(CONF_DEVICE_MAPPINGS, {})
    selected_entities = entry.data.get(CONF_SELECTED_ENTITIES, [])

    # Get options with defaults
    push_interval = entry.options.get(
        CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
    )
    command_poll_interval = entry.options.get(
        CONF_COMMAND_POLL_INTERVAL, DEFAULT_COMMAND_POLL_INTERVAL
    )
    device_sync_interval = entry.options.get(
        CONF_DEVICE_SYNC_INTERVAL, DEFAULT_DEVICE_SYNC_INTERVAL
    )

    _LOGGER.debug("Connecting to Ampæra API at %s", api_url)

    # Create the API client
    api = AmperaApiClient(api_key, base_url=api_url)

    # Validate the token
    try:
        valid = await api.async_validate_token()
        if not valid:
            await api.close()
            raise ConfigEntryAuthFailed("Invalid API token")
    except AmperaAuthError as err:
        await api.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except AmperaConnectionError as err:
        await api.close()
        raise ConfigEntryNotReady(f"Cannot connect to Ampæra: {err}") from err

    # Create telemetry push service
    push_service = AmperaTelemetryPushService(
        hass=hass,
        api_client=api,
        site_id=site_id,
        device_mappings=device_mappings,
        debounce_seconds=float(push_interval),
    )

    # Create command polling service
    command_service = AmperaCommandService(
        hass=hass,
        api_client=api,
        site_id=site_id,
        device_mappings=device_mappings,
        poll_interval=command_poll_interval,
    )

    # Create device sync service (keeps devices in sync with Ampæra)
    device_sync_service = AmperaDeviceSyncService(
        hass=hass,
        entry=entry,
        api_client=api,
        site_id=site_id,
        selected_entities=selected_entities,
        sync_interval=device_sync_interval,
    )

    # Start services
    try:
        await device_sync_service.async_start()  # Sync devices first
        await push_service.async_start()
        await command_service.async_start()
    except Exception as err:
        await api.close()
        raise ConfigEntryNotReady(f"Failed to start services: {err}") from err

    # Store everything in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "push_service": push_service,
        "command_service": command_service,
        "device_sync_service": device_sync_service,
        "site_id": site_id,
        "site_name": site_name,
    }

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info(
        "Ampæra integration started for site '%s' (%s) with %d synced devices",
        site_name,
        site_id,
        len(device_mappings),
    )

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Called when the user changes options via the integration's options flow.
    Updates service settings without full reload when possible.
    """
    data = hass.data[DOMAIN].get(entry.entry_id)
    if not data:
        return

    # Update push service debounce interval
    push_service: AmperaTelemetryPushService = data.get("push_service")
    if push_service:
        new_interval = entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )
        push_service._debounce_seconds = float(new_interval)

    # Update command service poll interval
    command_service: AmperaCommandService = data.get("command_service")
    if command_service:
        new_interval = entry.options.get(
            CONF_COMMAND_POLL_INTERVAL, DEFAULT_COMMAND_POLL_INTERVAL
        )
        command_service.set_poll_interval(new_interval)

    # Update device sync service interval
    device_sync_service: AmperaDeviceSyncService = data.get("device_sync_service")
    if device_sync_service:
        new_interval = entry.options.get(
            CONF_DEVICE_SYNC_INTERVAL, DEFAULT_DEVICE_SYNC_INTERVAL
        )
        device_sync_service.set_sync_interval(new_interval)

    _LOGGER.info("Ampæra options updated")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Called when the integration is removed or reloaded.
    Stops all services and closes connections.
    """
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if not data:
        return True

    # Stop device sync service
    device_sync_service: AmperaDeviceSyncService = data.get("device_sync_service")
    if device_sync_service:
        await device_sync_service.async_stop()

    # Stop push service
    push_service: AmperaTelemetryPushService = data.get("push_service")
    if push_service:
        await push_service.async_stop()

    # Stop command service
    command_service: AmperaCommandService = data.get("command_service")
    if command_service:
        await command_service.async_stop()

    # Close the API client
    api: AmperaApiClient = data.get("api")
    if api:
        await api.close()

    _LOGGER.info("Ampæra integration unloaded")
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Called when the integration needs to be reloaded.
    """
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
) -> bool:
    """Migrate old config entry to new version.

    Called when config entry version changes (VERSION in config_flow.py).
    """
    _LOGGER.debug(
        "Migrating config entry from version %s to version 2",
        entry.version,
    )

    if entry.version == 1:
        # Migration from v1 (pull architecture) to v2 (push architecture)
        # User needs to reconfigure - can't automatically migrate
        _LOGGER.warning(
            "Config entry requires reconfiguration for v2.0 push architecture. "
            "Please remove and re-add the integration."
        )
        # Return False to trigger reconfiguration
        return False

    return True
