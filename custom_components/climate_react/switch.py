"""Switch platform for Climate React integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
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
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[SwitchEntity] = [ClimateReactSwitch(controller, entry)]
    async_add_entities(entities, True)


class ClimateReactSwitch(SwitchEntity):
    """Switch to enable/disable Climate React control."""

    _attr_has_entity_name = True
    # Keep the entity name short; with _attr_has_entity_name = True the device
    # name (e.g. "Climate React Study") is prepended automatically, so a long
    # name here would produce "Climate React Study Climate React Control".
    _attr_name = "Control"
    _attr_should_poll = False

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self._controller = controller
        self._entry = entry
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_control"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._enabled_listener_remove: Callable[[], None] | None = None
        self._enabled_listener_remove = self._controller.add_enabled_listener(
            self._on_enabled_updated
        )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal."""
        if self._enabled_listener_remove:
            self._enabled_listener_remove()
            self._enabled_listener_remove = None
        await super().async_will_remove_from_hass()

    def _on_enabled_updated(self) -> None:
        """Refresh the switch state when the controller toggles itself off."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:  # type: ignore[override]
        """Return true if Climate React is enabled."""
        return self._controller.enabled

    @property
    def icon(self) -> str:  # type: ignore[override]
        """Return the icon for the switch."""
        return "mdi:thermostat-cog" if self.is_on else "mdi:thermostat"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on Climate React."""
        await self._controller.async_enable()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off Climate React."""
        await self._controller.async_disable()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """Return extra state attributes."""
        from .const import (
            CONF_MAX_TEMP,
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

        return attrs
