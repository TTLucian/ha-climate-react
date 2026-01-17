"""Sensor platform for Climate React integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .climate_react import ClimateReactController
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_MAX_HUMIDITY,
    CONF_MAX_TEMP,
    CONF_MIN_HUMIDITY,
    CONF_MIN_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_USE_HUMIDITY,
    DATA_COORDINATOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React sensors from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    
    sensors = [
        ClimateReactStatusSensor(controller, entry),
        ClimateReactTemperatureSensor(controller, entry),
    ]
    
    if entry.data.get(CONF_HUMIDITY_SENSOR):
        sensors.append(ClimateReactHumiditySensor(controller, entry))
    
    async_add_entities(sensors, True)


class ClimateReactBaseSensor(SensorEntity):
    """Base class for Climate React sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._controller = controller
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Climate React - {entry.data[CONF_CLIMATE_ENTITY]}",
            "manufacturer": "Climate React",
            "model": "Climate Automation Controller",
            "sw_version": "0.1.0",
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._controller.enabled


class ClimateReactStatusSensor(ClimateReactBaseSensor):
    """Sensor showing current Climate React status."""

    _attr_name = "Status"
    _attr_icon = "mdi:information-outline"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the status sensor."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if not self._controller.enabled:
            return "disabled"
        
        last_temp = self._controller._last_temp
        last_humidity = self._controller._last_humidity
        config = self._controller.config
        
        if last_temp is None:
            return "waiting"
        
        min_temp = config.get(CONF_MIN_TEMP)
        max_temp = config.get(CONF_MAX_TEMP)
        
        # Check temperature thresholds
        if min_temp is not None and last_temp < min_temp:
            return "heating"
        elif max_temp is not None and last_temp > max_temp:
            return "cooling"
        
        # Check humidity thresholds if enabled
        if self._controller.humidity_sensor and last_humidity is not None:
            max_humidity = config.get(CONF_MAX_HUMIDITY)
            if max_humidity is not None and last_humidity > max_humidity:
                return "dehumidifying"
            
            min_humidity = config.get(CONF_MIN_HUMIDITY)
            if min_humidity is not None and last_humidity < min_humidity:
                return "humidifying"
        
        return "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        config = self._controller.config
        attrs = {
            "climate_entity": self._controller.climate_entity,
        }
        
        # Temperature info
        if self._controller._last_temp is not None:
            attrs["temperature"] = round(self._controller._last_temp, 1)
            attrs["temperature_min"] = config.get(CONF_MIN_TEMP)
            attrs["temperature_max"] = config.get(CONF_MAX_TEMP)
        
        # Humidity info
        if self._controller.humidity_sensor and self._controller._last_humidity is not None:
            attrs["humidity"] = round(self._controller._last_humidity, 1)
            attrs["humidity_min"] = config.get(CONF_MIN_HUMIDITY)
            attrs["humidity_max"] = config.get(CONF_MAX_HUMIDITY)
        
        # Mode info
        attrs["mode_low_temp"] = config.get("mode_low_temp")
        attrs["mode_high_temp"] = config.get("mode_high_temp")
        if self._controller.humidity_sensor:
            attrs["mode_high_humidity"] = config.get("mode_high_humidity")
        
        return attrs


class ClimateReactTemperatureSensor(ClimateReactBaseSensor):
    """Sensor showing current temperature reading."""

    _attr_name = "Current Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the temperature sensor."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_temperature"
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Track the temperature sensor
        self._unsub = async_track_state_change_event(
            self.hass,
            [self._entry.data[CONF_TEMPERATURE_SENSOR]],
            self._async_sensor_changed,
        )
        
        # Set initial value
        state = self.hass.states.get(self._entry.data[CONF_TEMPERATURE_SENSOR])
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(state.state)
            except (ValueError, TypeError):
                pass

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._unsub:
            self._unsub()

    @callback
    async def _async_sensor_changed(self, event) -> None:
        """Handle sensor state changes."""
        new_state = event.data.get("new_state")
        if new_state and new_state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(new_state.state)
                self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        config = self._controller.config
        return {
            "min_threshold": config.get("min_temp_threshold"),
            "max_threshold": config.get("max_temp_threshold"),
            "source_sensor": self._entry.data[CONF_TEMPERATURE_SENSOR],
        }


class ClimateReactHumiditySensor(ClimateReactBaseSensor):
    """Sensor showing current humidity reading."""

    _attr_name = "Current Humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the humidity sensor."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_humidity"
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Track the humidity sensor
        humidity_sensor = self._entry.data.get(CONF_HUMIDITY_SENSOR)
        if humidity_sensor:
            self._unsub = async_track_state_change_event(
                self.hass,
                [humidity_sensor],
                self._async_sensor_changed,
            )
            
            # Set initial value
            state = self.hass.states.get(humidity_sensor)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    self._attr_native_value = float(state.state)
                except (ValueError, TypeError):
                    pass

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._unsub:
            self._unsub()

    @callback
    async def _async_sensor_changed(self, event) -> None:
        """Handle sensor state changes."""
        new_state = event.data.get("new_state")
        if new_state and new_state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(new_state.state)
                self.async_write_ha_state()
            except (ValueError, TypeError):
                pass

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        config = self._controller.config
        return {
            "min_threshold": config.get("min_humidity_threshold"),
            "max_threshold": config.get("max_humidity_threshold"),
            "source_sensor": self._entry.data.get(CONF_HUMIDITY_SENSOR),
        }
