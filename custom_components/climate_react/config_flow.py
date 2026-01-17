"""Config flow for Climate React integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_ENABLED,
    CONF_FAN_HIGH_HUMIDITY,
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
    CONF_USE_EXTERNAL_TEMP_SENSOR,
    CONF_USE_HUMIDITY,
    CONF_MAX_HUMIDITY,
    CONF_MAX_TEMP,
    CONF_MIN_HUMIDITY,
    CONF_MIN_TEMP,
    CONF_MODE_HIGH_HUMIDITY,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    CONF_MIN_RUN_TIME,
    CONF_SWING_HIGH_HUMIDITY,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_LOW_TEMP,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_ENABLED,
    DEFAULT_FAN_MODE,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MIN_TEMP,
    DEFAULT_MIN_RUN_TIME,
    DEFAULT_MODE_HIGH_HUMIDITY,
    DEFAULT_MODE_HIGH_TEMP,
    DEFAULT_MODE_LOW_TEMP,
    DEFAULT_SWING_MODE,
    DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
    DEFAULT_USE_EXTERNAL_TEMP_SENSOR,
    DEFAULT_USE_HUMIDITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ClimateReactConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climate React."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate climate entity exists
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            if not self.hass.states.get(climate_entity):
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            
            # Validate temperature sensor if external sensor is enabled
            use_external_temp = user_input.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
            temp_sensor = user_input.get(CONF_TEMPERATURE_SENSOR)
            if use_external_temp:
                if not temp_sensor:
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_required"
                elif not self.hass.states.get(temp_sensor):
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_not_found"
            
            # Validate humidity sensor if humidity is enabled and external sensor is enabled
            use_humidity = user_input.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
            use_external_humidity = user_input.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
            humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
            if use_humidity and use_external_humidity:
                if not humidity_sensor:
                    errors[CONF_HUMIDITY_SENSOR] = "entity_required"
                elif not self.hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"
            
            # Validate humidifier entity if provided
            humidifier_entity = user_input.get(CONF_HUMIDIFIER_ENTITY)
            if humidifier_entity and not self.hass.states.get(humidifier_entity):
                errors[CONF_HUMIDIFIER_ENTITY] = "entity_not_found"
            
            if not errors:
                # Create a unique ID based on the climate entity
                await self.async_set_unique_id(climate_entity)
                self._abort_if_unique_id_configured()
                
                # Add default values for other settings (configured via entities later)
                data = dict(user_input)
                data[CONF_MIN_TEMP] = DEFAULT_MIN_TEMP
                data[CONF_MAX_TEMP] = DEFAULT_MAX_TEMP
                data[CONF_MIN_HUMIDITY] = DEFAULT_MIN_HUMIDITY
                data[CONF_MAX_HUMIDITY] = DEFAULT_MAX_HUMIDITY
                data[CONF_MIN_RUN_TIME] = DEFAULT_MIN_RUN_TIME
                data[CONF_MODE_LOW_TEMP] = DEFAULT_MODE_LOW_TEMP
                data[CONF_MODE_HIGH_TEMP] = DEFAULT_MODE_HIGH_TEMP
                data[CONF_MODE_HIGH_HUMIDITY] = DEFAULT_MODE_HIGH_HUMIDITY
                data[CONF_FAN_LOW_TEMP] = DEFAULT_FAN_MODE
                data[CONF_FAN_HIGH_TEMP] = DEFAULT_FAN_MODE
                data[CONF_FAN_HIGH_HUMIDITY] = DEFAULT_FAN_MODE
                data[CONF_SWING_LOW_TEMP] = DEFAULT_SWING_MODE
                data[CONF_SWING_HIGH_TEMP] = DEFAULT_SWING_MODE
                data[CONF_SWING_HIGH_HUMIDITY] = DEFAULT_SWING_MODE
                data[CONF_ENABLED] = DEFAULT_ENABLED
                
                return self.async_create_entry(
                    title=f"Climate React - {climate_entity}",
                    data=data,
                )

        # Build the data schema dynamically based on checkbox state
        schema_dict = {
            vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(CONF_USE_EXTERNAL_TEMP_SENSOR, default=DEFAULT_USE_EXTERNAL_TEMP_SENSOR): selector.BooleanSelector(),
        }
        
        # Add temperature sensor field only if external temp sensor is enabled
        if user_input and user_input.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR):
            schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
        
        # Add humidity control checkbox
        schema_dict[vol.Optional(CONF_USE_HUMIDITY, default=DEFAULT_USE_HUMIDITY)] = selector.BooleanSelector()
        
        # Add humidity options only if humidity is enabled
        if user_input and user_input.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY):
            schema_dict[vol.Optional(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, default=DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)] = selector.BooleanSelector()
            
            # Add humidity sensor field only if external humidity sensor is enabled
            if user_input.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR):
                schema_dict[vol.Required(CONF_HUMIDITY_SENSOR)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                )
            
            # Add humidifier entity only if humidity is enabled
            schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="humidifier")
            )
        
        data_schema = vol.Schema(schema_dict)

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return ClimateReactOptionsFlow(config_entry)


class ClimateReactOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Climate React."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options - only allows changing entities."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate climate entity exists
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            if not self.hass.states.get(climate_entity):
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            
            # Validate temperature sensor if external sensor is enabled
            use_external_temp = user_input.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
            temp_sensor = user_input.get(CONF_TEMPERATURE_SENSOR)
            if use_external_temp:
                if not temp_sensor:
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_required"
                elif not self.hass.states.get(temp_sensor):
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_not_found"
            
            # Validate humidity sensor if humidity is enabled and external sensor is enabled
            use_humidity = user_input.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
            use_external_humidity = user_input.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
            humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
            if use_humidity and use_external_humidity:
                if not humidity_sensor:
                    errors[CONF_HUMIDITY_SENSOR] = "entity_required"
                elif not self.hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"
            
            # Validate humidifier entity if provided
            humidifier_entity = user_input.get(CONF_HUMIDIFIER_ENTITY)
            if humidifier_entity and not self.hass.states.get(humidifier_entity):
                errors[CONF_HUMIDIFIER_ENTITY] = "entity_not_found"
            
            if not errors:
                # Update entry data with new entities
                new_data = dict(self.config_entry.data)
                new_data[CONF_CLIMATE_ENTITY] = climate_entity
                new_data[CONF_USE_EXTERNAL_TEMP_SENSOR] = use_external_temp
                new_data[CONF_TEMPERATURE_SENSOR] = temp_sensor
                new_data[CONF_USE_HUMIDITY] = use_humidity
                new_data[CONF_USE_EXTERNAL_HUMIDITY_SENSOR] = use_external_humidity
                new_data[CONF_HUMIDITY_SENSOR] = humidity_sensor
                new_data[CONF_HUMIDIFIER_ENTITY] = humidifier_entity
                
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                )
                return self.async_create_entry(title="", data={})

        # Build options schema dynamically based on checkbox state
        schema_dict = {
            vol.Required(CONF_CLIMATE_ENTITY, default=self.config_entry.data.get(CONF_CLIMATE_ENTITY)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(CONF_USE_EXTERNAL_TEMP_SENSOR, default=self.config_entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)): selector.BooleanSelector(),
        }
        
        # Add temperature sensor field only if external temp sensor is enabled
        use_external_temp = (user_input and user_input.get(CONF_USE_EXTERNAL_TEMP_SENSOR)) or (
            not user_input and self.config_entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
        )
        if use_external_temp:
            schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR, default=self.config_entry.data.get(CONF_TEMPERATURE_SENSOR))] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
        
        # Add humidity control checkbox
        schema_dict[vol.Optional(CONF_USE_HUMIDITY, default=self.config_entry.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY))] = selector.BooleanSelector()
        
        # Add humidity options only if humidity is enabled
        use_humidity = (user_input and user_input.get(CONF_USE_HUMIDITY)) or (
            not user_input and self.config_entry.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        )
        if use_humidity:
            schema_dict[vol.Optional(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, default=self.config_entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR))] = selector.BooleanSelector()
            
            # Add humidity sensor field only if external humidity sensor is enabled
            use_external_humidity = (user_input and user_input.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR)) or (
                not user_input and self.config_entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
            )
            if use_external_humidity:
                schema_dict[vol.Required(CONF_HUMIDITY_SENSOR, default=self.config_entry.data.get(CONF_HUMIDITY_SENSOR))] = selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                )
            
            # Add humidifier entity only if humidity is enabled
            schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY, default=self.config_entry.data.get(CONF_HUMIDIFIER_ENTITY))] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="humidifier")
            )
        
        options_schema = vol.Schema(schema_dict)

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )
