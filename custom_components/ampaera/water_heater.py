"""Water heater platform for Ampæra Energy integration.

Provides control for water heaters (varmtvannsbereder) connected
to the Ampæra platform.

Features:
- Current temperature reading
- Target temperature control (40-85°C)
- Operation modes (comfort, eco, boost, off)
- Turn on/off
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DEVICE_TYPE_WATER_HEATER, DOMAIN
from .coordinator import AmperaDataCoordinator

_LOGGER = logging.getLogger(__name__)

# Operation modes
OPERATION_MODE_COMFORT = "comfort"
OPERATION_MODE_ECO = "eco"
OPERATION_MODE_BOOST = "boost"
OPERATION_MODE_OFF = "off"

OPERATION_MODES = [
    OPERATION_MODE_COMFORT,
    OPERATION_MODE_ECO,
    OPERATION_MODE_BOOST,
    OPERATION_MODE_OFF,
]

# Temperature limits (Celsius)
MIN_TEMP = 40.0
MAX_TEMP = 85.0
DEFAULT_TEMP = 65.0  # Legionella prevention temperature


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ampæra water heaters from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, AmperaDataCoordinator] = data["coordinators"]
    api = data["api"]

    entities: list[AmperaWaterHeater] = []

    for site_id, coordinator in coordinators.items():
        # Find water heater devices
        for device in coordinator.devices_data:
            device_type = device.get("device_type", device.get("type"))
            if device_type == DEVICE_TYPE_WATER_HEATER:
                entities.append(
                    AmperaWaterHeater(
                        coordinator=coordinator,
                        device=device,
                        api=api,
                    )
                )

    async_add_entities(entities)


class AmperaWaterHeater(CoordinatorEntity[AmperaDataCoordinator], WaterHeaterEntity):
    """Representation of an Ampæra water heater."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_attribution = ATTRIBUTION
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_operation_list = OPERATION_MODES
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(
        self,
        coordinator: AmperaDataCoordinator,
        device: dict[str, Any],
        api: Any,
    ) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator)
        self._device_id = device.get("device_id", device.get("id"))
        self._device_name = device.get("name", "Water Heater")
        self._api = api
        self._attr_unique_id = f"{coordinator.site_id}_{self._device_id}_water_heater"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this water heater."""
        device = self._get_device()
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer=device.get("manufacturer", "Unknown"),
            model=device.get("model", "Water Heater"),
            via_device=(DOMAIN, self.coordinator.site_id),
        )

    def _get_device(self) -> dict[str, Any]:
        """Get current device data from coordinator."""
        return self.coordinator.get_device(self._device_id) or {}

    def _get_state(self) -> dict[str, Any]:
        """Get current state from device data."""
        device = self._get_device()
        state = device.get("current_state", device.get("state", {}))
        # Handle nested water_heater state
        if "water_heater" in state:
            return {**state, **state["water_heater"]}
        return state

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        state = self._get_state()
        return state.get("temperature_c", state.get("current_temp"))

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        state = self._get_state()
        return state.get("target_temperature_c", state.get("target_temp", DEFAULT_TEMP))

    @property
    def current_operation(self) -> str | None:
        """Return the current operation mode."""
        state = self._get_state()
        mode = state.get("mode", OPERATION_MODE_COMFORT)

        # Map on/off state to mode if needed
        is_on = state.get("is_on", True)
        if not is_on:
            return OPERATION_MODE_OFF

        return mode if mode in OPERATION_MODES else OPERATION_MODE_COMFORT

    @property
    def is_on(self) -> bool:
        """Return True if water heater is on."""
        state = self._get_state()
        return state.get("is_on", True)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False

        device = self._get_device()
        status = device.get("status", "unknown")
        return status != "offline"

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        # Clamp to valid range
        temperature = max(MIN_TEMP, min(MAX_TEMP, float(temperature)))

        _LOGGER.debug(
            "Setting water heater %s temperature to %s°C",
            self._device_id,
            temperature,
        )

        await self._api.async_set_temperature(self._device_id, temperature)
        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new operation mode."""
        _LOGGER.debug(
            "Setting water heater %s mode to %s",
            self._device_id,
            operation_mode,
        )

        if operation_mode == OPERATION_MODE_OFF:
            await self._api.async_turn_off_device(self._device_id)
        else:
            # Turn on if off, then set mode
            if not self.is_on:
                await self._api.async_turn_on_device(self._device_id)

            # For now, mode is implicit in temperature/on-off
            # Future: Add set_mode command if backend supports it

        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the water heater on."""
        _LOGGER.debug("Turning on water heater %s", self._device_id)
        await self._api.async_turn_on_device(self._device_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the water heater off."""
        _LOGGER.debug("Turning off water heater %s", self._device_id)
        await self._api.async_turn_off_device(self._device_id)
        await self.coordinator.async_request_refresh()
