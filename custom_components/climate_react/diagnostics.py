"""Diagnostics support for Climate React integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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
    CONF_TEMPERATURE_SENSOR,
    CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
    CONF_USE_EXTERNAL_TEMP_SENSOR,
    CONF_USE_HUMIDITY,
    DATA_COORDINATOR,
    DOMAIN,
)

# Redact device IDs and sensor entity IDs in diagnostics
REDACT_KEYS = {
    CONF_CLIMATE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_HUMIDIFIER_ENTITY,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
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
                CONF_USE_HUMIDITY: entry.data.get(CONF_USE_HUMIDITY),
                CONF_USE_EXTERNAL_HUMIDITY_SENSOR: entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR),
                CONF_HUMIDITY_SENSOR: entry.data.get(CONF_HUMIDITY_SENSOR),
                CONF_HUMIDIFIER_ENTITY: entry.data.get(CONF_HUMIDIFIER_ENTITY),
            },
            REDACT_KEYS,
        ),
        "thresholds": {
            "temperature": {
                "min": config.get(CONF_MIN_TEMP),
                "max": config.get(CONF_MAX_TEMP),
            },
            "humidity": {
                "min": config.get(CONF_MIN_HUMIDITY),
                "max": config.get(CONF_MAX_HUMIDITY),
            },
        },
        "modes": {
            "low_temp": config.get("mode_low_temp"),
            "high_temp": config.get("mode_high_temp"),
            "high_humidity": config.get("mode_high_humidity"),
        },
        "fan_modes": {
            "low_temp": config.get("fan_low_temp"),
            "high_temp": config.get("fan_high_temp"),
            "high_humidity": config.get("fan_high_humidity"),
        },
        "swing_modes": {
            "low_temp": config.get("swing_low_temp"),
            "high_temp": config.get("swing_high_temp"),
            "high_humidity": config.get("swing_high_humidity"),
        },
        "target_temperatures": {
            "low_temp": config.get("temp_low_temp"),
            "high_temp": config.get("temp_high_temp"),
            "high_humidity": config.get("temp_high_humidity"),
        },
        "timing": {
            "delay_between_commands_ms": config.get(CONF_DELAY_BETWEEN_COMMANDS),
            "min_run_time_minutes": config.get(CONF_MIN_RUN_TIME),
        },
        "current_state": {
            "last_temperature": controller._last_temp,
            "last_humidity": controller._last_humidity,
            "last_set_hvac_mode": controller._last_set_hvac_mode,
            "last_mode_change_time": str(controller._last_mode_change_time) if controller._last_mode_change_time else None,
        },
    }

    return diagnostics_data
