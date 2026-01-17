"""Switch platform for Climate React integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate_react import ClimateReactController
from .const import CONF_CLIMATE_ENTITY, DATA_COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React switch from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    
    async_add_entities([ClimateReactSwitch(controller, entry)], True)


class ClimateReactSwitch(SwitchEntity):
    """Switch to enable/disable Climate React."""

    _attr_has_entity_name = True
    _attr_name = "Climate React"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self._controller = controller
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Climate React - {entry.data[CONF_CLIMATE_ENTITY]}",
            "manufacturer": "Climate React",
            "model": "Climate Automation Controller",
            "sw_version": "0.1.0",
        }

    @property
    def is_on(self) -> bool:
        """Return true if Climate React is enabled."""
        return self._controller.enabled

    @property
    def icon(self) -> str:
        """Return the icon for the switch."""
        return "mdi:thermostat-auto" if self.is_on else "mdi:thermostat-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on Climate React."""
        await self._controller.async_enable()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off Climate React."""
        await self._controller.async_disable()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        config = self._controller.config
        attrs = {
            "climate_entity": self._controller.climate_entity,
            "temperature_sensor": self._controller.temperature_sensor,
            "min_temp": config.get("min_temp_threshold"),
            "max_temp": config.get("max_temp_threshold"),
        }
        
        if self._controller.humidity_sensor:
            attrs["humidity_sensor"] = self._controller.humidity_sensor
            attrs["min_humidity"] = config.get("min_humidity_threshold")
            attrs["max_humidity"] = config.get("max_humidity_threshold")
        
        return attrs
