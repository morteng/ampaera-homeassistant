"""The Ampæra Simulation integration.

Creates simulated smart home devices with proper device registry entries:
- Water Heater (200L, 3kW) - temperature control and physics simulation
- EV Charger (32A, single-phase) - charging simulation with SOC tracking
- AMS Power Meter (3-phase) - aggregated power readings

These devices appear in Home Assistant's device registry with proper
manufacturer, model, and version information, making them discoverable
by the Ampæra Energy integration.

Physics Simulation:
- Water heater: Heat-up rate ~15°C/hour, heat loss ~0.5°C/hour
- EV charger: Power = Current × 230V × 0.95 efficiency
- Power meter: Aggregates power from all simulated loads
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .const import CONF_DEVICES, DOMAIN
from .coordinator import SimulationCoordinator
from .services import async_setup_services, async_unload_services

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ampæra Simulation from a config entry.

    Creates the simulation coordinator with selected devices and
    forwards setup to all entity platforms.
    """
    hass.data.setdefault(DOMAIN, {})

    # Get selected devices from config
    devices = entry.data.get(CONF_DEVICES, [])

    _LOGGER.info("Setting up Ampæra Simulation with devices: %s", devices)

    # Create the simulation coordinator with options
    options = dict(entry.options) if entry.options else {}
    coordinator = SimulationCoordinator(hass, devices, options)

    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await async_setup_services(hass)

    _LOGGER.info(
        "Ampæra Simulation started with %d device(s): %s",
        len(devices),
        ", ".join(devices),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Stops the simulation and removes all entities.
    """
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove stored data
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Unload services if no entries remain
        await async_unload_services(hass)

        _LOGGER.info("Ampæra Simulation unloaded")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Called when reconfiguration is needed.
    """
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
