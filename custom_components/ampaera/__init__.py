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

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.config_entry_oauth2_flow import async_register_implementation

from .api import AmperaApiClient, AmperaAuthError, AmperaConnectionError
from .application_credentials import AmperaOAuth2Implementation
from .command_service import AmperaCommandService
from .const import (
    AUTH_METHOD_API_KEY,
    AUTH_METHOD_OAUTH,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_AUTH_METHOD,
    CONF_COMMAND_POLL_INTERVAL,
    CONF_DEVICE_SYNC_INTERVAL,
    CONF_ENABLE_SIMULATION,
    CONF_GRID_REGION,
    CONF_INSTALLATION_MODE,
    CONF_OAUTH_TOKEN,
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
    INSTALLATION_MODE_REAL,
    INSTALLATION_MODE_SIMULATION,
)
from .device_sync_service import AmperaDeviceSyncService
from .event_service import AmperaEventService
from .push_service import AmperaTelemetryPushService, EntityMapping
from .services import async_setup_services as async_setup_simulation_services
from .services import async_unload_services as async_unload_simulation_services

_LOGGER = logging.getLogger(__name__)

# Platforms to forward to when simulation mode is enabled
SIMULATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Ampæra integration.

    This is called once when the integration is first loaded.
    We register our OAuth2 implementation here so it's available
    for the config flow.
    """
    # Register our built-in OAuth2 implementation
    # This allows users to authenticate without creating their own OAuth app
    async_register_implementation(
        hass,
        DOMAIN,
        AmperaOAuth2Implementation(hass),
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ampæra from a config entry.

    This is called when the integration is added via the UI.
    It creates the API client, starts the push service for telemetry,
    and starts the command service for remote control.

    Note: We don't create any HA entities - we sync existing HA devices
    to the Ampæra cloud platform.
    """
    hass.data.setdefault(DOMAIN, {})

    # Get config data - support both OAuth and API key auth
    auth_method = entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_API_KEY)
    if auth_method == AUTH_METHOD_OAUTH:
        api_token = entry.data.get(CONF_OAUTH_TOKEN)
        if not api_token:
            raise ConfigEntryAuthFailed("OAuth token missing")
    else:
        api_token = entry.data.get(CONF_API_KEY)
        if not api_token:
            raise ConfigEntryAuthFailed("API key missing")

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

    _LOGGER.debug("Connecting to Ampæra API at %s (auth: %s)", api_url, auth_method)

    # Create the API client
    api = AmperaApiClient(api_token, base_url=api_url)

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

    # Check if simulation is enabled (either via installation_mode or explicit enable_simulation toggle)
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)
    simulation_enabled = (
        installation_mode == INSTALLATION_MODE_SIMULATION
        or entry.data.get(CONF_ENABLE_SIMULATION, False)
        or entry.options.get(CONF_ENABLE_SIMULATION, False)
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
            "Household simulation ENABLED - Profile: %s, Water heater: %s",
            household_profile,
            wh_type,
        )
        # Store simulation config in hass.data for other components to access
        hass.data[DOMAIN][entry.entry_id]["simulation"] = {
            "enabled": True,
            "household_profile": household_profile,
            "water_heater_type": wh_type,
        }

        # Auto-setup ampaera_sim integration if not already configured
        await _async_setup_simulation_integration(hass, entry)

    # Auto-create dashboard (non-blocking, errors don't fail setup)
    await _async_setup_dashboard(hass, entry)

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


