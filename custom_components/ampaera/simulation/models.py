"""Device state models for Ampæra Simulation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    EV_CHARGER_DEFAULT_CURRENT,
    WATER_HEATER_DEFAULT_TARGET,
)


@dataclass
class WaterHeaterState:
    """Water heater simulation state.

    Tracks temperature, heating status, power consumption, and energy usage.
    Physics simulation handles temperature changes based on heating state
    and ambient heat loss.
    """

    current_temp: float = 45.0
    target_temp: float = WATER_HEATER_DEFAULT_TARGET
    is_heating: bool = False
    mode: str = "Normal"  # Normal, Eco, Boost, Off
    power_w: float = 0.0
    energy_kwh: float = 0.0

    # Mode-specific target temperatures
    MODE_TARGETS: dict[str, float] = field(
        default_factory=lambda: {
            "Normal": 65.0,
            "Eco": 55.0,
            "Boost": 75.0,
            "Off": 0.0,
        }
    )


@dataclass
class EVChargerState:
    """EV charger simulation state.

    Simulates a single-phase EV charger with adjustable current limit.
    Tracks connection status, charging state, and energy delivered.
    """

    is_connected: bool = False
    is_charging: bool = False
    status: str = "Disconnected"  # Disconnected, Connected - Waiting, Charging, Complete, Error
    battery_soc: float = 0.0  # 0-100%
    current_limit: int = EV_CHARGER_DEFAULT_CURRENT  # 6-32A
    power_w: float = 0.0
    session_energy_kwh: float = 0.0
    total_energy_kwh: float = 0.0

    # Status options for select entity
    STATUS_OPTIONS: list[str] = field(
        default_factory=lambda: [
            "Disconnected",
            "Connected - Waiting",
            "Charging",
            "Complete",
            "Error",
        ]
    )


@dataclass
class PowerMeterState:
    """AMS power meter simulation state.

    Simulates a 3-phase power meter with realistic voltage readings.
    Power is calculated from connected loads (water heater, EV charger).
    """

    power_w: float = 0.0
    voltage_l1: float = 230.0
    voltage_l2: float = 230.0
    voltage_l3: float = 230.0
    current_l1: float = 0.0
    current_l2: float = 0.0
    current_l3: float = 0.0
    energy_import_kwh: float = 0.0
    energy_export_kwh: float = 0.0
    # AMS meter period registers (reset at period boundaries)
    hour_energy_kwh: float = 0.0  # Running total for current hour
    day_energy_kwh: float = 0.0  # Running total for current day
    month_energy_kwh: float = 0.0  # Running total for current month


@dataclass
class HouseholdState:
    """Household background load simulation state.

    Generates realistic varying power consumption representing typical
    Norwegian household appliances (dishwasher, washing machine, cooking,
    TV, lights, etc.) without individual entity control.

    Load varies by:
    - Time of day (morning/evening peaks)
    - Day of week (weekday vs weekend patterns)
    - Presence mode (home, away, vacation)
    - Building type (home, cabin)
    - Random variations for realism
    """

    power_w: float = 0.0
    energy_kwh: float = 0.0
    # Current activity description for display
    activity: str = "Idle"
    # Presence mode: "home" (family present), "away" (temporarily out), "vacation" (long-term away)
    presence_mode: str = "home"
    # Building type: "home" (primary residence) or "cabin" (hytte - weekend/holiday use)
    building_type: str = "home"
    # Number of occupants (affects load scaling)
    occupants: int = 4

    # Presence mode options
    PRESENCE_MODES: list[str] = field(default_factory=lambda: ["home", "away", "vacation"])
    # Building type options
    BUILDING_TYPES: list[str] = field(default_factory=lambda: ["home", "cabin"])
