"""Number platform for Climate React integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate_react import ClimateReactController
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DELAY_BETWEEN_COMMANDS,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_MAX_HUMIDITY,
    CONF_MAX_TEMP,
    CONF_MIN_HUMIDITY,
    CONF_MIN_RUN_TIME,
    CONF_MIN_TEMP,
    CONF_TEMP_HIGH_HUMIDITY,
    CONF_TEMP_HIGH_TEMP,
    CONF_TEMP_LOW_TEMP,
    CONF_USE_HUMIDITY,
    DATA_COORDINATOR,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_MIN_RUN_TIME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React number entities from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    
    numbers = [
        ClimateReactMinTempNumber(controller, entry),
        ClimateReactMaxTempNumber(controller, entry),
        ClimateReactTempLowTempNumber(controller, entry),
        ClimateReactTempHighTempNumber(controller, entry),
        ClimateReactDelayBetweenCommandsNumber(controller, entry),
        ClimateReactMinRunTimeNumber(controller, entry),
    ]
    
    if entry.data.get(CONF_USE_HUMIDITY, False):
        # Min humidity only shown if humidifier is configured
        if entry.data.get(CONF_HUMIDIFIER_ENTITY):
            numbers.append(ClimateReactMinHumidityNumber(controller, entry))
        
        numbers.extend([
            ClimateReactMaxHumidityNumber(controller, entry),
            ClimateReactTempHighHumidityNumber(controller, entry),
        ])
    
    async_add_entities(numbers, True)


class ClimateReactBaseNumber(NumberEntity):
    """Base class for Climate React number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        self._controller = controller
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
        }

    async def async_set_native_value(self, value: float) -> None:
        """Update the threshold value."""
        # Update the config entry options
        new_options = {**self._entry.options}
        new_options[self._config_key] = value
        
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        
        # Update controller
        await self._controller.async_update_thresholds({self._service_key: value})
        
        # Update local state
        self._attr_native_value = value
        self.async_write_ha_state()


class ClimateReactMinTempNumber(ClimateReactBaseNumber):
    """Number entity for minimum temperature threshold."""

    _attr_name = "Minimum Temperature"
    _attr_icon = "mdi:thermometer-low"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.5
    _config_key = CONF_MIN_TEMP
    _service_key = "min_temp"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the min temp number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_min_temp"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_MIN_TEMP, 18.0)


class ClimateReactMaxTempNumber(ClimateReactBaseNumber):
    """Number entity for maximum temperature threshold."""

    _attr_name = "Maximum Temperature"
    _attr_icon = "mdi:thermometer-high"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.5
    _config_key = CONF_MAX_TEMP
    _service_key = "max_temp"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the max temp number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_max_temp"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_MAX_TEMP, 26.0)


class ClimateReactMinHumidityNumber(ClimateReactBaseNumber):
    """Number entity for minimum humidity threshold."""

    _attr_name = "Minimum Humidity"
    _attr_icon = "mdi:water-percent"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _config_key = CONF_MIN_HUMIDITY
    _service_key = "min_humidity"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the min humidity number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_min_humidity"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_MIN_HUMIDITY, 30.0)


class ClimateReactMaxHumidityNumber(ClimateReactBaseNumber):
    """Number entity for maximum humidity threshold."""

    _attr_name = "Maximum Humidity"
    _attr_icon = "mdi:water-percent-alert"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _config_key = CONF_MAX_HUMIDITY
    _service_key = "max_humidity"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the max humidity number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_max_humidity"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_MAX_HUMIDITY, 60.0)


class ClimateReactTempLowTempNumber(ClimateReactBaseNumber):
    """Number entity for target temperature at low threshold."""

    _attr_name = "Target Temperature Low"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.5
    _config_key = CONF_TEMP_LOW_TEMP
    _service_key = "temp_low"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the target temp low number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_temp_low_temp"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_TEMP_LOW_TEMP, 16.0)


class ClimateReactTempHighTempNumber(ClimateReactBaseNumber):
    """Number entity for target temperature at high threshold."""

    _attr_name = "Target Temperature High"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.5
    _config_key = CONF_TEMP_HIGH_TEMP
    _service_key = "temp_high"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the target temp high number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_temp_high_temp"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_TEMP_HIGH_TEMP, 30.0)


class ClimateReactTempHighHumidityNumber(ClimateReactBaseNumber):
    """Number entity for target temperature at high humidity."""

    _attr_name = "Target Temperature High Humidity"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 0.5
    _config_key = CONF_TEMP_HIGH_HUMIDITY
    _service_key = "temp_humidity"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the target temp humidity number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_temp_high_humidity"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_TEMP_HIGH_HUMIDITY, 24.0)


class ClimateReactDelayBetweenCommandsNumber(ClimateReactBaseNumber):
    """Number entity for delay between commands."""

    _attr_name = "Delay Between Commands (ms)"
    _attr_icon = "mdi:clock"
    _attr_native_unit_of_measurement = "ms"
    _attr_native_min_value = 0
    _attr_native_max_value = 5000
    _attr_native_step = 100
    _config_key = CONF_DELAY_BETWEEN_COMMANDS
    _service_key = "delay_between_commands"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the delay between commands number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_delay_between_commands"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_DELAY_BETWEEN_COMMANDS, DEFAULT_DELAY_BETWEEN_COMMANDS)


class ClimateReactMinRunTimeNumber(ClimateReactBaseNumber):
    """Number entity for minimum runtime between mode changes."""

    _attr_name = "Minimum Run Time (minutes)"
    _attr_icon = "mdi:timer"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _config_key = CONF_MIN_RUN_TIME
    _service_key = "min_run_time"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the min run time number."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_min_run_time"
        config = {**entry.data, **entry.options}
        self._attr_native_value = config.get(CONF_MIN_RUN_TIME, DEFAULT_MIN_RUN_TIME)