async def _async_setup_simulation_integration(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up embedded simulation when simulation mode is enabled.

    Creates simulated smart home devices via HA's native platform forwarding:
    - Water Heater (200L, 3kW) - temperature control and physics simulation
    - EV Charger (32A, single-phase) - charging simulation with SOC tracking
    - AMS Power Meter (3-phase) - aggregated power readings

    Uses proper platform setup to ensure entities are registered correctly.
    """
    try:
        # Import embedded simulation module
        from .simulation import async_setup_simulation

        _LOGGER.info("Setting up embedded simulation for Ampæra")

        # Determine which devices to simulate
        devices = ["ams_meter", "water_heater", "ev_charger"]

        # Create and start the simulation coordinator
        coordinator = await async_setup_simulation(hass, entry, devices)

        # Store coordinator under the key expected by platform files
        # Platform files expect hass.data[DOMAIN][entry.entry_id]["coordinator"]
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if entry_data and isinstance(entry_data, dict):
            entry_data["coordinator"] = coordinator
            entry_data["simulation_coordinator"] = coordinator  # Keep for backwards compat

        _LOGGER.info(
            "Simulation coordinator initialized with %d devices: %s",
            len(devices),
            ", ".join(devices),
        )

        # Forward to simulation platforms using HA's native mechanism
        # This ensures entities are properly registered in the entity registry
        await hass.config_entries.async_forward_entry_setups(entry, SIMULATION_PLATFORMS)

        _LOGGER.info(
            "Embedded simulation platforms loaded: %s",
            ", ".join([p.value for p in SIMULATION_PLATFORMS]),
        )

        # Schedule a delayed device sync to pick up the simulation entities
        async def _delayed_sync() -> None:
            """Trigger device sync after simulation entities are ready."""
            try:
                await asyncio.sleep(5)
                _LOGGER.info("Triggering device sync after simulation setup")

                entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if entry_data and isinstance(entry_data, dict):
                    sync_service = entry_data.get("device_sync_service")
                    if sync_service:
                        await sync_service.async_sync_now()
                        _LOGGER.info("Post-simulation device sync completed")
            except Exception as err:
                _LOGGER.error("Delayed sync failed: %s", err)

        hass.async_create_task(_delayed_sync(), name="ampaera_simulation_sync")

    except ImportError as err:
        _LOGGER.error(
            "Could not import simulation module: %s. "
            "Simulation mode requires the embedded simulation package.",
            err,
        )
    except Exception as err:
        _LOGGER.error("Failed to setup simulation: %s", err)


async def _async_setup_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Auto-create and register Lovelace dashboard.

    Creates a dashboard and registers it with Home Assistant so it appears
    in the sidebar automatically - no manual setup required.

    This works by directly adding to the lovelace_dashboards storage file,
    which is how HA's UI creates dashboards internally.
    """
    import json

    import yaml

    site_id = entry.data[CONF_SITE_ID]
    site_name = entry.data.get(CONF_SITE_NAME, "Home")
    grid_region = entry.data.get(CONF_GRID_REGION, "NO1")

    # Check if simulation mode is enabled
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)
    is_simulation = installation_mode == INSTALLATION_MODE_SIMULATION

    # Dashboard URL path (must contain hyphen for HA requirement)
    url_path = f"ampaera-{site_id[:8]}"

    # Load appropriate dashboard template based on mode
    if is_simulation:
        template_path = Path(__file__).parent / "dashboards" / "ampaera_dashboard_simulation.yaml"
        _LOGGER.info("Using simulation dashboard template")
    else:
        template_path = Path(__file__).parent / "dashboards" / "ampaera_dashboard.yaml"

    if not template_path.exists():
        _LOGGER.warning("Dashboard template not found at %s", template_path)
        return

    try:
        # Read template and substitute placeholders (use executor for file I/O)
        template = await hass.async_add_executor_job(
            template_path.read_text, "utf-8"
        )
        # Slugify site name to match HA's entity ID generation
        # HA uses this pattern: sensor.{device_name_slugified}_{entity_key}
        from homeassistant.util import slugify
        site_name_slug = slugify(site_name)

        dashboard_yaml = (
            template.replace("{site_id}", site_id)
            .replace("{site_name}", site_name)
            .replace("{site_name_slug}", site_name_slug)
            .replace("{grid_region}", grid_region)
        )

        # Parse YAML to get dashboard config
        dashboard_config = yaml.safe_load(dashboard_yaml)

        # Storage file paths
        storage_dir = Path(hass.config.path(".storage"))
        dashboards_file = storage_dir / "lovelace_dashboards"
        dashboard_config_file = storage_dir / f"lovelace.{url_path}"

        # Read existing dashboards storage
        dashboards_data = {"version": 1, "minor_version": 1, "key": "lovelace_dashboards", "data": {"items": []}}
        if dashboards_file.exists():
            content = await hass.async_add_executor_job(dashboards_file.read_text, "utf-8")
            dashboards_data = json.loads(content)

        # Check if dashboard already exists
        existing_ids = [item.get("url_path") for item in dashboards_data["data"]["items"]]
        if url_path in existing_ids:
            _LOGGER.debug("Dashboard %s already registered, skipping", url_path)
            return

        # Add new dashboard entry
        new_dashboard = {
            "id": url_path,
            "icon": "mdi:lightning-bolt",
            "title": f"Ampæra - {site_name}",
            "url_path": url_path,
            "mode": "storage",
            "show_in_sidebar": True,
            "require_admin": False,
        }
        dashboards_data["data"]["items"].append(new_dashboard)

        # Write updated dashboards list
        await hass.async_add_executor_job(
            dashboards_file.write_text,
            json.dumps(dashboards_data, indent=2),
            "utf-8",
        )
        _LOGGER.info("Registered Ampæra dashboard in lovelace_dashboards")

        # Write dashboard configuration
        config_data = {
            "version": 1,
            "minor_version": 1,
            "key": f"lovelace.{url_path}",
            "data": {"config": dashboard_config},
        }
        await hass.async_add_executor_job(
            dashboard_config_file.write_text,
            json.dumps(config_data, indent=2),
            "utf-8",
        )
        _LOGGER.info("Saved dashboard configuration to %s", dashboard_config_file)

        # Reload lovelace to make dashboard appear immediately
        # Fire the lovelace_updated event to trigger UI refresh
        dashboard_appeared = False
        try:
            # Method 1: Fire lovelace_updated event
            hass.bus.async_fire("lovelace_updated", {"url_path": url_path})
            _LOGGER.info("Fired lovelace_updated event for dashboard %s", url_path)

            # Method 2: Call lovelace reload service if available
            if hass.services.has_service("lovelace", "reload_resources"):
                await hass.services.async_call("lovelace", "reload_resources", blocking=False)
                _LOGGER.info("Called lovelace.reload_resources service")

            # Method 3: Reload the dashboards collection if accessible
            if "lovelace" in hass.data:
                lovelace_data = hass.data["lovelace"]
                # Try to reload the dashboards collection
                if hasattr(lovelace_data, "dashboards") and hasattr(lovelace_data.dashboards, "async_load"):
                    await lovelace_data.dashboards.async_load()
                    _LOGGER.info("Reloaded lovelace dashboards collection")
                    dashboard_appeared = True
                elif hasattr(lovelace_data, "async_load"):
                    await lovelace_data.async_load(force=True)
                    _LOGGER.info("Reloaded lovelace data")
                    dashboard_appeared = True

            # Even if methods above work partially, assume dashboard will appear
            dashboard_appeared = True
        except Exception as reload_err:
            _LOGGER.debug("Could not reload lovelace dynamically: %s", reload_err)

        # Notify user
        if dashboard_appeared:
            persistent_notification.async_create(
                hass,
                (
                    f"Your Ampæra Energy dashboard for **{site_name}** has been created!\n\n"
                    f"**Refresh your browser** to see **Ampæra - {site_name}** in the sidebar,\n"
                    f"or navigate directly to `/lovelace/{url_path}`."
                ),
                title="Ampæra Dashboard Created",
                notification_id=f"ampaera_dashboard_{site_id[:8]}",
            )
        else:
            persistent_notification.async_create(
                hass,
                (
                    f"Your Ampæra Energy dashboard for **{site_name}** has been created!\n\n"
                    "**Restart Home Assistant** to see it in the sidebar.\n\n"
                    "Go to **Settings** → **System** → **Restart** (top right corner).\n\n"
                    f"After restart, find it as **Ampæra - {site_name}** "
                    f"or navigate to `/lovelace/{url_path}`."
                ),
                title="Ampæra Dashboard Created - Restart Required",
                notification_id=f"ampaera_dashboard_{site_id[:8]}",
            )

    except Exception as err:
        _LOGGER.error("Failed to create dashboard: %s", err)
        # Fall back to YAML file creation
        with contextlib.suppress(Exception):
            await _async_setup_dashboard_yaml_fallback(hass, entry, None)


