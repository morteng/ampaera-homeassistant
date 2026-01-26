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

# Water heater operation modes (for entity interface)
WH_MODE_COMFORT = "Normal"  # Standard heating mode
WH_MODE_ECO = "Eco"
WH_MODE_BOOST = "Boost"
WH_MODE_OFF = "Off"

# Water heater entity temperature limits (more restrictive than simulation)
MIN_WATER_TEMP = 40.0
MAX_WATER_TEMP = 85.0
DEFAULT_WATER_TEMP = 65.0

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
    0: (100, 150),  # Night - minimal
    1: (50, 100),
    2: (50, 50),
    3: (50, 50),
    4: (50, 50),
    5: (100, 50),
    6: (800, 200),  # Weekday morning rush, weekend sleep
    7: (1200, 300),  # Breakfast, getting ready
    8: (400, 600),  # Leave for work/school, weekend wake
    9: (200, 800),  # House empty weekday, weekend breakfast
    10: (200, 600),
    11: (200, 800),  # Weekend cooking starts
    12: (300, 1000),  # Lunch
    13: (200, 600),
    14: (200, 500),
    15: (300, 600),
    16: (500, 800),  # Kids home from school
    17: (1500, 1200),  # Dinner cooking peak
    18: (1800, 1500),  # Peak cooking
    19: (1000, 1000),  # Dinner, TV
    20: (800, 800),  # Evening entertainment
    21: (600, 700),
    22: (400, 500),  # Winding down
    23: (200, 300),  # Going to bed
}

# Home patterns when family is AWAY (at cabin)
# Only standby loads: fridge, freezer, router, standby devices, frost protection
HOME_AWAY_PATTERNS = {
    # Hour: (weekday_load, weekend_load) - minimal variation
    0: (50, 50),
    1: (50, 50),
    2: (50, 50),
    3: (50, 50),
    4: (50, 50),
    5: (50, 50),
    6: (50, 50),
    7: (50, 50),
    8: (50, 50),
    9: (50, 50),
    10: (50, 50),
    11: (50, 50),
    12: (50, 50),
    13: (50, 50),
    14: (50, 50),
    15: (50, 50),
    16: (50, 50),
    17: (50, 50),
    18: (50, 50),
    19: (50, 50),
    20: (50, 50),
    21: (50, 50),
    22: (50, 50),
    23: (50, 50),
}

# Cabin (hytte) patterns when EMPTY - frost protection only
CABIN_EMPTY_PATTERNS = {
    # Hour: (weekday_load, weekend_load) - just frost protection, minimal standby
    0: (20, 20),
    1: (20, 20),
    2: (20, 20),
    3: (20, 20),
    4: (20, 20),
    5: (20, 20),
    6: (20, 20),
    7: (20, 20),
    8: (20, 20),
    9: (20, 20),
    10: (20, 20),
    11: (20, 20),
    12: (20, 20),
    13: (20, 20),
    14: (20, 20),
    15: (20, 20),
    16: (20, 20),
    17: (20, 20),
    18: (20, 20),
    19: (20, 20),
    20: (20, 20),
    21: (20, 20),
    22: (20, 20),
    23: (20, 20),
}

# Cabin (hytte) patterns when OCCUPIED - weekend visit style
# Norwegian cabin visits: arrive Friday evening, leave Sunday afternoon
CABIN_OCCUPIED_PATTERNS = {
    # Hour: (weekday_load, weekend_load)
    0: (100, 150),  # Night - wood stove supplements
    1: (50, 100),
    2: (50, 50),
    3: (50, 50),
    4: (50, 50),
    5: (50, 50),
    6: (50, 100),  # Sleep in at cabin
    7: (100, 200),
    8: (200, 500),  # Wake up, breakfast
    9: (300, 800),  # Coffee, breakfast, sauna heating
    10: (400, 700),  # Activities
    11: (300, 900),  # Lunch prep
    12: (500, 1200),  # Lunch - more cooking at cabin
    13: (300, 600),  # Relax after lunch
    14: (300, 500),  # Afternoon activities
    15: (400, 600),
    16: (500, 800),  # Afternoon fika/coffee
    17: (800, 1200),  # Dinner prep - cabin cooking
    18: (1200, 1500),  # Dinner
    19: (800, 1000),  # Evening activities
    20: (600, 800),  # Sauna, relaxation
    21: (500, 700),  # Wind down
    22: (300, 500),  # Preparing for bed
    23: (200, 300),
}

# Base load by building type (fridge, always-on devices)
HOUSEHOLD_BASE_LOAD_HOME_W = 250.0  # Primary home: fridge, freezer, router, standby
HOUSEHOLD_BASE_LOAD_CABIN_W = 80.0  # Cabin: small fridge only when occupied
HOUSEHOLD_BASE_LOAD_CABIN_EMPTY_W = 30.0  # Cabin empty: frost protection circuit only

# Simulation timing
UPDATE_INTERVAL_SECONDS = 10
