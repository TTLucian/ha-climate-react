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
        """Handle the initial step - climate entity selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate climate entity exists
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            if not self.hass.states.get(climate_entity):
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            
            if not errors:
                # Store data for next step
                self.data = user_input
                return await self.async_step_temperature()

        # Step 1: Climate entity and external temp sensor choice
        data_schema = vol.Schema(
            {
                vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_USE_EXTERNAL_TEMP_SENSOR, default=DEFAULT_USE_EXTERNAL_TEMP_SENSOR): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_temperature(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle temperature sensor selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate temperature sensor if external is enabled
            use_external_temp = self.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
            if use_external_temp:
                temp_sensor = user_input.get(CONF_TEMPERATURE_SENSOR)
                if not temp_sensor:
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_required"
                elif not self.hass.states.get(temp_sensor):
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_not_found"
            
            if not errors:
                # Update data and continue
                self.data.update(user_input)
                return await self.async_step_humidity()

        # Only show temperature sensor if using external sensor
        use_external_temp = self.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
        schema_dict = {}
        
        if use_external_temp:
            schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
        
        if not schema_dict:
            # If not using external temp sensor, skip to next step
            self.data[CONF_TEMPERATURE_SENSOR] = None
            return await self.async_step_humidity()

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="temperature", data_schema=data_schema, errors=errors
        )

    async def async_step_humidity(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle humidity control choice."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store humidity settings
            self.data.update(user_input)
            return await self.async_step_humidity_sensor()

        # Step 3: Humidity control
        data_schema = vol.Schema(
            {
                vol.Optional(CONF_USE_HUMIDITY, default=DEFAULT_USE_HUMIDITY): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="humidity", data_schema=data_schema, errors=errors
        )

    async def async_step_humidity_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle humidity sensor selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate humidity sensor if needed
            use_humidity = self.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
            use_external_humidity = user_input.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
            
            if use_humidity and use_external_humidity:
                humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
                if not humidity_sensor:
                    errors[CONF_HUMIDITY_SENSOR] = "entity_required"
                elif not self.hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"
            
            if not errors:
                # Update data and create entry
                self.data.update(user_input)
                return await self._async_create_entry_with_defaults()

        use_humidity = self.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        
        if not use_humidity:
            # Skip humidity sensor selection if humidity not enabled
            self.data[CONF_USE_EXTERNAL_HUMIDITY_SENSOR] = False
            self.data[CONF_HUMIDITY_SENSOR] = None
            self.data[CONF_HUMIDIFIER_ENTITY] = None
            return await self._async_create_entry_with_defaults()

        schema_dict = {
            vol.Optional(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, default=DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR): selector.BooleanSelector(),
        }
        
        # Show humidity sensor if using external
        use_external_humidity = self.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
        if use_external_humidity:
            schema_dict[vol.Required(CONF_HUMIDITY_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            )
        
        # Always show humidifier option if humidity enabled
        schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="humidifier")
        )

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="humidity_sensor", data_schema=data_schema, errors=errors
        )

    async def _async_create_entry_with_defaults(self) -> config_entries.FlowResult:
        """Create the config entry with default values."""
        climate_entity = self.data[CONF_CLIMATE_ENTITY]
        
        # Create a unique ID based on the climate entity
        await self.async_set_unique_id(climate_entity)
        self._abort_if_unique_id_configured()
        
        # Add default values for other settings
        data = dict(self.data)
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
        self.data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options - step 1: climate entity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate climate entity exists
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            if not self.hass.states.get(climate_entity):
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            
            if not errors:
                # Store data for next step
                self.data = user_input
                return await self.async_step_temperature_options()

        # Step 1: Climate entity and external temp sensor choice
        options_schema = vol.Schema(
            {
                vol.Required(CONF_CLIMATE_ENTITY, default=self.config_entry.data.get(CONF_CLIMATE_ENTITY)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_USE_EXTERNAL_TEMP_SENSOR, default=self.config_entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )

    async def async_step_temperature_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle temperature sensor selection in options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate temperature sensor if external is enabled
            use_external_temp = self.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
            if use_external_temp:
                temp_sensor = user_input.get(CONF_TEMPERATURE_SENSOR)
                if not temp_sensor:
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_required"
                elif not self.hass.states.get(temp_sensor):
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_not_found"
            
            if not errors:
                # Update data and continue
                self.data.update(user_input)
                return await self.async_step_humidity_options()

        # Only show temperature sensor if using external sensor
        use_external_temp = self.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
        schema_dict = {}
        
        if use_external_temp:
            schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR, default=self.config_entry.data.get(CONF_TEMPERATURE_SENSOR))] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
        
        if not schema_dict:
            # If not using external temp sensor, skip to next step
            self.data[CONF_TEMPERATURE_SENSOR] = None
            return await self.async_step_humidity_options()

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="temperature_options", data_schema=data_schema, errors=errors
        )

    async def async_step_humidity_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle humidity control choice in options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store humidity settings
            self.data.update(user_input)
            return await self.async_step_humidity_sensor_options()

        # Step 3: Humidity control
        options_schema = vol.Schema(
            {
                vol.Optional(CONF_USE_HUMIDITY, default=self.config_entry.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="humidity_options", data_schema=options_schema, errors=errors
        )

    async def async_step_humidity_sensor_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle humidity sensor selection in options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate humidity sensor if needed
            use_humidity = self.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
            use_external_humidity = user_input.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
            
            if use_humidity and use_external_humidity:
                humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
                if not humidity_sensor:
                    errors[CONF_HUMIDITY_SENSOR] = "entity_required"
                elif not self.hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"
            
            if not errors:
                # Update entry data
                new_data = dict(self.config_entry.data)
                new_data.update(self.data)
                new_data.update(user_input)
                
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                )
                return self.async_create_entry(title="", data={})
            
            # Re-show form with errors, preserving user input
            self.data.update(user_input)

        use_humidity = self.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        
        if not use_humidity:
            # Skip humidity sensor selection if humidity not enabled
            new_data = dict(self.config_entry.data)
            new_data.update(self.data)
            new_data[CONF_USE_EXTERNAL_HUMIDITY_SENSOR] = False
            new_data[CONF_HUMIDITY_SENSOR] = None
            new_data[CONF_HUMIDIFIER_ENTITY] = None
            
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )
            return self.async_create_entry(title="", data={})

        schema_dict = {
            vol.Optional(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, default=self.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, self.config_entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR))): selector.BooleanSelector(),
        }
        
        # Show humidity sensor if using external
        use_external_humidity = self.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, self.config_entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR))
        if use_external_humidity:
            schema_dict[vol.Required(CONF_HUMIDITY_SENSOR, default=self.data.get(CONF_HUMIDITY_SENSOR, self.config_entry.data.get(CONF_HUMIDITY_SENSOR)))] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            )
        
        # Always show humidifier option if humidity enabled
        schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY, default=self.data.get(CONF_HUMIDIFIER_ENTITY, self.config_entry.data.get(CONF_HUMIDIFIER_ENTITY)))] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="humidifier")
        )

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="humidity_sensor_options", data_schema=data_schema, errors=errors
        )
