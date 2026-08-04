"""Diagnostics support for Climate React integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .climate_react import ClimateReactController
from .const import (
    BASE_RETRY_DELAY_SECONDS,
    CONF_CLIMATE_ENTITY,
    CONF_DELAY_BETWEEN_COMMANDS,
    CONF_LAST_MODE_CHANGE_TIME,
    CONF_LAST_SET_HVAC_MODE,
    CONF_MAX_TEMP,
    CONF_MIN_RUN_TIME,
    CONF_MIN_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_USE_EXTERNAL_TEMP_SENSOR,
    DATA_COORDINATOR,
    DOMAIN,
    MAX_RETRY_ATTEMPTS,
)

# Redact device IDs and sensor entity IDs in diagnostics
REDACT_KEYS = {
    CONF_CLIMATE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    config = controller.config

    diagnostics_data = {
        "entry_id": entry.entry_id,
        "enabled": controller.enabled,
        "configuration": async_redact_data(
            {
                CONF_CLIMATE_ENTITY: entry.data.get(CONF_CLIMATE_ENTITY),
                CONF_USE_EXTERNAL_TEMP_SENSOR: entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR),
                CONF_TEMPERATURE_SENSOR: entry.data.get(CONF_TEMPERATURE_SENSOR),
            },
            REDACT_KEYS,
        ),
        "thresholds": {
            "temperature": {
                "min": config.get(CONF_MIN_TEMP),
                "max": config.get(CONF_MAX_TEMP),
            },
        },
        "modes": {
            "low_temp": config.get("mode_low_temp"),
            "high_temp": config.get("mode_high_temp"),
        },
        "fan_modes": {
            "low_temp": config.get("fan_low_temp"),
            "high_temp": config.get("fan_high_temp"),
        },
        "swing_modes": {
            "low_temp": config.get("swing_low_temp"),
            "high_temp": config.get("swing_high_temp"),
        },
        "target_temperatures": {
            "low_temp": config.get("temp_low_temp"),
            "high_temp": config.get("temp_high_temp"),
        },
        "timing": {
            "delay_between_commands_ms": config.get(CONF_DELAY_BETWEEN_COMMANDS),
            "min_run_time_minutes": config.get(CONF_MIN_RUN_TIME),
            "max_retry_attempts": MAX_RETRY_ATTEMPTS,
            "base_retry_delay_seconds": BASE_RETRY_DELAY_SECONDS,
        },
        "current_state": {
            "last_temperature": controller._last_temp,
            "last_set_hvac_mode": controller._last_set_hvac_mode,
            "last_mode_change_time": (
                str(controller._last_mode_change_time) if controller._last_mode_change_time else None
            ),
        },
        "persisted_state": {
            "last_mode_change_time": entry.options.get(CONF_LAST_MODE_CHANGE_TIME),
            "last_set_hvac_mode": entry.options.get(CONF_LAST_SET_HVAC_MODE),
        },
        "configuration_validation": {
            "entities_exist": all(
                hass.states.get(entity_id) is not None
                for entity_id in [
                    controller.climate_entity,
                    controller.temperature_sensor,
                ]
                + ([controller.light_entity] if controller.light_entity else [])
            ),
            "temperature_thresholds_valid": (config.get(CONF_MIN_TEMP, 18.0) < config.get(CONF_MAX_TEMP, 26.0)),
        },
    }

    return diagnostics_data
