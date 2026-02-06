"""Config flow for Climate React integration."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AC_HUMIDITY_CONTROLS,
    CONF_CLIMATE_ENTITY,
    CONF_DELAY_BETWEEN_COMMANDS,
    CONF_ENABLE_LIGHT_CONTROL,
    CONF_ENABLED,
    CONF_FAN_HIGH_HUMIDITY,
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_ENTITY,
    CONF_LIGHT_SELECT_OFF_OPTION,
    CONF_LIGHT_SELECT_ON_OPTION,
    CONF_MAX_HUMIDITY,
    CONF_MAX_TEMP,
    CONF_MIN_HUMIDITY,
    CONF_MIN_RUN_TIME,
    CONF_MIN_TEMP,
    CONF_MODE_HIGH_HUMIDITY,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    CONF_SWING_HIGH_HUMIDITY,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_HIGH_HUMIDITY,
    CONF_SWING_HORIZONTAL_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_LOW_TEMP,
    CONF_SWING_LOW_TEMP,
    CONF_TEMP_HIGH_HUMIDITY,
    CONF_TEMP_HIGH_TEMP,
    CONF_TEMP_LOW_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TIMER_MINUTES,
    CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
    CONF_USE_EXTERNAL_TEMP_SENSOR,
    CONF_USE_HUMIDITY,
    DEFAULT_AC_HUMIDITY_CONTROLS,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_ENABLE_LIGHT_CONTROL,
    DEFAULT_ENABLED,
    DEFAULT_FAN_MODE,
    DEFAULT_LIGHT_SELECT_OFF_OPTION,
    DEFAULT_LIGHT_SELECT_ON_OPTION,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MIN_RUN_TIME,
    DEFAULT_MIN_TEMP,
    DEFAULT_MODE_HIGH_HUMIDITY,
    DEFAULT_MODE_HIGH_TEMP,
    DEFAULT_MODE_LOW_TEMP,
    DEFAULT_SWING_MODE,
    DEFAULT_TEMP_HIGH_HUMIDITY,
    DEFAULT_TEMP_HIGH_TEMP,
    DEFAULT_TEMP_LOW_TEMP,
    DEFAULT_TIMER_MINUTES,
    DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
    DEFAULT_USE_EXTERNAL_TEMP_SENSOR,
    DEFAULT_USE_HUMIDITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class UserStepData(TypedDict, total=False):
    """Type-safe data structure for user step configuration."""

    climate_entity: str
    enable_light_control: bool
    use_external_temp_sensor: bool
    use_humidity: bool
    use_external_humidity_sensor: bool
    ac_humidity_controls: bool


class SensorStepData(TypedDict, total=False):
    """Type-safe data structure for sensor step configuration."""

    temperature_sensor: str | None
    humidity_sensor: str | None
    humidifier_entity: str | None
    light_entity: str | None


class LightOptionsData(TypedDict, total=False):
    """Type-safe data structure for light options step configuration."""

    light_select_on_option: str
    light_select_off_option: str


class ClimateReactConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climate React."""

    VERSION = 1
    _step1_data: UserStepData | None = None
    _step2_data: SensorStepData | None = None

    def _validate_entity_exists(
        self, entity_id: str | None, field_name: str, errors: dict[str, str]
    ) -> bool:
        """Validate that an entity exists in Home Assistant.

        Args:
            entity_id: The entity ID to validate
            field_name: The field name for error reporting
            errors: Dictionary to store validation errors

        Returns:
            True if entity exists or entity_id is None, False otherwise
        """
        if not entity_id:
            errors[field_name] = "entity_required"
            return False
        if not self.hass.states.get(entity_id):
            errors[field_name] = "entity_not_found"
            return False
        return True

    def _validate_entity_domain(
        self,
        entity_id: str,
        allowed_domains: list[str],
        field_name: str,
        errors: dict[str, str],
    ) -> bool:
        """Validate that an entity belongs to allowed domains.

        Args:
            entity_id: The entity ID to validate
            allowed_domains: List of allowed domain prefixes
            field_name: The field name for error reporting
            errors: Dictionary to store validation errors

        Returns:
            True if entity domain is allowed, False otherwise
        """
        if not any(entity_id.startswith(domain + ".") for domain in allowed_domains):
            errors[field_name] = "invalid_domain"
            return False
        return True

    def _extract_optional_entity(
        self, user_input: dict[str, Any] | None, field_name: str
    ) -> str | None:
        """Type-safely extract an optional entity ID from user input.

        Args:
            user_input: The user input dictionary
            field_name: The field name to extract

        Returns:
            The entity ID if present and valid, None otherwise
        """
        if not user_input:
            return None
        value = user_input.get(field_name)
        return str(value) if value else None

    def _create_default_config_data(self, base_data: UserStepData) -> dict[str, Any]:
        """Create complete configuration data with all default values.

        Args:
            base_data: The base configuration data from user input

        Returns:
            Complete configuration dictionary with defaults
        """
        from .const import (
            DEFAULT_DELAY_BETWEEN_COMMANDS,
            DEFAULT_ENABLED,
            DEFAULT_FAN_MODE,
            DEFAULT_LIGHT_SELECT_OFF_OPTION,
            DEFAULT_LIGHT_SELECT_ON_OPTION,
            DEFAULT_MAX_HUMIDITY,
            DEFAULT_MAX_TEMP,
            DEFAULT_MIN_HUMIDITY,
            DEFAULT_MIN_RUN_TIME,
            DEFAULT_MIN_TEMP,
            DEFAULT_MODE_HIGH_HUMIDITY,
            DEFAULT_MODE_HIGH_TEMP,
            DEFAULT_MODE_LOW_TEMP,
            DEFAULT_SWING_MODE,
            DEFAULT_TEMP_HIGH_HUMIDITY,
            DEFAULT_TEMP_HIGH_TEMP,
            DEFAULT_TEMP_LOW_TEMP,
            DEFAULT_TIMER_MINUTES,
        )

        return {
            **base_data,
            CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
            CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
            CONF_MIN_HUMIDITY: DEFAULT_MIN_HUMIDITY,
            CONF_MAX_HUMIDITY: DEFAULT_MAX_HUMIDITY,
            CONF_MIN_RUN_TIME: DEFAULT_MIN_RUN_TIME,
            CONF_MODE_LOW_TEMP: DEFAULT_MODE_LOW_TEMP,
            CONF_MODE_HIGH_TEMP: DEFAULT_MODE_HIGH_TEMP,
            CONF_MODE_HIGH_HUMIDITY: DEFAULT_MODE_HIGH_HUMIDITY,
            CONF_FAN_LOW_TEMP: DEFAULT_FAN_MODE,
            CONF_FAN_HIGH_TEMP: DEFAULT_FAN_MODE,
            CONF_FAN_HIGH_HUMIDITY: DEFAULT_FAN_MODE,
            CONF_SWING_LOW_TEMP: DEFAULT_SWING_MODE,
            CONF_SWING_HIGH_TEMP: DEFAULT_SWING_MODE,
            CONF_SWING_HIGH_HUMIDITY: DEFAULT_SWING_MODE,
            CONF_SWING_HORIZONTAL_LOW_TEMP: DEFAULT_SWING_MODE,
            CONF_SWING_HORIZONTAL_HIGH_TEMP: DEFAULT_SWING_MODE,
            CONF_SWING_HORIZONTAL_HIGH_HUMIDITY: DEFAULT_SWING_MODE,
            CONF_TEMP_LOW_TEMP: DEFAULT_TEMP_LOW_TEMP,
            CONF_TEMP_HIGH_TEMP: DEFAULT_TEMP_HIGH_TEMP,
            CONF_TEMP_HIGH_HUMIDITY: DEFAULT_TEMP_HIGH_HUMIDITY,
            CONF_DELAY_BETWEEN_COMMANDS: DEFAULT_DELAY_BETWEEN_COMMANDS,
            CONF_TIMER_MINUTES: DEFAULT_TIMER_MINUTES,
            CONF_ENABLED: DEFAULT_ENABLED,
            CONF_LIGHT_SELECT_ON_OPTION: DEFAULT_LIGHT_SELECT_ON_OPTION,
            CONF_LIGHT_SELECT_OFF_OPTION: DEFAULT_LIGHT_SELECT_OFF_OPTION,
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Handle the initial step - core settings and navigation to sensors step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Type-safe validation of climate entity
            climate_entity = self._extract_optional_entity(
                user_input, CONF_CLIMATE_ENTITY
            )
            if not self._validate_entity_exists(
                climate_entity, CONF_CLIMATE_ENTITY, errors
            ):
                pass  # Error already added by validation method

            if not errors:
                # Create type-safe step data
                assert climate_entity is not None  # Validated above
                self._step1_data = UserStepData(
                    climate_entity=climate_entity,
                    enable_light_control=user_input.get(
                        CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL
                    ),
                    use_external_temp_sensor=user_input.get(
                        CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR
                    ),
                    use_humidity=user_input.get(
                        CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY
                    ),
                    use_external_humidity_sensor=user_input.get(
                        CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                        DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
                    ),
                    ac_humidity_controls=user_input.get(
                        CONF_AC_HUMIDITY_CONTROLS, DEFAULT_AC_HUMIDITY_CONTROLS
                    ),
                )

                # Check if any optional features are enabled
                assert self._step1_data is not None  # Set above
                if not (
                    self._step1_data.get("use_external_temp_sensor", False)
                    or self._step1_data.get("use_humidity", False)
                    or self._step1_data.get("use_external_humidity_sensor", False)
                    or self._step1_data.get("ac_humidity_controls", False)
                ):
                    return await self._async_create_entry_with_defaults(
                        self._step1_data
                    )

                return await self.async_step_sensors()

        # Build schema with all fields
        schema_dict = {
            vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(
                CONF_ENABLE_LIGHT_CONTROL,
                default=DEFAULT_ENABLE_LIGHT_CONTROL,
                description={"suggested_value": DEFAULT_ENABLE_LIGHT_CONTROL},
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_EXTERNAL_TEMP_SENSOR,
                default=DEFAULT_USE_EXTERNAL_TEMP_SENSOR,
                description={"suggested_value": DEFAULT_USE_EXTERNAL_TEMP_SENSOR},
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_HUMIDITY,
                default=DEFAULT_USE_HUMIDITY,
                description={"suggested_value": DEFAULT_USE_HUMIDITY},
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                default=DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
                description={"suggested_value": DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR},
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_AC_HUMIDITY_CONTROLS,
                default=DEFAULT_AC_HUMIDITY_CONTROLS,
                description={"suggested_value": DEFAULT_AC_HUMIDITY_CONTROLS},
            ): selector.BooleanSelector(),
        }

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> Any:
        """Handle sensor selection step based on first-step choices."""
        if not self._step1_data:
            return await self.async_step_user()

        errors: dict[str, str] = {}

        use_external_temp = self._step1_data.get(
            CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR
        )
        use_humidity = self._step1_data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        use_external_humidity = self._step1_data.get(
            CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR
        )
        light_control = self._step1_data.get(
            CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL
        )

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

            # Validate light entity depending on whether light control was enabled
            light_entity = user_input.get(CONF_LIGHT_ENTITY)
            if light_control:
                # If user chose to enable light control, a light entity is required
                if not light_entity:
                    errors[CONF_LIGHT_ENTITY] = "entity_required"
                elif not self.hass.states.get(light_entity):
                    errors[CONF_LIGHT_ENTITY] = "entity_not_found"
                elif not any(
                    light_entity.startswith(domain + ".")
                    for domain in ["light", "switch", "select"]
                ):
                    errors[CONF_LIGHT_ENTITY] = "invalid_domain"
            else:
                # Light control disabled: if user provided an entity, validate its domain/existence
                if light_entity:
                    if not self.hass.states.get(light_entity):
                        errors[CONF_LIGHT_ENTITY] = "entity_not_found"
                    elif not any(
                        light_entity.startswith(domain + ".")
                        for domain in ["light", "switch", "select"]
                    ):
                        errors[CONF_LIGHT_ENTITY] = "invalid_domain"

            if not errors:
                # Check if light entity is a select type - if so, route to light_options step
                light_entity = user_input.get(CONF_LIGHT_ENTITY)
                if light_entity and light_entity.startswith("select."):
                    # Store step 2 data as type-safe SensorStepData
                    self._step2_data = SensorStepData(
                        temperature_sensor=self._extract_optional_entity(
                            user_input, CONF_TEMPERATURE_SENSOR
                        ),
                        humidity_sensor=self._extract_optional_entity(
                            user_input, CONF_HUMIDITY_SENSOR
                        ),
                        humidifier_entity=self._extract_optional_entity(
                            user_input, CONF_HUMIDIFIER_ENTITY
                        ),
                        light_entity=self._extract_optional_entity(
                            user_input, CONF_LIGHT_ENTITY
                        ),
                    )
                    return await self.async_step_light_options()

                # Otherwise, create entry
                assert self._step1_data is not None  # Set in async_step_user
                climate_entity = self._step1_data["climate_entity"]
                await self.async_set_unique_id(climate_entity)
                self._abort_if_unique_id_configured()

                # Create type-safe config data with sensor step inputs
                data = self._create_default_config_data(self._step1_data)
                data.update(
                    {
                        CONF_TEMPERATURE_SENSOR: self._extract_optional_entity(
                            user_input, CONF_TEMPERATURE_SENSOR
                        ),
                        CONF_HUMIDITY_SENSOR: self._extract_optional_entity(
                            user_input, CONF_HUMIDITY_SENSOR
                        ),
                        CONF_HUMIDIFIER_ENTITY: self._extract_optional_entity(
                            user_input, CONF_HUMIDIFIER_ENTITY
                        ),
                        CONF_LIGHT_ENTITY: self._extract_optional_entity(
                            user_input, CONF_LIGHT_ENTITY
                        ),
                    }
                )

                # Generate title matching device name logic
                state = self.hass.states.get(climate_entity)
                if state:
                    friendly_name = state.attributes.get("friendly_name")
                    if friendly_name:
                        # If friendly_name is just the entity_id, extract the name part
                        if friendly_name.startswith("climate."):
                            entity_name = (
                                friendly_name.split(".")[-1].replace("_", " ").title()
                            )
                            title = f"Climate React {entity_name}"
                        else:
                            title = f"Climate React {friendly_name}"
                    else:
                        entity_name = (
                            climate_entity.split(".")[-1].replace("_", " ").title()
                        )
                        title = f"Climate React {entity_name}"
                else:
                    entity_name = (
                        climate_entity.split(".")[-1].replace("_", " ").title()
                    )
                    title = f"Climate React {entity_name}"

                return self.async_create_entry(
                    title=title,
                    data=data,
                )

        schema_dict: dict[Any, Any] = {}

        if use_external_temp:
            schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR)] = (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                )
            )

        if use_humidity and use_external_humidity:
            schema_dict[vol.Required(CONF_HUMIDITY_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            )

        if use_humidity:
            schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["humidifier", "switch"])
            )

        # Light entity is optional; validate when provided.
        schema_dict[vol.Optional(CONF_LIGHT_ENTITY)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["light", "switch", "select"])
        )

        return self.async_show_form(
            step_id="sensors", data_schema=vol.Schema(schema_dict), errors=errors
        )

    async def async_step_light_options(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle light select entity options step."""
        if not self._step2_data:
            return await self.async_step_sensors()

        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._step1_data is not None
            if not errors:
                climate_entity = self._step1_data["climate_entity"]
                await self.async_set_unique_id(climate_entity)
                self._abort_if_unique_id_configured()

                data = {**self._step1_data}
                data[CONF_TEMPERATURE_SENSOR] = (
                    self._step2_data.get(CONF_TEMPERATURE_SENSOR) or None
                )
                data[CONF_HUMIDITY_SENSOR] = (
                    self._step2_data.get(CONF_HUMIDITY_SENSOR) or None
                )
                data[CONF_HUMIDIFIER_ENTITY] = (
                    self._step2_data.get(CONF_HUMIDIFIER_ENTITY) or None
                )

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
                data[CONF_SWING_HORIZONTAL_LOW_TEMP] = DEFAULT_SWING_MODE
                data[CONF_SWING_HORIZONTAL_HIGH_TEMP] = DEFAULT_SWING_MODE
                data[CONF_SWING_HORIZONTAL_HIGH_HUMIDITY] = DEFAULT_SWING_MODE
                data[CONF_TEMP_LOW_TEMP] = DEFAULT_TEMP_LOW_TEMP
                data[CONF_TEMP_HIGH_TEMP] = DEFAULT_TEMP_HIGH_TEMP
                data[CONF_TEMP_HIGH_HUMIDITY] = DEFAULT_TEMP_HIGH_HUMIDITY
                data[CONF_DELAY_BETWEEN_COMMANDS] = DEFAULT_DELAY_BETWEEN_COMMANDS
                data[CONF_TIMER_MINUTES] = DEFAULT_TIMER_MINUTES
                data[CONF_ENABLED] = DEFAULT_ENABLED
                data[CONF_LIGHT_ENTITY] = self._step2_data.get(CONF_LIGHT_ENTITY)
                data[CONF_LIGHT_SELECT_ON_OPTION] = user_input.get(
                    CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION
                )
                data[CONF_LIGHT_SELECT_OFF_OPTION] = user_input.get(
                    CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION
                )

                # Generate title matching device name logic
                state = self.hass.states.get(climate_entity)
                if state:
                    friendly_name = state.attributes.get("friendly_name")
                    if friendly_name:
                        # If friendly_name is just the entity_id, extract the name part
                        if friendly_name.startswith("climate."):
                            entity_name = (
                                friendly_name.split(".")[-1].replace("_", " ").title()
                            )
                            title = f"Climate React {entity_name}"
                        else:
                            title = f"Climate React {friendly_name}"
                    else:
                        entity_name = (
                            climate_entity.split(".")[-1].replace("_", " ").title()
                        )
                        title = f"Climate React {entity_name}"
                else:
                    entity_name = (
                        climate_entity.split(".")[-1].replace("_", " ").title()
                    )
                    title = f"Climate React {entity_name}"

                return self.async_create_entry(
                    title=title,
                    data=data,
                )

        schema_dict = {
            vol.Optional(
                CONF_LIGHT_SELECT_ON_OPTION, default=DEFAULT_LIGHT_SELECT_ON_OPTION
            ): selector.TextSelector(),
            vol.Optional(
                CONF_LIGHT_SELECT_OFF_OPTION, default=DEFAULT_LIGHT_SELECT_OFF_OPTION
            ): selector.TextSelector(),
        }

        return self.async_show_form(
            step_id="light_options", data_schema=vol.Schema(schema_dict), errors=errors
        )

    async def _async_create_entry_with_defaults(
        self, step1_data: UserStepData
    ) -> config_entries.FlowResult:
        """Create entry with default values when no optional features are enabled."""
        climate_entity = step1_data["climate_entity"]
        await self.async_set_unique_id(climate_entity)
        self._abort_if_unique_id_configured()

        # Use type-safe helper to create complete config data
        data = self._create_default_config_data(step1_data)
        # Override defaults for simple case
        data.update(
            {
                CONF_TEMPERATURE_SENSOR: None,
                CONF_HUMIDITY_SENSOR: None,
                CONF_HUMIDIFIER_ENTITY: None,
                CONF_LIGHT_ENTITY: None,
                CONF_ENABLE_LIGHT_CONTROL: step1_data.get(
                    "enable_light_control", DEFAULT_ENABLE_LIGHT_CONTROL
                ),
            }
        )

        # Generate title matching device name logic
        state = self.hass.states.get(climate_entity)
        if state:
            friendly_name = state.attributes.get("friendly_name")
            if friendly_name:
                # If friendly_name is just the entity_id, extract the name part
                if friendly_name.startswith("climate."):
                    entity_name = friendly_name.split(".")[-1].replace("_", " ").title()
                    title = f"Climate React {entity_name}"
                else:
                    title = f"Climate React {friendly_name}"
            else:
                entity_name = climate_entity.split(".")[-1].replace("_", " ").title()
                title = f"Climate React {entity_name}"
        else:
            entity_name = climate_entity.split(".")[-1].replace("_", " ").title()
            title = f"Climate React {entity_name}"

        return self.async_create_entry(  # type: ignore
            title=title,
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
        super().__init__()
        self._config_entry = config_entry
        self._step1_data: dict[str, Any] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
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
                default=self.config_entry.data.get(CONF_CLIMATE_ENTITY),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            vol.Optional(
                CONF_USE_EXTERNAL_TEMP_SENSOR,
                default=self.config_entry.data.get(
                    CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR
                ),
                description={
                    "suggested_value": self.config_entry.data.get(
                        CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR
                    )
                },
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_HUMIDITY,
                default=self.config_entry.data.get(
                    CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY
                ),
                description={
                    "suggested_value": self.config_entry.data.get(
                        CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY
                    )
                },
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                default=self.config_entry.data.get(
                    CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                    DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
                ),
                description={
                    "suggested_value": self.config_entry.data.get(
                        CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
                        DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR,
                    )
                },
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_AC_HUMIDITY_CONTROLS,
                default=self.config_entry.data.get(
                    CONF_AC_HUMIDITY_CONTROLS, DEFAULT_AC_HUMIDITY_CONTROLS
                ),
                description={
                    "suggested_value": self.config_entry.data.get(
                        CONF_AC_HUMIDITY_CONTROLS, DEFAULT_AC_HUMIDITY_CONTROLS
                    )
                },
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_LIGHT_CONTROL,
                default=self.config_entry.data.get(
                    CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL
                ),
                description={
                    "suggested_value": self.config_entry.data.get(
                        CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL
                    )
                },
            ): selector.BooleanSelector(),
        }

        options_schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> Any:
        """Second options step - sensors/entities based on toggles."""
        if not self._step1_data:
            return await self.async_step_init()

        errors: dict[str, str] = {}

        use_external_temp = self._step1_data.get(
            CONF_USE_EXTERNAL_TEMP_SENSOR, DEFAULT_USE_EXTERNAL_TEMP_SENSOR
        )
        use_humidity = self._step1_data.get(CONF_USE_HUMIDITY, DEFAULT_USE_HUMIDITY)
        use_external_humidity = self._step1_data.get(
            CONF_USE_EXTERNAL_HUMIDITY_SENSOR, DEFAULT_USE_EXTERNAL_HUMIDITY_SENSOR
        )
        light_control = self._step1_data.get(
            CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL
        )

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
                elif not any(
                    light_entity.startswith(domain + ".")
                    for domain in ["light", "switch", "select"]
                ):
                    errors[CONF_LIGHT_ENTITY] = "invalid_domain"

            if not errors:
                # Merge existing data with updated selections
                data = {**self.config_entry.data, **self._step1_data}
                data[CONF_TEMPERATURE_SENSOR] = (
                    user_input.get(CONF_TEMPERATURE_SENSOR) or None
                )
                data[CONF_HUMIDITY_SENSOR] = (
                    user_input.get(CONF_HUMIDITY_SENSOR) or None
                )
                data[CONF_HUMIDIFIER_ENTITY] = (
                    user_input.get(CONF_HUMIDIFIER_ENTITY) or None
                )
                data[CONF_LIGHT_ENTITY] = user_input.get(CONF_LIGHT_ENTITY) or None
                data[CONF_LIGHT_SELECT_ON_OPTION] = user_input.get(
                    CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION
                )
                data[CONF_LIGHT_SELECT_OFF_OPTION] = user_input.get(
                    CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION
                )

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=data,
                )
                # Trigger reload via abort (standard HA pattern for options flow)
                return self.async_abort(reason="reconfigure_successful")

        schema_dict: dict[Any, Any] = {}

        if use_external_temp:
            current_temp = self.config_entry.data.get(CONF_TEMPERATURE_SENSOR)
            if current_temp:
                schema_dict[
                    vol.Required(CONF_TEMPERATURE_SENSOR, default=current_temp)
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                )
            else:
                schema_dict[vol.Required(CONF_TEMPERATURE_SENSOR)] = (
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor", device_class="temperature"
                        )
                    )
                )

        if use_humidity and use_external_humidity:
            current_humidity = self.config_entry.data.get(CONF_HUMIDITY_SENSOR)
            if current_humidity:
                schema_dict[
                    vol.Required(CONF_HUMIDITY_SENSOR, default=current_humidity)
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="humidity"
                    )
                )
            else:
                schema_dict[vol.Required(CONF_HUMIDITY_SENSOR)] = (
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor", device_class="humidity"
                        )
                    )
                )

        if use_humidity:
            current_humidifier = self.config_entry.data.get(CONF_HUMIDIFIER_ENTITY)
            if current_humidifier:
                schema_dict[
                    vol.Optional(CONF_HUMIDIFIER_ENTITY, default=current_humidifier)
                ] = selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["humidifier", "switch"])
                )
            else:
                schema_dict[vol.Optional(CONF_HUMIDIFIER_ENTITY)] = (
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=["humidifier", "switch"])
                    )
                )

        if light_control:
            current_light = self.config_entry.data.get(CONF_LIGHT_ENTITY)
            if current_light:
                schema_dict[vol.Required(CONF_LIGHT_ENTITY, default=current_light)] = (
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["light", "switch", "select"]
                        )
                    )
                )
            else:
                schema_dict[vol.Required(CONF_LIGHT_ENTITY)] = selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["light", "switch", "select"])
                )
            # Add select option fields with current values or defaults
            current_on = self.config_entry.data.get(
                CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION
            )
            current_off = self.config_entry.data.get(
                CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION
            )
            schema_dict[
                vol.Optional(CONF_LIGHT_SELECT_ON_OPTION, default=current_on)
            ] = selector.TextSelector()
            schema_dict[
                vol.Optional(CONF_LIGHT_SELECT_OFF_OPTION, default=current_off)
            ] = selector.TextSelector()

        return self.async_show_form(
            step_id="sensors", data_schema=vol.Schema(schema_dict), errors=errors
        )
