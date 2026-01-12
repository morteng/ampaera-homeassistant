"""Services for Ampæra Simulation.

Provides simulation control services for testing scenarios:
- simulate_shower: Drop water heater temperature
- connect_ev: Simulate EV connection
- disconnect_ev: Simulate EV disconnection
- start_charging: Start EV charging
- stop_charging: Stop EV charging
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import ServiceCall

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import SimulationCoordinator

_LOGGER = logging.getLogger(__name__)

# Service names
SERVICE_SIMULATE_SHOWER = "simulate_shower"
SERVICE_CONNECT_EV = "connect_ev"
SERVICE_DISCONNECT_EV = "disconnect_ev"
SERVICE_START_CHARGING = "start_charging"
SERVICE_STOP_CHARGING = "stop_charging"
SERVICE_SET_CURRENT_LIMIT = "set_current_limit"

# Service schemas
SIMULATE_SHOWER_SCHEMA = vol.Schema(
    {
        vol.Optional("liters", default=50): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=200)
        ),
    }
)

CONNECT_EV_SCHEMA = vol.Schema(
    {
        vol.Optional("battery_soc", default=30): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
    }
)

SET_CURRENT_LIMIT_SCHEMA = vol.Schema(
    {
        vol.Required("current"): vol.All(
            vol.Coerce(int), vol.Range(min=6, max=32)
        ),
    }
)


def _get_coordinator(hass: HomeAssistant) -> SimulationCoordinator | None:
    """Get the first available coordinator."""
    if DOMAIN not in hass.data:
        return None

    for entry_data in hass.data[DOMAIN].values():
        if isinstance(entry_data, dict) and "coordinator" in entry_data:
            return entry_data["coordinator"]

    return None


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up simulation services."""
    # Don't register if already registered
    if hass.services.has_service(DOMAIN, SERVICE_SIMULATE_SHOWER):
        return

    async def handle_simulate_shower(call: ServiceCall) -> None:
        """Handle simulate_shower service call."""
        liters = call.data.get("liters", 50)
        _LOGGER.info("Simulating shower usage: %d liters", liters)

        coordinator = _get_coordinator(hass)
        if coordinator:
            coordinator.simulate_shower(liters)
            await coordinator.async_request_refresh()

    async def handle_connect_ev(call: ServiceCall) -> None:
        """Handle connect_ev service call."""
        battery_soc = call.data.get("battery_soc", 30.0)
        _LOGGER.info("Simulating EV connection with %.0f%% SOC", battery_soc)

        coordinator = _get_coordinator(hass)
        if coordinator:
            coordinator.connect_ev(battery_soc)
            await coordinator.async_request_refresh()

    async def handle_disconnect_ev(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle disconnect_ev service call."""
        _LOGGER.info("Simulating EV disconnection")

        coordinator = _get_coordinator(hass)
        if coordinator:
            coordinator.disconnect_ev()
            await coordinator.async_request_refresh()

    async def handle_start_charging(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle start_charging service call."""
        _LOGGER.info("Starting EV charging")

        coordinator = _get_coordinator(hass)
        if coordinator:
            coordinator.start_charging()
            await coordinator.async_request_refresh()

    async def handle_stop_charging(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle stop_charging service call."""
        _LOGGER.info("Stopping EV charging")

        coordinator = _get_coordinator(hass)
        if coordinator:
            coordinator.stop_charging()
            await coordinator.async_request_refresh()

    async def handle_set_current_limit(call: ServiceCall) -> None:
        """Handle set_current_limit service call."""
        current = call.data["current"]
        _LOGGER.info("Setting EV current limit to %dA", current)

        coordinator = _get_coordinator(hass)
        if coordinator:
            coordinator.set_ev_current_limit(current)
            await coordinator.async_request_refresh()

    # Register all services
    hass.services.async_register(
        DOMAIN, SERVICE_SIMULATE_SHOWER, handle_simulate_shower, schema=SIMULATE_SHOWER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CONNECT_EV, handle_connect_ev, schema=CONNECT_EV_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_DISCONNECT_EV, handle_disconnect_ev)
    hass.services.async_register(DOMAIN, SERVICE_START_CHARGING, handle_start_charging)
    hass.services.async_register(DOMAIN, SERVICE_STOP_CHARGING, handle_stop_charging)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CURRENT_LIMIT, handle_set_current_limit, schema=SET_CURRENT_LIMIT_SCHEMA
    )

    _LOGGER.info("Ampæra Simulation services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload simulation services."""
    # Only unload if no entries remain
    if hass.data.get(DOMAIN):
        return

    services_to_remove = [
        SERVICE_SIMULATE_SHOWER,
        SERVICE_CONNECT_EV,
        SERVICE_DISCONNECT_EV,
        SERVICE_START_CHARGING,
        SERVICE_STOP_CHARGING,
        SERVICE_SET_CURRENT_LIMIT,
    ]

    for service in services_to_remove:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    _LOGGER.info("Ampæra Simulation services unloaded")
