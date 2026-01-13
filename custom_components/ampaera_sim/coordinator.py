"""Data update coordinator for Ampæra Simulation.

Implements the physics engine that drives all simulated device behavior.
Runs every UPDATE_INTERVAL_SECONDS to update device states based on
physical models (heat transfer, battery charging, power consumption).
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    AMS_METER_NOMINAL_VOLTAGE,
    AMS_METER_VOLTAGE_VARIATION,
    CABIN_EMPTY_PATTERNS,
    CABIN_OCCUPIED_PATTERNS,
    DEVICE_AMS_METER,
    DEVICE_EV_CHARGER,
    DEVICE_HOUSEHOLD,
    DEVICE_WATER_HEATER,
    DOMAIN,
    EV_CHARGER_EFFICIENCY,
    EV_CHARGER_VOLTAGE,
    HOME_AWAY_PATTERNS,
    HOUSEHOLD_BASE_LOAD_CABIN_EMPTY_W,
    HOUSEHOLD_BASE_LOAD_CABIN_W,
    HOUSEHOLD_BASE_LOAD_HOME_W,
    HOUSEHOLD_PATTERNS,
    UPDATE_INTERVAL_SECONDS,
    WATER_HEATER_HEAT_LOSS_C_PER_HOUR,
    WATER_HEATER_HEAT_RATE_C_PER_HOUR,
    WATER_HEATER_HYSTERESIS,
    WATER_HEATER_MAX_TEMP,
    WATER_HEATER_MIN_TEMP,
    WATER_HEATER_POWER_W,
)
from .models import EVChargerState, HouseholdState, PowerMeterState, WaterHeaterState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class SimulationCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that runs physics simulation for all devices.

    The coordinator runs on a fixed interval and updates all device states
    based on their physical models. It calculates:
    - Water heater temperature changes (heating and heat loss)
    - EV charging progress (energy accumulation, SOC increase)
    - Power meter readings (aggregate power, voltage, current)
    """

    def __init__(
        self, hass: HomeAssistant, devices: list[str], options: dict | None = None
    ) -> None:
        """Initialize the simulation coordinator.

        Args:
            hass: Home Assistant instance
            devices: List of device types to simulate (water_heater, ev_charger, ams_meter)
            options: Optional config entry options (building_type, presence_mode)
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self._devices = devices
        self._options = options or {}
        self._last_update = dt_util.utcnow()

        # Initialize device states based on selected devices
        self.water_heater: WaterHeaterState | None = (
            WaterHeaterState() if DEVICE_WATER_HEATER in devices else None
        )
        self.ev_charger: EVChargerState | None = (
            EVChargerState() if DEVICE_EV_CHARGER in devices else None
        )
        self.power_meter: PowerMeterState | None = (
            PowerMeterState() if DEVICE_AMS_METER in devices else None
        )
        self.household: HouseholdState | None = (
            HouseholdState() if DEVICE_HOUSEHOLD in devices else None
        )

        # Apply options to household if configured
        if self.household and self._options:
            if "building_type" in self._options:
                self.household.building_type = self._options["building_type"]
                _LOGGER.info("Set building_type to %s from options", self._options["building_type"])
            if "presence_mode" in self._options:
                self.household.presence_mode = self._options["presence_mode"]
                _LOGGER.info("Set presence_mode to %s from options", self._options["presence_mode"])

        _LOGGER.debug(
            "Initialized SimulationCoordinator with devices: %s",
            devices,
        )

    @property
    def devices(self) -> list[str]:
        """Return list of enabled device types."""
        return self._devices

    async def _async_update_data(self) -> dict[str, Any]:
        """Run physics simulation step.

        Called every UPDATE_INTERVAL_SECONDS. Calculates the time delta
        since the last update and advances all device physics accordingly.

        Returns:
            Dictionary with current state of all devices
        """
        now = dt_util.utcnow()
        dt_hours = (now - self._last_update).total_seconds() / 3600
        self._last_update = now

        # Update each device's physics
        if self.water_heater:
            self._update_water_heater_physics(dt_hours)

        if self.ev_charger:
            self._update_ev_charger_physics(dt_hours)

        if self.household:
            self._update_household_physics(dt_hours)

        if self.power_meter:
            self._update_power_meter()

        return {
            "water_heater": self.water_heater,
            "ev_charger": self.ev_charger,
            "power_meter": self.power_meter,
            "household": self.household,
        }

    def _update_water_heater_physics(self, dt_hours: float) -> None:
        """Update water heater temperature based on physics.

        Implements a simple thermal model:
        - When heating: temperature rises at HEAT_RATE_C_PER_HOUR
        - Always: ambient heat loss at HEAT_LOSS_C_PER_HOUR
        - Thermostat with hysteresis prevents rapid cycling

        Args:
            dt_hours: Time elapsed since last update in hours
        """
        wh = self.water_heater
        if wh is None:
            return

        # Determine heating state based on mode and temperature
        if wh.mode == "Off":
            wh.is_heating = False
        elif wh.mode == "Boost":
            # Boost mode heats until 75°C
            wh.is_heating = wh.current_temp < 75.0
        else:
            # Normal/Eco mode: use target temp with hysteresis
            target = wh.MODE_TARGETS.get(wh.mode, wh.target_temp)
            if wh.current_temp < target - WATER_HEATER_HYSTERESIS:
                wh.is_heating = True
            elif wh.current_temp >= target:
                wh.is_heating = False
            # Otherwise maintain current heating state

        # Calculate temperature change
        temp_change = 0.0

        if wh.is_heating:
            # Heating: temperature rises
            temp_change += WATER_HEATER_HEAT_RATE_C_PER_HOUR * dt_hours
            wh.power_w = WATER_HEATER_POWER_W
            # Accumulate energy
            wh.energy_kwh += (WATER_HEATER_POWER_W / 1000) * dt_hours
        else:
            wh.power_w = 0.0

        # Ambient heat loss (always present)
        temp_change -= WATER_HEATER_HEAT_LOSS_C_PER_HOUR * dt_hours

        # Apply temperature change with bounds
        wh.current_temp = max(
            WATER_HEATER_MIN_TEMP,
            min(WATER_HEATER_MAX_TEMP, wh.current_temp + temp_change),
        )

    def _update_ev_charger_physics(self, dt_hours: float) -> None:
        """Update EV charger state based on physics.

        Simulates charging at the configured current limit.
        Battery SOC increases based on energy delivered.

        Args:
            dt_hours: Time elapsed since last update in hours
        """
        ev = self.ev_charger
        if ev is None:
            return

        if not ev.is_connected:
            # Not connected - no power, reset session
            ev.is_charging = False
            ev.power_w = 0.0
            ev.status = "Disconnected"
            return

        if ev.battery_soc >= 100.0:
            # Fully charged
            ev.is_charging = False
            ev.power_w = 0.0
            ev.status = "Complete"
            return

        if ev.is_charging:
            # Calculate power and energy
            ev.power_w = EV_CHARGER_VOLTAGE * ev.current_limit * EV_CHARGER_EFFICIENCY
            energy_delivered = (ev.power_w / 1000) * dt_hours

            # Add to session and total energy
            ev.session_energy_kwh += energy_delivered
            ev.total_energy_kwh += energy_delivered

            # Increase SOC (assuming ~60 kWh battery)
            battery_capacity_kwh = 60.0
            soc_increase = (energy_delivered / battery_capacity_kwh) * 100
            ev.battery_soc = min(100.0, ev.battery_soc + soc_increase)

            ev.status = "Charging"

            if ev.battery_soc >= 100.0:
                ev.is_charging = False
                ev.power_w = 0.0
                ev.status = "Complete"
        else:
            # Connected but not charging
            ev.power_w = 0.0
            if ev.battery_soc >= 100.0:
                ev.status = "Complete"
            else:
                ev.status = "Connected - Waiting"

    def _update_household_physics(self, dt_hours: float) -> None:
        """Update household background load based on time of day and presence.

        Generates realistic varying power consumption based on:
        - Time of day (morning/evening peaks, night valley)
        - Day of week (weekday vs weekend patterns)
        - Presence mode (home, away, vacation)
        - Building type (home vs cabin/hytte)
        - Random variations for realism

        Args:
            dt_hours: Time elapsed since last update in hours
        """
        hh = self.household
        if hh is None:
            return

        # Get current time
        now = dt_util.now()
        hour = now.hour
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6

        # Select pattern based on building type and presence
        if hh.building_type == "cabin":
            # Cabin (hytte) patterns
            if hh.presence_mode == "home":
                # Family is at the cabin
                patterns = CABIN_OCCUPIED_PATTERNS
                base_load = HOUSEHOLD_BASE_LOAD_CABIN_W
            else:
                # Cabin is empty
                patterns = CABIN_EMPTY_PATTERNS
                base_load = HOUSEHOLD_BASE_LOAD_CABIN_EMPTY_W
        else:
            # Primary home patterns
            if hh.presence_mode == "home":
                # Family is at home
                patterns = HOUSEHOLD_PATTERNS
                base_load = HOUSEHOLD_BASE_LOAD_HOME_W
            elif hh.presence_mode == "away":
                # Family is away (at cabin for weekend)
                patterns = HOME_AWAY_PATTERNS
                base_load = HOUSEHOLD_BASE_LOAD_HOME_W  # Keep base load for fridge etc.
            else:
                # Vacation - similar to away
                patterns = HOME_AWAY_PATTERNS
                base_load = HOUSEHOLD_BASE_LOAD_HOME_W

        # Get base load pattern for this hour
        weekday_load, weekend_load = patterns.get(hour, (300, 400))
        pattern_load = weekend_load if is_weekend else weekday_load

        # Scale by occupants (4 is baseline)
        if hh.presence_mode == "home":
            occupant_factor = hh.occupants / 4.0
            pattern_load *= occupant_factor

        # Add random variation (±30% for realism when occupied, ±5% when empty)
        if hh.presence_mode == "home":
            variation = random.uniform(0.7, 1.3)
        else:
            variation = random.uniform(0.95, 1.05)
        activity_load = pattern_load * variation

        # Add occasional random spikes (appliance cycles) only when occupied
        if hh.presence_mode == "home" and random.random() < 0.05:
            if hh.building_type == "cabin":
                # Cabin-specific appliances
                spike = random.choice([
                    (1500, "Sauna heating"),
                    (2200, "Kettle"),
                    (1000, "Cooking"),
                    (800, "Coffee maker"),
                ])
            else:
                # Home appliances
                spike = random.choice([
                    (1800, "Cooking"),      # Stove/oven
                    (2200, "Kettle"),       # Electric kettle
                    (1500, "Dishwasher"),   # Dishwasher heating
                    (2000, "Washing"),      # Washing machine heating
                    (900, "Toaster"),       # Toaster
                ])
            activity_load += spike[0]
            hh.activity = spike[1]
        else:
            # Set activity based on presence, building type, and time
            if hh.presence_mode != "home":
                if hh.building_type == "cabin":
                    hh.activity = "Empty (frost protection)"
                else:
                    hh.activity = "Away (standby loads)"
            elif hh.building_type == "cabin":
                # Cabin activities
                if hour in (6, 7, 8):
                    hh.activity = "Cabin morning"
                elif hour in (9, 10) and is_weekend:
                    hh.activity = "Sauna warming"
                elif 11 <= hour <= 13:
                    hh.activity = "Lunch preparation"
                elif 17 <= hour <= 19:
                    hh.activity = "Dinner at cabin"
                elif 20 <= hour <= 22:
                    hh.activity = "Evening relaxation"
                elif hour >= 23 or hour < 6:
                    hh.activity = "Night (cabin)"
                else:
                    hh.activity = "Cabin activity"
            else:
                # Home activities
                if hour in (6, 7):
                    hh.activity = "Morning routine"
                elif hour in (8, 9, 10) and is_weekend:
                    hh.activity = "Weekend breakfast"
                elif 17 <= hour <= 19:
                    hh.activity = "Dinner preparation"
                elif 20 <= hour <= 22:
                    hh.activity = "Evening entertainment"
                elif hour >= 23 or hour < 6:
                    hh.activity = "Night (standby)"
                else:
                    hh.activity = "Normal activity"

        # Total power = base load + activity load
        hh.power_w = base_load + activity_load

        # Accumulate energy
        hh.energy_kwh += (hh.power_w / 1000) * dt_hours

    def _update_power_meter(self) -> None:
        """Update power meter readings based on connected loads.

        Aggregates power from all simulated loads and calculates
        per-phase currents assuming balanced loading.
        """
        pm = self.power_meter
        if pm is None:
            return

        # Calculate total power from all loads
        total_power = 0.0

        if self.water_heater:
            total_power += self.water_heater.power_w

        if self.ev_charger:
            total_power += self.ev_charger.power_w

        if self.household:
            total_power += self.household.power_w

        pm.power_w = total_power

        # Simulate realistic voltage with slight variation
        variation = random.uniform(-AMS_METER_VOLTAGE_VARIATION, AMS_METER_VOLTAGE_VARIATION)
        pm.voltage_l1 = AMS_METER_NOMINAL_VOLTAGE + variation
        pm.voltage_l2 = AMS_METER_NOMINAL_VOLTAGE + random.uniform(-AMS_METER_VOLTAGE_VARIATION, AMS_METER_VOLTAGE_VARIATION)
        pm.voltage_l3 = AMS_METER_NOMINAL_VOLTAGE + random.uniform(-AMS_METER_VOLTAGE_VARIATION, AMS_METER_VOLTAGE_VARIATION)

        # Calculate currents - distribute loads across phases
        # Water heater on L1, EV charger on L2, Household split across L1 and L3
        wh_power = self.water_heater.power_w if self.water_heater else 0.0
        ev_power = self.ev_charger.power_w if self.ev_charger else 0.0
        hh_power = self.household.power_w if self.household else 0.0

        pm.current_l1 = (wh_power + hh_power * 0.5) / pm.voltage_l1
        pm.current_l2 = ev_power / pm.voltage_l2
        pm.current_l3 = (hh_power * 0.5) / pm.voltage_l3

        # Accumulate energy (import only in this simulation)
        dt_hours = UPDATE_INTERVAL_SECONDS / 3600
        pm.energy_import_kwh += (total_power / 1000) * dt_hours

    # Public methods for external control (services)

    def simulate_shower(self, liters: int) -> None:
        """Simulate hot water usage from a shower.

        Drops water heater temperature based on liters used.
        Typical relationship: 0.4°C drop per liter for 200L tank.

        Args:
            liters: Amount of hot water used in liters
        """
        if self.water_heater is None:
            _LOGGER.warning("Cannot simulate shower: water heater not enabled")
            return

        temp_drop = liters * 0.4  # 0.4°C per liter for 200L tank
        self.water_heater.current_temp = max(
            WATER_HEATER_MIN_TEMP,
            self.water_heater.current_temp - temp_drop,
        )
        _LOGGER.info(
            "Simulated shower: %d liters, temp dropped to %.1f°C",
            liters,
            self.water_heater.current_temp,
        )

    def connect_ev(self, battery_soc: float = 30.0) -> None:
        """Simulate EV connection.

        Args:
            battery_soc: Initial battery state of charge (0-100%)
        """
        if self.ev_charger is None:
            _LOGGER.warning("Cannot connect EV: charger not enabled")
            return

        self.ev_charger.is_connected = True
        self.ev_charger.battery_soc = battery_soc
        self.ev_charger.session_energy_kwh = 0.0
        self.ev_charger.status = "Connected - Waiting"
        _LOGGER.info("EV connected with %.0f%% SOC", battery_soc)

    def disconnect_ev(self) -> None:
        """Simulate EV disconnection."""
        if self.ev_charger is None:
            return

        self.ev_charger.is_connected = False
        self.ev_charger.is_charging = False
        self.ev_charger.power_w = 0.0
        self.ev_charger.status = "Disconnected"
        _LOGGER.info(
            "EV disconnected. Session energy: %.2f kWh",
            self.ev_charger.session_energy_kwh,
        )

    def start_charging(self) -> None:
        """Start EV charging if connected."""
        if self.ev_charger is None or not self.ev_charger.is_connected:
            return

        if self.ev_charger.battery_soc < 100.0:
            self.ev_charger.is_charging = True
            self.ev_charger.status = "Charging"
            _LOGGER.info("EV charging started")

    def stop_charging(self) -> None:
        """Stop EV charging."""
        if self.ev_charger is None:
            return

        self.ev_charger.is_charging = False
        if self.ev_charger.is_connected:
            self.ev_charger.status = "Connected - Waiting"
        _LOGGER.info("EV charging stopped")

    def set_ev_current_limit(self, current: int) -> None:
        """Set EV charger current limit.

        Args:
            current: Current limit in amps (6-32)
        """
        if self.ev_charger is None:
            return

        self.ev_charger.current_limit = max(6, min(32, current))
        _LOGGER.info("EV current limit set to %dA", self.ev_charger.current_limit)

    def set_water_heater_mode(self, mode: str) -> None:
        """Set water heater operating mode.

        Args:
            mode: Operating mode (Normal, Eco, Boost, Off)
        """
        if self.water_heater is None:
            return

        if mode in self.water_heater.MODE_TARGETS:
            self.water_heater.mode = mode
            self.water_heater.target_temp = self.water_heater.MODE_TARGETS[mode]
            _LOGGER.info("Water heater mode set to %s", mode)
        else:
            _LOGGER.warning("Invalid water heater mode: %s", mode)

    def set_water_heater_target(self, temp: float) -> None:
        """Set water heater target temperature.

        Args:
            temp: Target temperature in °C
        """
        if self.water_heater is None:
            return

        self.water_heater.target_temp = max(40.0, min(75.0, temp))
        _LOGGER.info("Water heater target set to %.1f°C", self.water_heater.target_temp)

    def set_presence_mode(self, mode: str) -> None:
        """Set household presence mode.

        Controls whether the household simulation behaves as occupied or empty.
        This affects power consumption patterns significantly:
        - "home": Full household activity patterns
        - "away": Standby loads only (fridge, router, etc.)
        - "vacation": Extended away mode

        Args:
            mode: Presence mode ("home", "away", "vacation")
        """
        if self.household is None:
            _LOGGER.warning("Cannot set presence: household not enabled")
            return

        if mode not in self.household.PRESENCE_MODES:
            _LOGGER.warning("Invalid presence mode: %s", mode)
            return

        old_mode = self.household.presence_mode
        self.household.presence_mode = mode
        _LOGGER.info(
            "Presence mode changed: %s -> %s (building: %s)",
            old_mode,
            mode,
            self.household.building_type,
        )

    def set_building_type(self, building_type: str) -> None:
        """Set building type (home or cabin).

        Controls the consumption patterns and base loads:
        - "home": Primary residence with full appliances
        - "cabin": Hytte/weekend cabin with different patterns

        Args:
            building_type: Building type ("home", "cabin")
        """
        if self.household is None:
            _LOGGER.warning("Cannot set building type: household not enabled")
            return

        if building_type not in self.household.BUILDING_TYPES:
            _LOGGER.warning("Invalid building type: %s", building_type)
            return

        old_type = self.household.building_type
        self.household.building_type = building_type
        _LOGGER.info("Building type changed: %s -> %s", old_type, building_type)

    def set_occupants(self, count: int) -> None:
        """Set the number of occupants.

        Scales power consumption proportionally:
        - 1 person: ~25% of baseline (4 people)
        - 2 people: ~50% of baseline
        - 4 people: 100% baseline
        - 6 people: ~150% of baseline

        Args:
            count: Number of occupants (1-8)
        """
        if self.household is None:
            _LOGGER.warning("Cannot set occupants: household not enabled")
            return

        self.household.occupants = max(1, min(8, count))
        _LOGGER.info("Occupants set to %d", self.household.occupants)
