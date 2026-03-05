"""The Climate React integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .climate_react import ClimateReactController
from .const import (
    CONF_CLIMATE_ENTITY,
    DATA_COORDINATOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.NUMBER, Platform.SELECT]

# Key for storing per-entry data snapshots inside hass.data[DOMAIN].
# Using hass.data avoids module-level globals that survive HA module reloads
# (e.g. via HACS), which would cause async_update_options to always reload.
_ENTRY_DATA_CACHE = "_entry_data_cache"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climate React from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(_ENTRY_DATA_CACHE, {})

    # Create the controller
    controller = ClimateReactController(hass, entry)
    await controller.async_setup()

    # Store the controller
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: controller,
    }

    # Track initial data for change detection
    hass.data[DOMAIN][_ENTRY_DATA_CACHE][entry.entry_id] = dict(entry.data)

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Setup options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info(
        "Climate React integration initialized for %s", entry.data[CONF_CLIMATE_ENTITY]
    )

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

        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].get(_ENTRY_DATA_CACHE, {}).pop(entry.entry_id, None)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle entry data or options updates.

    Only reload if entry.data changed (climate entity, external sensors).
    Options changes (modes, thresholds) are handled by the controller without reload.
    """
    # Check if entry.data actually changed (climate entity or sensors)
    entry_data_cache = hass.data.get(DOMAIN, {}).get(_ENTRY_DATA_CACHE, {})
    previous_data = entry_data_cache.get(entry.entry_id, {})
    if entry.data != previous_data:
        # Data changed - need to reload to reconfigure climate entity/sensors
        entry_data_cache[entry.entry_id] = dict(entry.data)
        _LOGGER.info("Climate React entry data changed, reloading...")
        await hass.config_entries.async_reload(entry.entry_id)
    # else: only options changed (modes/thresholds) - controller handles this without reload
