"""Switch platform for Ampæra Simulation.

Creates switch entities for controlling simulated devices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_EV_CHARGER,
    DEVICE_WATER_HEATER,
    DOMAIN,
    EV_CHARGER_MODEL,
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
    """Set up switch platform."""
    coordinator: SimulationCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SwitchEntity] = []

    # Water heater switches
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(WaterHeaterHeatingSwitch(coordinator))

    # EV charger switches
    if DEVICE_EV_CHARGER in coordinator.devices:
        entities.extend(
            [
                EVChargerConnectedSwitch(coordinator),
                EVChargerChargingSwitch(coordinator),
            ]
        )

    async_add_entities(entities)


# =============================================================================
# Water Heater Switches
# =============================================================================


class WaterHeaterHeatingSwitch(CoordinatorEntity, SwitchEntity):
    """Water heater heating switch.

    Controls whether the water heater is actively heating.
    Note: The physics simulation may override this based on
    temperature thresholds and operating mode.
    """

    _attr_has_entity_name = True
    _attr_name = "Heating"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater_heating"

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
    def is_on(self) -> bool | None:
        """Return true if heating is on."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.is_heating
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn on heating."""
        if self.coordinator.water_heater:
            # Setting mode to Normal allows physics to control heating
            self.coordinator.water_heater.mode = "Normal"
            self.coordinator.water_heater.is_heating = True
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn off heating."""
        if self.coordinator.water_heater:
            self.coordinator.water_heater.mode = "Off"
            self.coordinator.water_heater.is_heating = False
            await self.coordinator.async_request_refresh()


# =============================================================================
# EV Charger Switches
# =============================================================================


class EVChargerConnectedSwitch(CoordinatorEntity, SwitchEntity):
    """EV charger connection switch.

    Simulates plugging/unplugging the EV.
    """

    _attr_has_entity_name = True
    _attr_name = "Connected"
    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_connected"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "ev_charger")},
            name="Simulated EV Charger",
            manufacturer=MANUFACTURER,
            model=EV_CHARGER_MODEL,
            sw_version="1.0.0",
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if EV is connected."""
        if self.coordinator.ev_charger:
            return self.coordinator.ev_charger.is_connected
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Connect EV (simulates plugging in)."""
        self.coordinator.connect_ev(battery_soc=30.0)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disconnect EV (simulates unplugging)."""
        self.coordinator.disconnect_ev()
        await self.coordinator.async_request_refresh()


class EVChargerChargingSwitch(CoordinatorEntity, SwitchEntity):
    """EV charger charging switch.

    Controls whether charging is active (if EV is connected).
    """

    _attr_has_entity_name = True
    _attr_name = "Charging"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_charging"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "ev_charger")},
            name="Simulated EV Charger",
            manufacturer=MANUFACTURER,
            model=EV_CHARGER_MODEL,
            sw_version="1.0.0",
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if charging is active."""
        if self.coordinator.ev_charger:
            return self.coordinator.ev_charger.is_charging
        return None

    @property
    def available(self) -> bool:
        """Return true if EV is connected."""
        if self.coordinator.ev_charger:
            return self.coordinator.ev_charger.is_connected
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Start charging."""
        self.coordinator.start_charging()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Stop charging."""
        self.coordinator.stop_charging()
        await self.coordinator.async_request_refresh()
