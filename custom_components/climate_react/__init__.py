"""The Climate React integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .climate_react import ClimateReactController
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_ENABLED,
    DATA_COORDINATOR,
    DATA_UNSUB,
    DOMAIN,
    SERVICE_DISABLE,
    SERVICE_ENABLE,
    SERVICE_UPDATE_THRESHOLDS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.NUMBER, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climate React from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Create the controller
    controller = ClimateReactController(hass, entry)
    await controller.async_setup()
    
    # Store the controller
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: controller,
        DATA_UNSUB: [],
    }
    
    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    await async_register_services(hass)
    
    # Setup options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    
    _LOGGER.info("Climate React integration initialized for %s", entry.data[CONF_CLIMATE_ENTITY])
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Clean up the controller
        data = hass.data[DOMAIN][entry.entry_id]
        controller: ClimateReactController = data[DATA_COORDINATOR]
        await controller.async_shutdown()
        
        # Remove unsub listeners
        for unsub in data[DATA_UNSUB]:
            unsub()
        
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register Climate React services."""
    
    async def handle_enable(call: ServiceCall) -> None:
        """Handle enable service call."""
        entity_id = call.data.get("entity_id")
        for entry_id, data in hass.data[DOMAIN].items():
            controller: ClimateReactController = data[DATA_COORDINATOR]
            if entity_id is None or controller.climate_entity == entity_id:
                await controller.async_enable()
    
    async def handle_disable(call: ServiceCall) -> None:
        """Handle disable service call."""
        entity_id = call.data.get("entity_id")
        for entry_id, data in hass.data[DOMAIN].items():
            controller: ClimateReactController = data[DATA_COORDINATOR]
            if entity_id is None or controller.climate_entity == entity_id:
                await controller.async_disable()
    
    async def handle_update_thresholds(call: ServiceCall) -> None:
        """Handle update thresholds service call."""
        entity_id = call.data.get("entity_id")
        for entry_id, data in hass.data[DOMAIN].items():
            controller: ClimateReactController = data[DATA_COORDINATOR]
            if entity_id is None or controller.climate_entity == entity_id:
                await controller.async_update_thresholds(call.data)
    
    # Register services if not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_ENABLE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_ENABLE,
            handle_enable,
            schema=vol.Schema({
                vol.Optional("entity_id"): cv.entity_id,
            }),
        )
    
    if not hass.services.has_service(DOMAIN, SERVICE_DISABLE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DISABLE,
            handle_disable,
            schema=vol.Schema({
                vol.Optional("entity_id"): cv.entity_id,
            }),
        )
    
    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE_THRESHOLDS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE_THRESHOLDS,
            handle_update_thresholds,
            schema=vol.Schema({
                vol.Optional("entity_id"): cv.entity_id,
                vol.Optional("min_temp"): vol.Coerce(float),
                vol.Optional("max_temp"): vol.Coerce(float),
                vol.Optional("min_humidity"): vol.Coerce(float),
                vol.Optional("max_humidity"): vol.Coerce(float),
            }),
        )
