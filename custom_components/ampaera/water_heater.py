"""Water heater platform for Ampæra Energy integration.

When simulation mode is enabled, creates simulated water heater entity.
When in real device mode, this platform is not used (devices are synced via push).
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
    """Set up Ampæra water heaters from a config entry."""
    # Check if simulation mode is enabled
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE)
    if installation_mode != INSTALLATION_MODE_SIMULATION:
        _LOGGER.debug("Water heater platform: not in simulation mode, skipping")
        return

    # Get simulation coordinator
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: SimulationCoordinator | None = entry_data.get("coordinator")

    if coordinator is None:
        _LOGGER.warning("Water heater platform: simulation coordinator not found")
        return

    # Import and setup simulation water heater
    from .simulation.const import DEVICE_WATER_HEATER
    from .simulation.water_heater import SimulatedWaterHeater

    entities = []

    # Water heater entity
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(SimulatedWaterHeater(coordinator))

    _LOGGER.info("Adding %d simulation water heater entities", len(entities))
    async_add_entities(entities)
