"""Switch platform for Climate React integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate_react import ClimateReactController
from .const import (
    DATA_COORDINATOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React switch from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    entities: list[SwitchEntity] = [ClimateReactSwitch(controller, entry)]

    # Add light control switch only if a light entity is configured
    if controller.light_entity:
        entities.append(ClimateReactLightControlSwitch(controller, entry))

    async_add_entities(entities, True)


class ClimateReactSwitch(SwitchEntity):
    """Switch to enable/disable Climate React."""

    _attr_has_entity_name = True
    _attr_name = "Climate React"
    _attr_should_poll = False

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self._controller = controller
        self._entry = entry
        room_name = controller.get_room_name()
        self._attr_unique_id = f"climate_react_{room_name}"
        self._attr_icon = "mdi:thermostat-off"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
        }

    @property
    def is_on(self) -> bool:
        """Return true if Climate React is enabled."""
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on Climate React."""
        self._attr_icon = "mdi:thermostat-auto"
        await self._controller.async_enable()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off Climate React."""
        self._attr_icon = "mdi:thermostat-off"
        await self._controller.async_disable()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        from .const import (
            CONF_MAX_HUMIDITY,
            CONF_MAX_TEMP,
            CONF_MIN_HUMIDITY,
            CONF_MIN_TEMP,
        )

        config = self._controller.config
        attrs = {
            "climate_entity": self._controller.climate_entity,
            "temperature_sensor": self._controller.temperature_sensor,
            "min_temp": config.get(CONF_MIN_TEMP),
            "max_temp": config.get(CONF_MAX_TEMP),
        }

        # Add current temperature if available
        if self._controller._last_temp is not None:
            attrs["current_temperature"] = round(self._controller._last_temp, 1)

        if self._controller.humidity_sensor:
            attrs["humidity_sensor"] = self._controller.humidity_sensor
            attrs["min_humidity"] = config.get(CONF_MIN_HUMIDITY)
            attrs["max_humidity"] = config.get(CONF_MAX_HUMIDITY)

        # Add current humidity if available
        if (
            self._controller.humidity_sensor
            and self._controller._last_humidity is not None
        ):
            attrs["current_humidity"] = round(self._controller._last_humidity, 1)

        return attrs


class ClimateReactLightControlSwitch(SwitchEntity):
    """Switch to enable/disable display light control."""

    _attr_has_entity_name = True
    _attr_name = "Light Control"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the light control switch."""
        self._controller = controller
        self._entry = entry
        room_name = controller.get_room_name()
        self._attr_unique_id = f"climate_react_{room_name}_light_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
        }

    @property
    def is_on(self) -> bool:
        """Return true if light control is enabled."""
        return self._controller.light_control_enabled

    @property
    def icon(self) -> str:
        """Return the icon for the switch."""
        return "mdi:lightbulb-on-outline" if self.is_on else "mdi:lightbulb-off-outline"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable light control."""
        await self._controller.async_set_light_control_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable light control."""
        await self._controller.async_set_light_control_enabled(False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "light_entity": self._controller.light_entity,
        }
