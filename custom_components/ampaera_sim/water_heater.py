"""Water heater platform for Ampæra Simulation.

Uses the native Home Assistant water heater platform for better
integration with the Energy Dashboard and climate controls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_WATER_HEATER,
    DOMAIN,
    MANUFACTURER,
    WATER_HEATER_MODEL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SimulationCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up water heater platform."""
    coordinator: SimulationCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[WaterHeaterEntity] = []

    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(SimulatedWaterHeater(coordinator))

    async_add_entities(entities)


class SimulatedWaterHeater(CoordinatorEntity, WaterHeaterEntity):
    """Simulated water heater entity using native HA platform.

    Provides temperature control and operation mode selection
    through the standard Home Assistant water heater interface.
    """

    _attr_has_entity_name = True
    _attr_name = None  # Uses device name directly
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_operation_list = ["Normal", "Eco", "Boost", "Off"]
    _attr_min_temp = 40
    _attr_max_temp = 75
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize water heater."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "water_heater")},
            name="Simulated Water Heater",
            manufacturer=MANUFACTURER,
            model=WATER_HEATER_MODEL,
            sw_version="1.0.0",
        )

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        if self.coordinator.water_heater:
            return round(self.coordinator.water_heater.current_temp, 1)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.target_temp
        return None

    @property
    def current_operation(self) -> str | None:
        """Return current operation mode."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.mode
        return None

    @property
    def is_away_mode_on(self) -> bool:
        """Return true if away mode is on (Off mode)."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.mode == "Off"
        return False

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None and self.coordinator.water_heater:
            self.coordinator.set_water_heater_target(temp)
            await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        if self.coordinator.water_heater:
            self.coordinator.set_water_heater_mode(operation_mode)
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn on water heater (set to Normal mode)."""
        if self.coordinator.water_heater:
            self.coordinator.set_water_heater_mode("Normal")
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn off water heater."""
        if self.coordinator.water_heater:
            self.coordinator.set_water_heater_mode("Off")
            await self.coordinator.async_request_refresh()
