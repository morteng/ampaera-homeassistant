"""Select platform for Ampæra Energy integration.

When simulation mode is enabled, creates simulated device select controls:
- Water heater mode selection
- EV charger status selection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INSTALLATION_MODE, DOMAIN, INSTALLATION_MODE_SIMULATION

if TYPE_CHECKING:
    from .simulation.coordinator import SimulationCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ampæra select entities from a config entry."""
    # Check if simulation mode is enabled
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE)
    if installation_mode != INSTALLATION_MODE_SIMULATION:
        _LOGGER.debug("Select platform: not in simulation mode, skipping")
        return

    # Get simulation coordinator
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: SimulationCoordinator | None = entry_data.get("coordinator")

    if coordinator is None:
        _LOGGER.warning("Select platform: simulation coordinator not found")
        return

    # Import and setup simulation selects
    from .simulation.const import DEVICE_EV_CHARGER, DEVICE_WATER_HEATER
    from .simulation.select import EVChargerStatusSelect, WaterHeaterModeSelect

    entities = []

    # Water heater mode select
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(WaterHeaterModeSelect(coordinator))

    # EV charger status select
    if DEVICE_EV_CHARGER in coordinator.devices:
        entities.append(EVChargerStatusSelect(coordinator))

    _LOGGER.info("Adding %d simulation select entities", len(entities))
    async_add_entities(entities)
