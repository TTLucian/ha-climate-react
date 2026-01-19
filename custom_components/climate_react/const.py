"""Constants for the Climate React integration."""

DOMAIN = "climate_react"

# Configuration keys
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_USE_EXTERNAL_TEMP_SENSOR = "use_external_temp_sensor"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_USE_HUMIDITY = "use_humidity"
CONF_USE_EXTERNAL_HUMIDITY_SENSOR = "use_external_humidity_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_HUMIDIFIER_ENTITY = "humidifier_entity"
CONF_MIN_TEMP = "min_temp_threshold"
CONF_MAX_TEMP = "max_temp_threshold"
CONF_MIN_HUMIDITY = "min_humidity_threshold"
CONF_MAX_HUMIDITY = "max_humidity_threshold"
CONF_MODE_LOW_TEMP = "mode_low_temp"
CONF_MODE_HIGH_TEMP = "mode_high_temp"
CONF_MODE_HIGH_HUMIDITY = "mode_high_humidity"
CONF_FAN_LOW_TEMP = "fan_low_temp"
CONF_FAN_HIGH_TEMP = "fan_high_temp"
CONF_FAN_HIGH_HUMIDITY = "fan_high_humidity"
CONF_SWING_LOW_TEMP = "swing_low_temp"
CONF_SWING_HIGH_TEMP = "swing_high_temp"
CONF_SWING_HIGH_HUMIDITY = "swing_high_humidity"
CONF_SWING_HORIZONTAL_LOW_TEMP = "swing_horizontal_low_temp"
CONF_SWING_HORIZONTAL_HIGH_TEMP = "swing_horizontal_high_temp"
CONF_SWING_HORIZONTAL_HIGH_HUMIDITY = "swing_horizontal_high_humidity"
CONF_TEMP_LOW_TEMP = "temp_low_temp"
CONF_TEMP_HIGH_TEMP = "temp_high_temp"
CONF_TEMP_HIGH_HUMIDITY = "temp_high_humidity"
CONF_DELAY_BETWEEN_COMMANDS = "delay_between_commands_ms"
CONF_MIN_RUN_TIME = "min_run_time_minutes"
CONF_ENABLED = "enabled"
CONF_ENABLE_LIGHT_CONTROL = "enable_light_control"
CONF_LIGHT_ENTITY = "light_entity"
CONF_LIGHT_BEHAVIOR = "light_behavior"
CONF_TIMER_MINUTES = "timer_minutes"

# Default values
DEFAULT_MIN_TEMP = 18.0
DEFAULT_MAX_TEMP = 26.0
DEFAULT_MIN_HUMIDITY = 30.0
DEFAULT_MAX_HUMIDITY = 60.0
DEFAULT_MODE_LOW_TEMP = "heat"
DEFAULT_MODE_HIGH_TEMP = "cool"
DEFAULT_MODE_HIGH_HUMIDITY = "dry"
DEFAULT_FAN_MODE = "auto"
DEFAULT_SWING_MODE = "off"
DEFAULT_TEMP_LOW_TEMP = 16.0
DEFAULT_TEMP_HIGH_TEMP = 30.0
DEFAULT_TEMP_HIGH_HUMIDITY = 24.0
DEFAULT_DELAY_BETWEEN_COMMANDS = 500
DEFAULT_MIN_RUN_TIME = 5
DEFAULT_ENABLED = False
DEFAULT_ENABLE_LIGHT_CONTROL = False
DEFAULT_LIGHT_BEHAVIOR = "unchanged"
DEFAULT_USE_EXTERNAL_TEMP_SENSOR = False
DEFAULT_USE_HUMIDITY = False
DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR = False

# Light behavior options
LIGHT_BEHAVIOR_ON = "on"
LIGHT_BEHAVIOR_OFF = "off"
LIGHT_BEHAVIOR_UNCHANGED = "unchanged"
DEFAULT_TIMER_MINUTES = 0

# HVAC modes
MODE_OFF = "off"
MODE_HEAT = "heat"
MODE_COOL = "cool"
MODE_DRY = "dry"
MODE_AUTO = "auto"
MODE_FAN_ONLY = "fan_only"

# Service names
SERVICE_ENABLE = "enable"
SERVICE_DISABLE = "disable"
SERVICE_UPDATE_THRESHOLDS = "update_thresholds"

# Data keys
DATA_COORDINATOR = "coordinator"
DATA_UNSUB = "unsub"