async def _async_setup_dashboard_yaml_fallback(
    hass: HomeAssistant, entry: ConfigEntry, dashboard_yaml: str | None
) -> None:
    """Fallback: Create dashboard YAML file and notify user to add manually."""
    site_id = entry.data[CONF_SITE_ID]
    site_name = entry.data.get(CONF_SITE_NAME, "Home")
    grid_region = entry.data.get(CONF_GRID_REGION, "NO1")

    # Check if simulation mode is enabled
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)
    is_simulation = installation_mode == INSTALLATION_MODE_SIMULATION

    if dashboard_yaml is None:
        from homeassistant.util import slugify
        site_name_slug = slugify(site_name)

        # Use appropriate template based on mode
        if is_simulation:
            template_path = Path(__file__).parent / "dashboards" / "ampaera_dashboard_simulation.yaml"
        else:
            template_path = Path(__file__).parent / "dashboards" / "ampaera_dashboard.yaml"

        template = await hass.async_add_executor_job(template_path.read_text, "utf-8")
        dashboard_yaml = (
            template.replace("{site_id}", site_id)
            .replace("{site_name}", site_name)
            .replace("{site_name_slug}", site_name_slug)
            .replace("{grid_region}", grid_region)
        )

    # Create dashboards directory if needed
    dashboards_dir = Path(hass.config.path("dashboards"))
    await hass.async_add_executor_job(dashboards_dir.mkdir, True, True)

    # Write dashboard file
    dashboard_file = dashboards_dir / f"ampaera_{site_id[:8]}.yaml"

    if not dashboard_file.exists():
        await hass.async_add_executor_job(
            dashboard_file.write_text, dashboard_yaml, "utf-8"
        )
        _LOGGER.info("Created Ampæra dashboard YAML at %s", dashboard_file)

        persistent_notification.async_create(
            hass,
            (
                f"Your Ampæra Energy dashboard for **{site_name}** is ready!\n\n"
                "To enable it:\n"
                "1. Go to **Settings** → **Dashboards**\n"
                "2. Click **Add Dashboard**\n"
                "3. Select **Use existing YAML file**\n"
                f"4. Enter path: `dashboards/ampaera_{site_id[:8]}.yaml`\n\n"
                "The dashboard includes real-time power, energy graphs, "
                "device controls, and spot prices."
            ),
            title="Ampæra Dashboard Created",
            notification_id=f"ampaera_dashboard_{site_id[:8]}",
        )


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

    # Unload simulation platforms if in simulation mode
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE)
    if installation_mode == INSTALLATION_MODE_SIMULATION:
        await hass.config_entries.async_unload_platforms(entry, SIMULATION_PLATFORMS)

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
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Migrate old config entry to new version.

    Called when config entry version changes (VERSION in config_flow.py).
    """
    _LOGGER.debug(
        "Migrating config entry from version %s to version 3",
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

    if entry.version == 2:
        # Migration from v2 (API key only) to v3 (OAuth + API key support)
        # Add auth_method field with default to api_key for existing entries
        new_data = {**entry.data, CONF_AUTH_METHOD: AUTH_METHOD_API_KEY}
        hass.config_entries.async_update_entry(entry, data=new_data, version=3)
        _LOGGER.info("Migrated config entry to version 3 (added auth_method=api_key)")

    return True
