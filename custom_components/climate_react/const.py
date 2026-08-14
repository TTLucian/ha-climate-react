"""Constants for the Climate React integration."""

DOMAIN = "climate_react"

# Configuration keys
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_USE_EXTERNAL_TEMP_SENSOR = "use_external_temp_sensor"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_MIN_TEMP = "min_temp_threshold"
CONF_MAX_TEMP = "max_temp_threshold"
CONF_MODE_LOW_TEMP = "mode_low_temp"
CONF_MODE_HIGH_TEMP = "mode_high_temp"
CONF_FAN_LOW_TEMP = "fan_low_temp"
CONF_FAN_HIGH_TEMP = "fan_high_temp"
CONF_SWING_LOW_TEMP = "swing_low_temp"
CONF_SWING_HIGH_TEMP = "swing_high_temp"
CONF_SWING_HORIZONTAL_LOW_TEMP = "swing_horizontal_low_temp"
CONF_SWING_HORIZONTAL_HIGH_TEMP = "swing_horizontal_high_temp"
CONF_TEMP_LOW_TEMP = "temp_low_temp"
CONF_TEMP_HIGH_TEMP = "temp_high_temp"
CONF_DELAY_BETWEEN_COMMANDS = "delay_between_commands_ms"
CONF_MIN_RUN_TIME = "min_run_time_minutes"
CONF_ENABLED = "enabled"
CONF_ENABLE_LIGHT_CONTROL = "enable_light_control"
CONF_LIGHT_ENTITY = "light_entity"
CONF_LIGHT_BEHAVIOR = "light_behavior"
CONF_LIGHT_SELECT_ON_OPTION = "light_select_on_option"
CONF_LIGHT_SELECT_OFF_OPTION = "light_select_off_option"
CONF_LAST_MODE_CHANGE_TIME = "last_mode_change_time"
CONF_LAST_SET_HVAC_MODE = "last_set_hvac_mode"
CONF_TIMER_MINUTES = "timer_minutes"
CONF_TIMER_EXPIRY = "timer_expiry"

# Default values
DEFAULT_MIN_TEMP = 18.0
DEFAULT_MAX_TEMP = 26.0
DEFAULT_MODE_LOW_TEMP = "heat"
DEFAULT_MODE_HIGH_TEMP = "cool"
DEFAULT_FAN_MODE = "auto"
DEFAULT_SWING_MODE = "off"
DEFAULT_SWING_HORIZONTAL_MODE = "off"
DEFAULT_TEMP_LOW_TEMP = 16.0
DEFAULT_TEMP_HIGH_TEMP = 30.0
DEFAULT_DELAY_BETWEEN_COMMANDS = 500
DEFAULT_MIN_RUN_TIME = 5
DEFAULT_ENABLED = False
DEFAULT_ENABLE_LIGHT_CONTROL = False
DEFAULT_LIGHT_BEHAVIOR = "unchanged"
DEFAULT_LIGHT_SELECT_ON_OPTION = "on"
DEFAULT_LIGHT_SELECT_OFF_OPTION = "off"
DEFAULT_USE_EXTERNAL_TEMP_SENSOR = False

# Light behavior options
LIGHT_BEHAVIOR_ON = "on"
LIGHT_BEHAVIOR_OFF = "off"
LIGHT_BEHAVIOR_UNCHANGED = "unchanged"
DEFAULT_TIMER_MINUTES = 0

# HVAC modes
MODE_OFF = "off"
MODE_NONE = "none"  # Sentinel: do nothing when threshold is crossed
MODE_HEAT = "heat"
MODE_COOL = "cool"
MODE_DRY = "dry"
MODE_AUTO = "auto"
MODE_FAN_ONLY = "fan_only"

# Data keys
DATA_COORDINATOR = "coordinator"

# Circuit breaker constants
CIRCUIT_BREAKER_MAX_FAILURES = 3
CIRCUIT_BREAKER_TIMEOUT_SECONDS = 300

# Service call retry constants
MAX_RETRY_ATTEMPTS = 3
BASE_RETRY_DELAY_SECONDS = 1

# State logging constants
MAX_STATE_LOG_ENTRIES = 20

# Capability cache constants
CAPABILITY_CACHE_DURATION_SECONDS = 300

# Task throttling constants
MAX_CONCURRENT_BACKGROUND_TASKS = 10

# Manual override detection grace period (seconds)
# After a climate command, ACs often report transient states (e.g. a brief
# fan_only before cool) or take a moment to echo all attributes (fan mode,
# swing mode, target temperature). During this window, state changes are
# re-baselined rather than treated as manual overrides, preventing spurious
# automation disable right after the AC turns on.
MANUAL_OVERRIDE_GRACE_SECONDS = 15
