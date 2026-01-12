"""Select platform for Ampæra Simulation.

Creates select entities for mode selection like
water heater operating mode and EV charger status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
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
    """Set up select platform."""
    coordinator: SimulationCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SelectEntity] = []

    # Water heater selects
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(WaterHeaterModeSelect(coordinator))

    # EV charger selects (status is read-only, shown as sensor instead)
    if DEVICE_EV_CHARGER in coordinator.devices:
        entities.append(EVChargerStatusSelect(coordinator))

    async_add_entities(entities)


class WaterHeaterModeSelect(CoordinatorEntity, SelectEntity):
    """Water heater operating mode select entity.

    Allows selecting the operating mode:
    - Normal: Heat to 65°C target
    - Eco: Heat to 55°C target (energy saving)
    - Boost: Heat to 75°C (maximum heat)
    - Off: Disable heating
    """

    _attr_has_entity_name = True
    _attr_name = "Mode"
    _attr_options = ["Normal", "Eco", "Boost", "Off"]

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater_mode"

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
    def current_option(self) -> str | None:
        """Return current mode."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.mode
        return None

    async def async_select_option(self, option: str) -> None:
        """Select operating mode."""
        self.coordinator.set_water_heater_mode(option)
        await self.coordinator.async_request_refresh()


class EVChargerStatusSelect(CoordinatorEntity, SelectEntity):
    """EV charger status select entity.

    Shows current charger status. While this is primarily a display,
    selecting certain options can trigger state changes for testing.
    """

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_options = [
        "Disconnected",
        "Connected - Waiting",
        "Charging",
        "Complete",
        "Error",
    ]

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_status"

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
    def current_option(self) -> str | None:
        """Return current status."""
        if self.coordinator.ev_charger:
            return self.coordinator.ev_charger.status
        return None

    async def async_select_option(self, option: str) -> None:
        """Select status (triggers appropriate state changes)."""
        if not self.coordinator.ev_charger:
            return

        ev = self.coordinator.ev_charger

        if option == "Disconnected":
            self.coordinator.disconnect_ev()
        elif option == "Connected - Waiting":
            if not ev.is_connected:
                self.coordinator.connect_ev(battery_soc=30.0)
            self.coordinator.stop_charging()
        elif option == "Charging":
            if not ev.is_connected:
                self.coordinator.connect_ev(battery_soc=30.0)
            self.coordinator.start_charging()
        elif option == "Complete":
            if not ev.is_connected:
                self.coordinator.connect_ev(battery_soc=100.0)
            ev.battery_soc = 100.0
            ev.is_charging = False
            ev.status = "Complete"
        elif option == "Error":
            ev.status = "Error"
            ev.is_charging = False

        await self.coordinator.async_request_refresh()
