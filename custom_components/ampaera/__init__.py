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

from homeassistant.core import ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import AmperaApiClient, AmperaAuthError, AmperaConnectionError
from .command_service import AmperaCommandService
from .const import (
    CONF_API_KEY,
    CONF_API_URL,
    CONF_COMMAND_POLL_INTERVAL,
    CONF_DEVICE_SYNC_INTERVAL,
    CONF_ENABLE_SIMULATION,
    CONF_POLLING_INTERVAL,
    CONF_SELECTED_ENTITIES,
    CONF_SIMULATION_HOUSEHOLD_PROFILE,
    CONF_SIMULATION_WATER_HEATER_TYPE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_API_BASE_URL,
    DEFAULT_COMMAND_POLL_INTERVAL,
    DEFAULT_DEVICE_SYNC_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
)
from .device_sync_service import AmperaDeviceSyncService
from .event_service import AmperaEventService
from .push_service import AmperaTelemetryPushService, EntityMapping
from .services import async_setup_services as async_setup_simulation_services
from .services import async_unload_services as async_unload_simulation_services

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
    selected_entities = entry.data.get(CONF_SELECTED_ENTITIES, [])

    # Get options with defaults
    push_interval = entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
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

    # Create device sync service (keeps devices in sync with Ampæra)
    # This MUST be created and started first to build entity_mappings
    # Note: selected_entities actually contains device IDs (confusing legacy naming)
    device_sync_service = AmperaDeviceSyncService(
        hass=hass,
        entry=entry,
        api_client=api,
        site_id=site_id,
        selected_device_ids=selected_entities,
        sync_interval=device_sync_interval,
    )

    # Start device sync first to discover devices and build entity mappings
    try:
        await device_sync_service.async_start()
    except Exception as err:
        await api.close()
        raise ConfigEntryNotReady(f"Failed to start device sync: {err}") from err

    # Get entity mappings from device sync service (built during initial sync)
    device_id_mappings = device_sync_service.device_id_mappings
    entity_mappings = device_sync_service.entity_mappings

    _LOGGER.debug(
        "Device sync completed: %d devices, %d entities",
        len(device_id_mappings),
        len(entity_mappings),
    )

    # Create event service for reporting state changes with source attribution
    event_service = AmperaEventService(
        hass=hass,
        api_client=api,
        site_id=site_id,
    )

    # Create telemetry push service with entity mappings from device sync
    # Pass event_service for on/off state change reporting
    push_service = AmperaTelemetryPushService(
        hass=hass,
        api_client=api,
        site_id=site_id,
        entity_mappings=entity_mappings,
        debounce_seconds=float(push_interval),
        event_service=event_service,
    )

    # Create command polling service (uses device_id_mappings for command routing)
    command_service = AmperaCommandService(
        hass=hass,
        api_client=api,
        site_id=site_id,
        device_mappings=device_id_mappings,
        poll_interval=command_poll_interval,
    )

    # Build capability mappings for command routing (device_id → {capability → entity_id})
    # This transforms entity_mappings (entity_id → EntityMapping) into a format
    # the command service can use to resolve the correct entity for each command type
    def build_capability_mappings(
        ent_mappings: dict[str, EntityMapping],
    ) -> dict[str, dict[str, str]]:
        """Transform entity mappings to capability mappings."""
        cap_mappings: dict[str, dict[str, str]] = {}
        for ent_id, m in ent_mappings.items():
            dev_id = m.device_id
            if dev_id not in cap_mappings:
                cap_mappings[dev_id] = {}
            cap_mappings[dev_id][m.capability] = ent_id
        return cap_mappings

    capability_mappings = build_capability_mappings(entity_mappings)
    command_service.set_entity_mappings(capability_mappings)

    # Register callback to update services when device sync updates mappings
    def on_sync_complete(
        _device_mappings: dict[str, str],
        new_entity_mappings: dict[str, EntityMapping],
    ) -> None:
        """Update push and command services after device sync."""
        # Update push service with new entity mappings
        push_service.update_entity_mappings(new_entity_mappings)

        # Update command service with capability mappings
        new_cap_mappings = build_capability_mappings(new_entity_mappings)
        command_service.set_entity_mappings(new_cap_mappings)
        _LOGGER.debug(
            "Updated entity mappings for %d devices",
            len(new_entity_mappings),
        )

    device_sync_service.register_sync_callback(on_sync_complete)

    # Start remaining services
    try:
        await push_service.async_start()
        await command_service.async_start()
    except Exception as err:
        await device_sync_service.async_stop()
        await api.close()
        raise ConfigEntryNotReady(f"Failed to start services: {err}") from err

    # Store everything in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "push_service": push_service,
        "command_service": command_service,
        "device_sync_service": device_sync_service,
        "event_service": event_service,
        "site_id": site_id,
        "site_name": site_name,
    }

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register services (only once for the domain)
    await _async_setup_services(hass)

    # Register simulation services
    await async_setup_simulation_services(hass)

    # Check if simulation is enabled
    simulation_enabled = entry.data.get(CONF_ENABLE_SIMULATION, False) or entry.options.get(
        CONF_ENABLE_SIMULATION, False
    )
    if simulation_enabled:
        household_profile = entry.data.get(
            CONF_SIMULATION_HOUSEHOLD_PROFILE,
            entry.options.get(CONF_SIMULATION_HOUSEHOLD_PROFILE, "family"),
        )
        wh_type = entry.data.get(
            CONF_SIMULATION_WATER_HEATER_TYPE,
            entry.options.get(CONF_SIMULATION_WATER_HEATER_TYPE, "smart"),
        )
        _LOGGER.info(
            "Household simulation ENABLED - Profile: %s, Water heater: %s. "
            "Ensure simulation packages are added to your configuration.yaml",
            household_profile,
            wh_type,
        )
        # Store simulation config in hass.data for other components to access
        hass.data[DOMAIN][entry.entry_id]["simulation"] = {
            "enabled": True,
            "household_profile": household_profile,
            "water_heater_type": wh_type,
        }

    _LOGGER.info(
        "Ampæra integration started for site '%s' (%s) with %d devices, %d entities%s",
        site_name,
        site_id,
        len(device_id_mappings),
        len(entity_mappings),
        " (simulation enabled)" if simulation_enabled else "",
    )

    return True


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up Ampæra services."""
    # Only register services once
    if hass.services.has_service(DOMAIN, "force_sync"):
        return

    async def handle_force_sync(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle force_sync service call."""
        _LOGGER.info("Force sync requested via service call")
        for _entry_id, data in hass.data.get(DOMAIN, {}).items():
            if isinstance(data, dict):
                sync_service = data.get("device_sync_service")
                if sync_service:
                    await sync_service.async_sync_now()

    async def handle_push_telemetry(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle push_telemetry service call."""
        _LOGGER.info("Push telemetry requested via service call")
        for _entry_id, data in hass.data.get(DOMAIN, {}).items():
            if isinstance(data, dict):
                push_service = data.get("push_service")
                if push_service:
                    await push_service.async_push_now()

    hass.services.async_register(DOMAIN, "force_sync", handle_force_sync)
    hass.services.async_register(DOMAIN, "push_telemetry", handle_push_telemetry)


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
        new_interval = entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
        push_service._debounce_seconds = float(new_interval)

    # Update command service poll interval
    command_service: AmperaCommandService = data.get("command_service")
    if command_service:
        new_interval = entry.options.get(CONF_COMMAND_POLL_INTERVAL, DEFAULT_COMMAND_POLL_INTERVAL)
        command_service.set_poll_interval(new_interval)

    # Update device sync service interval
    device_sync_service: AmperaDeviceSyncService = data.get("device_sync_service")
    if device_sync_service:
        new_interval = entry.options.get(CONF_DEVICE_SYNC_INTERVAL, DEFAULT_DEVICE_SYNC_INTERVAL)
        device_sync_service.set_sync_interval(new_interval)

        # If command service exists, update its entity mappings from latest sync
        if command_service:
            entity_mappings = device_sync_service.entity_mappings
            capability_mappings: dict[str, dict[str, str]] = {}
            for entity_id, mapping in entity_mappings.items():
                device_id = mapping.device_id
                if device_id not in capability_mappings:
                    capability_mappings[device_id] = {}
                capability_mappings[device_id][mapping.capability] = entity_id
            command_service.set_entity_mappings(capability_mappings)

    # Update simulation config if changed
    simulation_enabled = entry.options.get(CONF_ENABLE_SIMULATION, False)
    if simulation_enabled:
        data["simulation"] = {
            "enabled": True,
            "household_profile": entry.options.get(CONF_SIMULATION_HOUSEHOLD_PROFILE, "family"),
            "water_heater_type": entry.options.get(CONF_SIMULATION_WATER_HEATER_TYPE, "smart"),
        }
        _LOGGER.info("Simulation updated: %s", data["simulation"])
    elif "simulation" in data:
        del data["simulation"]
        _LOGGER.info("Simulation disabled")

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

    # Unload simulation services if no entries remain
    await async_unload_simulation_services(hass)

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
