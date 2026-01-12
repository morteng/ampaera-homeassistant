"""Constants for the Ampæra Simulation integration."""

from __future__ import annotations

DOMAIN = "ampaera_sim"

# Configuration
CONF_DEVICES = "devices"

# Device types
DEVICE_WATER_HEATER = "water_heater"
DEVICE_EV_CHARGER = "ev_charger"
DEVICE_AMS_METER = "ams_meter"
DEVICE_HOUSEHOLD = "household"

# Device info
MANUFACTURER = "Ampæra Simulation"

# Water heater constants (typical Norwegian 200L tank)
# Research: Norwegian varmtvannsbereder typically 2000W for 200L tanks
# (3000W more common for 300L tanks)
WATER_HEATER_MODEL = "SIM-WH-200L"
WATER_HEATER_TANK_SIZE_L = 200
WATER_HEATER_POWER_W = 2000.0
WATER_HEATER_HEAT_RATE_C_PER_HOUR = 10.0  # Temperature rise per hour at 2kW
WATER_HEATER_HEAT_LOSS_C_PER_HOUR = 0.5  # Ambient heat loss per hour
WATER_HEATER_MIN_TEMP = 15.0
WATER_HEATER_MAX_TEMP = 85.0
WATER_HEATER_DEFAULT_TARGET = 65.0
WATER_HEATER_HYSTERESIS = 2.0  # Start heating when temp falls this much below target

# EV charger constants
EV_CHARGER_MODEL = "SIM-EVC-32A"
EV_CHARGER_VOLTAGE = 230  # Single-phase voltage
EV_CHARGER_MAX_CURRENT = 32
EV_CHARGER_MIN_CURRENT = 6
EV_CHARGER_DEFAULT_CURRENT = 16
EV_CHARGER_EFFICIENCY = 0.95  # Charging efficiency

# AMS meter constants
AMS_METER_MODEL = "SIM-AMS-HAN"
AMS_METER_NOMINAL_VOLTAGE = 230.0
AMS_METER_VOLTAGE_VARIATION = 3.0  # Typical ±3V variation

# Household simulation constants
# Simulates background household load (appliances, lights, entertainment)
HOUSEHOLD_MODEL = "SIM-HOUSEHOLD"
HOUSEHOLD_BASE_LOAD_W = 250.0  # Always-on: fridge, standby devices, router
HOUSEHOLD_PEAK_LOAD_W = 3000.0  # Maximum additional load from appliances

# Typical Norwegian household load patterns (W above base load)
# Based on: dishwasher, washing machine, cooking, TV, lights, etc.
HOUSEHOLD_PATTERNS = {
    # Hour: (weekday_load, weekend_load)
    0: (100, 150),    # Night - minimal
    1: (50, 100),
    2: (50, 50),
    3: (50, 50),
    4: (50, 50),
    5: (100, 50),
    6: (800, 200),    # Weekday morning rush, weekend sleep
    7: (1200, 300),   # Breakfast, getting ready
    8: (400, 600),    # Leave for work/school, weekend wake
    9: (200, 800),    # House empty weekday, weekend breakfast
    10: (200, 600),
    11: (200, 800),   # Weekend cooking starts
    12: (300, 1000),  # Lunch
    13: (200, 600),
    14: (200, 500),
    15: (300, 600),
    16: (500, 800),   # Kids home from school
    17: (1500, 1200), # Dinner cooking peak
    18: (1800, 1500), # Peak cooking
    19: (1000, 1000), # Dinner, TV
    20: (800, 800),   # Evening entertainment
    21: (600, 700),
    22: (400, 500),   # Winding down
    23: (200, 300),   # Going to bed
}

# Simulation timing
UPDATE_INTERVAL_SECONDS = 10
