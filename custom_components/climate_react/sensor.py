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
    ]
    
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
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
            "hw_version": "0.1.0",
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._controller.enabled


class ClimateReactStatusSensor(ClimateReactBaseSensor):
    """Sensor showing current Climate React status."""

    _attr_name = "Status"
    _attr_icon = "mdi:information-outline"

    @property
    def available(self) -> bool:
        """Return True if entity is available (always available)."""
        return True

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the status sensor."""
        super().__init__(controller, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if not self._controller.enabled:
            return "off"
        
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

