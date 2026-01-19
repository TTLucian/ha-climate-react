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
    CONF_ENABLE_LIGHT_CONTROL,
    CONF_LIGHT_ENTITY,
    CONF_LIGHT_SELECT_ON_OPTION,
    CONF_LIGHT_SELECT_OFF_OPTION,
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
    DEFAULT_LIGHT_SELECT_ON_OPTION,
    DEFAULT_LIGHT_SELECT_OFF_OPTION,
    DEFAULT_ENABLE_LIGHT_CONTROL,
    DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
    DEFAULT_USE_EXTERNAL_TEMP_SENSOR,
    DEFAULT_USE_HUMIDITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ClimateReactConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climate React."""

    VERSION = 1
    _step1_data: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step - core settings and navigation to sensors step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate climate entity exists
            climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
            if not climate_entity:
                errors[CONF_CLIMATE_ENTITY] = "entity_required"
            elif not self.hass.states.get(climate_entity):
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            if not errors:
                self._step1_data = dict(user_input)
                return await self.async_step_sensors()

        # Build schema with all fields
        schema_dict = {
            vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_USE_EXTERNAL_TEMP_SENSOR,
                default=DEFAULT_USE_EXTERNAL_TEMP_SENSOR,
                description={"suggested_value": DEFAULT_USE_EXTERNAL_TEMP_SENSOR}
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_HUMIDITY,
                default=DEFAULT_USE_HUMIDITY,
                description={"suggested_value": DEFAULT_USE_HUMIDITY}
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                default=DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
                description={"suggested_value": DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR}
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_LIGHT_CONTROL,
                default=DEFAULT_ENABLE_LIGHT_CONTROL,
                description={"suggested_value": DEFAULT_ENABLE_LIGHT_CONTROL}
            ): selector.BooleanSelector(),
        }

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle sensor selection step based on first-step choices."""
        if not self._step1_data:
            return await self.async_step_user()

        errors: dict[str, str] = {}

        use_external_temp = self._step1_data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
        use_humidity = self._step1_data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        use_external_humidity = self._step1_data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)

        if user_input is not None:
            if use_external_temp:
                temp_sensor = user_input.get(CONF_TEMPERATURE_SENSOR)
                if not temp_sensor:
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_required"
                elif not self.hass.states.get(temp_sensor):
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_not_found"

            if use_humidity and use_external_humidity:
                humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
                if not humidity_sensor:
                    errors[CONF_HUMIDITY_SENSOR] = "entity_required"
                elif not self.hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"

            if use_humidity:
                humidifier = user_input.get(CONF_HUMIDIFIER_ENTITY)
                if humidifier and not self.hass.states.get(humidifier):
                    errors[CONF_HUMIDIFIER_ENTITY] = "entity_not_found"

            if self._step1_data.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL):
                light_entity = user_input.get(CONF_LIGHT_ENTITY)
                if not light_entity:
                    errors[CONF_LIGHT_ENTITY] = "entity_required"
                elif not self.hass.states.get(light_entity):
                    errors[CONF_LIGHT_ENTITY] = "entity_not_found"

            if not errors:
                climate_entity = self._step1_data[CONF_CLIMATE_ENTITY]
                await self.async_set_unique_id(climate_entity)
                self._abort_if_unique_id_configured()

                data = {**self._step1_data}
                data[CONF_TEMPERATURE_SENSOR] = user_input.get(CONF_TEMPERATURE_SENSOR)
                data[CONF_HUMIDITY_SENSOR] = user_input.get(CONF_HUMIDITY_SENSOR)
                data[CONF_HUMIDIFIER_ENTITY] = user_input.get(CONF_HUMIDIFIER_ENTITY)

                # Prepare defaults
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
                data[CONF_ENABLE_LIGHT_CONTROL] = data.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL)
                data[CONF_LIGHT_ENTITY] = user_input.get(CONF_LIGHT_ENTITY)
                data[CONF_LIGHT_SELECT_ON_OPTION] = user_input.get(CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION)
                data[CONF_LIGHT_SELECT_OFF_OPTION] = user_input.get(CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION)

                return self.async_create_entry(
                    title=f"Climate React - {climate_entity}",
                    data=data,
                )

        schema_dict: dict[Any, Any] = {}

        if use_external_temp:
            schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )

        if use_humidity and use_external_humidity:
            schema_dict[vol.Required(CONF_HUMIDITY_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            )

        if use_humidity:
            schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="humidifier")
            )

        if self._step1_data.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL):
            schema_dict[vol.Required(CONF_LIGHT_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["light", "switch", "select"])
            )
            # Add select option fields with defaults
            schema_dict[vol.Optional(
                CONF_LIGHT_SELECT_ON_OPTION,
                default=DEFAULT_LIGHT_SELECT_ON_OPTION
            )] = selector.TextSelector()
            schema_dict[vol.Optional(
                CONF_LIGHT_SELECT_OFF_OPTION,
                default=DEFAULT_LIGHT_SELECT_OFF_OPTION
            )] = selector.TextSelector()

        return self.async_show_form(
            step_id="sensors", data_schema=vol.Schema(schema_dict), errors=errors
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
        super().__init__()
        self._config_entry = config_entry
        self._step1_data: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Initial options step - core selections before sensors."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate climate entity exists
            climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
            if not climate_entity:
                errors[CONF_CLIMATE_ENTITY] = "entity_required"
            elif not self.hass.states.get(climate_entity):
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            if not errors:
                self._step1_data = dict(user_input)
                return await self.async_step_sensors()

        # Build schema with core fields only
        schema_dict = {
            vol.Required(
                CONF_CLIMATE_ENTITY,
                default=self.config_entry.data.get(CONF_CLIMATE_ENTITY)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_USE_EXTERNAL_TEMP_SENSOR,
                default=self.config_entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR),
                description={"suggested_value": self.config_entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)}
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_HUMIDITY,
                default=self.config_entry.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY),
                description={"suggested_value": self.config_entry.data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)}
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                default=self.config_entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR),
                description={"suggested_value": self.config_entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)}
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_LIGHT_CONTROL,
                default=self.config_entry.data.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL),
                description={"suggested_value": self.config_entry.data.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL)}
            ): selector.BooleanSelector(),
        }

        options_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Second options step - sensors/entities based on toggles."""
        if not self._step1_data:
            return await self.async_step_init()

        errors: dict[str, str] = {}

        use_external_temp = self._step1_data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR)
        use_humidity = self._step1_data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        use_external_humidity = self._step1_data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR)
        light_control = self._step1_data.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL)

        if user_input is not None:
            if use_external_temp:
                temp_sensor = user_input.get(CONF_TEMPERATURE_SENSOR)
                if not temp_sensor:
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_required"
                elif not self.hass.states.get(temp_sensor):
                    errors[CONF_TEMPERATURE_SENSOR] = "entity_not_found"

            if use_humidity and use_external_humidity:
                humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
                if not humidity_sensor:
                    errors[CONF_HUMIDITY_SENSOR] = "entity_required"
                elif not self.hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"

            if use_humidity:
                humidifier = user_input.get(CONF_HUMIDIFIER_ENTITY)
                if humidifier and not self.hass.states.get(humidifier):
                    errors[CONF_HUMIDIFIER_ENTITY] = "entity_not_found"

            if light_control:
                light_entity = user_input.get(CONF_LIGHT_ENTITY)
                if not light_entity:
                    errors[CONF_LIGHT_ENTITY] = "entity_required"
                elif not self.hass.states.get(light_entity):
                    errors[CONF_LIGHT_ENTITY] = "entity_not_found"

            if not errors:
                # Merge existing data with updated selections
                data = {**self.config_entry.data, **self._step1_data}
                data[CONF_TEMPERATURE_SENSOR] = user_input.get(CONF_TEMPERATURE_SENSOR)
                data[CONF_HUMIDITY_SENSOR] = user_input.get(CONF_HUMIDITY_SENSOR)
                data[CONF_HUMIDIFIER_ENTITY] = user_input.get(CONF_HUMIDIFIER_ENTITY)
                data[CONF_LIGHT_ENTITY] = user_input.get(CONF_LIGHT_ENTITY)
                data[CONF_LIGHT_SELECT_ON_OPTION] = user_input.get(CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION)
                data[CONF_LIGHT_SELECT_OFF_OPTION] = user_input.get(CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION)

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=data,
                )
                return self.async_create_entry(title="", data={})

        schema_dict: dict[Any, Any] = {}

        if use_external_temp:
            current_temp = self.config_entry.data.get(CONF_TEMPERATURE_SENSOR)
            schema_dict[vol.Required(
                CONF_TEMPERATURE_SENSOR,
                default=current_temp
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )

        if use_humidity and use_external_humidity:
            current_humidity = self.config_entry.data.get(CONF_HUMIDITY_SENSOR)
            schema_dict[vol.Required(
                CONF_HUMIDITY_SENSOR,
                default=current_humidity
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            )

        if use_humidity:
            current_humidifier = self.config_entry.data.get(CONF_HUMIDIFIER_ENTITY)
            schema_dict[vol.Optional(
                CONF_HUMIDIFIER_ENTITY,
                default=current_humidifier
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="humidifier")
            )

        if light_control:
            current_light = self.config_entry.data.get(CONF_LIGHT_ENTITY)
            schema_dict[vol.Required(
                CONF_LIGHT_ENTITY,
                default=current_light
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["light", "switch", "select"])
            )
            # Add select option fields with current values or defaults
            current_on = self.config_entry.data.get(CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION)
            current_off = self.config_entry.data.get(CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION)
            schema_dict[vol.Optional(
                CONF_LIGHT_SELECT_ON_OPTION,
                default=current_on
            )] = selector.TextSelector()
            schema_dict[vol.Optional(
                CONF_LIGHT_SELECT_OFF_OPTION,
                default=current_off
            )] = selector.TextSelector()

        return self.async_show_form(
            step_id="sensors", data_schema=vol.Schema(schema_dict), errors=errors
        )
