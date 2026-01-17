"""Core Climate React controller."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DELAY_BETWEEN_COMMANDS,
    CONF_ENABLED,
    CONF_FAN_HIGH_HUMIDITY,
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_MIN_RUN_TIME,
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
    CONF_SWING_HIGH_HUMIDITY,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_LOW_TEMP,
    CONF_SWING_HORIZONTAL_HIGH_HUMIDITY,
    CONF_SWING_HORIZONTAL_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_LOW_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMP_HIGH_HUMIDITY,
    CONF_TEMP_HIGH_TEMP,
    CONF_TEMP_LOW_TEMP,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_ENABLED,
)

_LOGGER = logging.getLogger(__name__)


class ClimateReactController:
    """Controller for Climate React automation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the controller."""
        self.hass = hass
        self.entry = entry
        self._unsub_temp = None
        self._unsub_humidity = None
        self._unsub_climate = None
        self._unsub_climate_availability = None
        self._enabled = entry.data.get(CONF_ENABLED, DEFAULT_ENABLED)
        self._last_temp = None
        self._last_humidity = None
        self._warned_horizontal_service_missing = False
        self._climate_min_temp: float | None = None
        self._climate_max_temp: float | None = None
        self._last_mode_change_time: float | None = None
        self._last_set_hvac_mode: str | None = None

    @property
    def config(self) -> dict[str, Any]:
        """Get merged configuration (data + options)."""
        return {**self.entry.data, **self.entry.options}

    @property
    def climate_entity(self) -> str:
        """Get the climate entity ID."""
        return self.entry.data[CONF_CLIMATE_ENTITY]

    @property
    def temperature_sensor(self) -> str:
        """Get the temperature sensor entity ID (or climate entity if using built-in)."""
        use_external = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
        if use_external:
            return self.entry.data.get(CONF_TEMPERATURE_SENSOR, self.climate_entity)
        return self.climate_entity

    @property
    def humidity_sensor(self) -> str | None:
        """Get the humidity sensor entity ID (or climate entity if using built-in)."""
        use_humidity = self.entry.data.get(CONF_USE_HUMIDITY, False)
        if not use_humidity:
            return None
        
        use_external = self.entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, False)
        if use_external:
            return self.entry.data.get(CONF_HUMIDITY_SENSOR, self.climate_entity)
        return self.climate_entity

    @property
    def humidifier_entity(self) -> str | None:
        """Get the humidifier entity ID."""
        return self.entry.data.get(CONF_HUMIDIFIER_ENTITY)

    @property
    def enabled(self) -> bool:
        """Check if Climate React is enabled."""
        return self._enabled

    def _can_change_mode(self) -> bool:
        """Check if minimum run time has elapsed since last mode change."""
        if self._last_mode_change_time is None:
            return True
        
        config = self.config
        min_run_time = config.get(CONF_MIN_RUN_TIME, DEFAULT_MIN_RUN_TIME)
        elapsed = datetime.now() - self._last_mode_change_time
        
        return elapsed >= timedelta(minutes=min_run_time)

    async def async_setup(self) -> None:
        """Set up the controller."""
        # Subscribe to temperature sensor state changes
        self._unsub_temp = async_track_state_change_event(
            self.hass,
            [self.temperature_sensor],
            self._async_temperature_changed,
        )

        # Subscribe to humidity sensor if configured
        if self.humidity_sensor:
            self._unsub_humidity = async_track_state_change_event(
                self.hass,
                [self.humidity_sensor],
                self._async_humidity_changed,
            )

        # Subscribe to climate entity changes for manual override detection
        self._unsub_climate = async_track_state_change_event(
            self.hass,
            [self.climate_entity],
            self._async_climate_state_changed,
        )

        # Watch climate entity availability to re-evaluate when it comes online
        self._unsub_climate_availability = async_track_state_change_event(
            self.hass,
            [self.climate_entity],
            self._async_climate_available,
        )

        # Initial state evaluation
        await self._async_evaluate_state()

        _LOGGER.info(
            "Climate React controller initialized for %s (temp: %s, humidity: %s)",
            self.climate_entity,
            self.temperature_sensor,
            self.humidity_sensor or "not configured",
        )

    async def async_shutdown(self) -> None:
        """Shut down the controller."""
        if self._unsub_temp:
            self._unsub_temp()
        if self._unsub_humidity:
            self._unsub_humidity()
        if self._unsub_climate:
            self._unsub_climate()
        if self._unsub_climate_availability:
            self._unsub_climate_availability()
        _LOGGER.info("Climate React controller shut down for %s", self.climate_entity)

    async def async_enable(self) -> None:
        """Enable Climate React."""
        self._enabled = True
        await self._async_evaluate_state()
        _LOGGER.info("Climate React enabled for %s", self.climate_entity)

    async def async_disable(self) -> None:
        """Disable Climate React."""
        self._enabled = False
        _LOGGER.info("Climate React disabled for %s", self.climate_entity)

    async def async_update_thresholds(self, data: dict[str, Any]) -> None:
        """Update thresholds dynamically."""
        # Update config entry options
        new_options = {**self.entry.options}
        
        if "min_temp" in data:
            new_options[CONF_MIN_TEMP] = data["min_temp"]
        if "max_temp" in data:
            new_options[CONF_MAX_TEMP] = data["max_temp"]
        if "min_humidity" in data:
            new_options[CONF_MIN_HUMIDITY] = data["min_humidity"]
        if "max_humidity" in data:
            new_options[CONF_MAX_HUMIDITY] = data["max_humidity"]
        
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        
        # Re-evaluate state with new thresholds
        await self._async_evaluate_state()
        
        _LOGGER.info("Thresholds updated for %s: %s", self.climate_entity, data)

    @callback
    async def _async_climate_available(self, event: Event) -> None:
        """Handle climate entity becoming available."""
        new_state: State = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        await self._async_sync_thresholds_to_climate(new_state)
        await self._async_evaluate_state()

    async def _async_sync_thresholds_to_climate(self, climate_state: State) -> None:
        """Sync configured thresholds to climate entity limits."""
        # Extract climate limits
        climate_min_temp = climate_state.attributes.get("min_temp")
        climate_max_temp = climate_state.attributes.get("max_temp")
        
        if climate_min_temp is not None:
            self._climate_min_temp = float(climate_min_temp)
        if climate_max_temp is not None:
            self._climate_max_temp = float(climate_max_temp)
        
        # Validate and clamp configured thresholds
        config = self.config
        needs_update = False
        new_options = {**self.entry.options}
        
        # Clamp min_temp
        configured_min_temp = config.get(CONF_MIN_TEMP, 18.0)
        if self._climate_min_temp is not None and configured_min_temp < self._climate_min_temp:
            _LOGGER.warning(
                "Configured min_temp %.1f°C is below climate entity minimum %.1f°C; clamping",
                configured_min_temp,
                self._climate_min_temp,
            )
            new_options[CONF_MIN_TEMP] = self._climate_min_temp
            needs_update = True
        
        # Clamp max_temp
        configured_max_temp = config.get(CONF_MAX_TEMP, 26.0)
        if self._climate_max_temp is not None and configured_max_temp > self._climate_max_temp:
            _LOGGER.warning(
                "Configured max_temp %.1f°C is above climate entity maximum %.1f°C; clamping",
                configured_max_temp,
                self._climate_max_temp,
            )
            new_options[CONF_MAX_TEMP] = self._climate_max_temp
            needs_update = True
        
        # Ensure min <= max
        final_min = new_options.get(CONF_MIN_TEMP, configured_min_temp)
        final_max = new_options.get(CONF_MAX_TEMP, configured_max_temp)
        if final_min > final_max:
            _LOGGER.warning(
                "min_temp %.1f°C > max_temp %.1f°C; swapping values",
                final_min,
                final_max,
            )
            new_options[CONF_MIN_TEMP] = final_max
            new_options[CONF_MAX_TEMP] = final_min
            needs_update = True
        
        if needs_update:
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)

    @callback
    async def _async_temperature_changed(self, event: Event) -> None:
        """Handle temperature sensor state change."""
        if not self._enabled:
            return

        new_state: State = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            # If using climate entity, read from current_temperature attribute
            use_external = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
            if not use_external and new_state.entity_id == self.climate_entity:
                temperature = new_state.attributes.get("current_temperature")
                if temperature is None:
                    return
            else:
                temperature = float(new_state.state)
            
            temperature = float(temperature)
            self._last_temp = temperature
            _LOGGER.debug("Temperature changed to %.1f°C for %s", temperature, self.climate_entity)
            await self._async_handle_temperature_threshold(temperature)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid temperature state: %s (%s)", new_state.state, err)

    @callback
    async def _async_climate_state_changed(self, event: Event) -> None:
        """Detect manual mode changes outside of automation."""
        if not self._enabled:
            return

        new_state: State = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        current_mode = new_state.state
        
        # If we set a mode and it changed to something else, it's a manual override
        if self._last_set_hvac_mode is not None and current_mode != self._last_set_hvac_mode:
            _LOGGER.warning(
                "Manual override detected on %s: mode changed from %s (automation) to %s (manual). "
                "Disabling Climate React to prevent conflicts.",
                self.climate_entity,
                self._last_set_hvac_mode,
                current_mode,
            )
            self._enabled = False
            self._last_set_hvac_mode = None

    @callback
    async def _async_humidity_changed(self, event: Event) -> None:
        """Handle humidity sensor state change."""
        if not self._enabled:
            return

        new_state: State = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            # If using climate entity, read from current_humidity attribute
            use_external = self.entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, False)
            if not use_external and new_state.entity_id == self.climate_entity:
                humidity = new_state.attributes.get("current_humidity")
                if humidity is None:
                    return
            else:
                humidity = float(new_state.state)
            
            humidity = float(humidity)
            self._last_humidity = humidity
            _LOGGER.debug("Humidity changed to %.1f%% for %s", humidity, self.climate_entity)
            await self._async_handle_humidity_threshold(humidity)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid humidity state: %s (%s)", new_state.state, err)

    async def _async_evaluate_state(self) -> None:
        """Evaluate current sensor states."""
        if not self._enabled:
            return

        # Get current temperature
        temp_state = self.hass.states.get(self.temperature_sensor)
        if temp_state and temp_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                # If using climate entity, read from current_temperature attribute
                use_external_temp = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
                if not use_external_temp and temp_state.entity_id == self.climate_entity:
                    temperature = temp_state.attributes.get("current_temperature")
                    if temperature is not None:
                        self._last_temp = float(temperature)
                        await self._async_handle_temperature_threshold(float(temperature))
                else:
                    temperature = float(temp_state.state)
                    self._last_temp = temperature
                    await self._async_handle_temperature_threshold(temperature)
            except (ValueError, TypeError):
                pass

        # Get current humidity if configured
        if self.humidity_sensor:
            humidity_state = self.hass.states.get(self.humidity_sensor)
            if humidity_state and humidity_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    # If using climate entity, read from current_humidity attribute
                    use_external_humidity = self.entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, False)
                    if not use_external_humidity and humidity_state.entity_id == self.climate_entity:
                        humidity = humidity_state.attributes.get("current_humidity")
                        if humidity is not None:
                            self._last_humidity = float(humidity)
                            await self._async_handle_humidity_threshold(float(humidity))
                    else:
                        humidity = float(humidity_state.state)
                        self._last_humidity = humidity
                        await self._async_handle_humidity_threshold(humidity)
                except (ValueError, TypeError):
                    pass

    async def _async_handle_temperature_threshold(self, temperature: float) -> None:
        """Handle temperature threshold logic."""
        if not self._can_change_mode():
            _LOGGER.debug(
                "Temperature threshold triggered but minimum run time not elapsed for %s",
                self.climate_entity
            )
            return
        
        config = self.config
        min_temp = config[CONF_MIN_TEMP]
        max_temp = config[CONF_MAX_TEMP]
        
        # Clamp to climate limits if available
        if self._climate_min_temp is not None:
            min_temp = max(min_temp, self._climate_min_temp)
        if self._climate_max_temp is not None:
            max_temp = min(max_temp, self._climate_max_temp)

        # Determine action based on thresholds
        if temperature < min_temp:
            # Low temperature - trigger heating
            mode = config[CONF_MODE_LOW_TEMP]
            fan_mode = config.get(CONF_FAN_LOW_TEMP)
            swing_mode = config.get(CONF_SWING_LOW_TEMP)
            swing_horizontal_mode = config.get(CONF_SWING_HORIZONTAL_LOW_TEMP)
            target_temp = config.get(CONF_TEMP_LOW_TEMP)
            
            _LOGGER.info(
                "Temperature %.1f°C < %.1f°C (min) for %s - setting mode to %s",
                temperature, min_temp, self.climate_entity, mode
            )
            
            await self._async_set_climate(mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp)
            
        elif temperature > max_temp:
            # High temperature - trigger cooling
            mode = config[CONF_MODE_HIGH_TEMP]
            fan_mode = config.get(CONF_FAN_HIGH_TEMP)
            swing_mode = config.get(CONF_SWING_HIGH_TEMP)
            swing_horizontal_mode = config.get(CONF_SWING_HORIZONTAL_HIGH_TEMP)
            target_temp = config.get(CONF_TEMP_HIGH_TEMP)
            
            _LOGGER.info(
                "Temperature %.1f°C > %.1f°C (max) for %s - setting mode to %s",
                temperature, max_temp, self.climate_entity, mode
            )
            
            await self._async_set_climate(mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp)
        else:
            _LOGGER.debug(
                "Temperature %.1f°C within range [%.1f, %.1f] for %s",
                temperature, min_temp, max_temp, self.climate_entity
            )

    async def _async_handle_humidity_threshold(self, humidity: float) -> None:
        """Handle humidity threshold logic."""
        config = self.config
        min_humidity = config.get(CONF_MIN_HUMIDITY)
        max_humidity = config.get(CONF_MAX_HUMIDITY)
        
        # Check if humidity is too low (turn on humidifier)
        if min_humidity and humidity < min_humidity:
            if self.humidifier_entity:
                _LOGGER.info(
                    "Humidity %.1f%% < %.1f%% (min) for %s - turning on humidifier %s",
                    humidity, min_humidity, self.climate_entity, self.humidifier_entity
                )
                await self.hass.services.async_call(
                    "humidifier",
                    "turn_on",
                    {"entity_id": self.humidifier_entity},
                    blocking=True,
                )
            else:
                _LOGGER.debug(
                    "Humidity %.1f%% < %.1f%% (min) but no humidifier configured",
                    humidity, min_humidity
                )
        # Check if humidity is too high (turn off humidifier and/or trigger dehumidify mode)
        elif max_humidity and humidity > max_humidity:
            # Turn off humidifier if it's on
            if self.humidifier_entity:
                _LOGGER.debug(
                    "Humidity %.1f%% > %.1f%% (max) - turning off humidifier %s",
                    humidity, max_humidity, self.humidifier_entity
                )
                await self.hass.services.async_call(
                    "humidifier",
                    "turn_off",
                    {"entity_id": self.humidifier_entity},
                    blocking=True,
                )
            
            # Trigger dehumidify mode on climate entity
            mode = config.get(CONF_MODE_HIGH_HUMIDITY)
            fan_mode = config.get(CONF_FAN_HIGH_HUMIDITY)
            swing_mode = config.get(CONF_SWING_HIGH_HUMIDITY)
            swing_horizontal_mode = config.get(CONF_SWING_HORIZONTAL_HIGH_HUMIDITY)
            target_temp = config.get(CONF_TEMP_HIGH_HUMIDITY)
            
            _LOGGER.info(
                "Humidity %.1f%% > %.1f%% (max) for %s - setting mode to %s",
                humidity, max_humidity, self.climate_entity, mode
            )
            
            await self._async_set_climate(mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp)
        else:
            # Humidity is within acceptable range - turn off humidifier
            if self.humidifier_entity:
                _LOGGER.debug(
                    "Humidity %.1f%% within range [%.1f, %.1f] - turning off humidifier %s",
                    humidity, min_humidity or 0, max_humidity or 100, self.humidifier_entity
                )
                await self.hass.services.async_call(
                    "humidifier",
                    "turn_off",
                    {"entity_id": self.humidifier_entity},
                    blocking=True,
                )
            _LOGGER.debug(
                "Humidity %.1f%% within acceptable range for %s",
                humidity, self.climate_entity
            )

    async def _async_set_climate(
        self,
        hvac_mode: str | None,
        fan_mode: str | None,
        swing_mode: str | None,
        swing_horizontal_mode: str | None,
        target_temp: float | None = None,
    ) -> None:
        """Set climate entity mode, fan, swing, and temperature with configurable delays."""
        climate_state = self.hass.states.get(self.climate_entity)
        config = self.config

        def _clamp(option: str | None, supported_attr: str) -> str | None:
            if not option:
                return None
            if not climate_state:
                return option
            supported = climate_state.attributes.get(supported_attr)
            if isinstance(supported, list) and option not in supported:
                # choose first supported option if available
                return supported[0] if supported else None
            return option

        hvac_mode = _clamp(hvac_mode, "hvac_modes")
        fan_mode = _clamp(fan_mode, "fan_modes")
        swing_mode = _clamp(swing_mode, "swing_modes")
        swing_horizontal_mode = _clamp(swing_horizontal_mode, "swing_horizontal_modes")

        # Get configured delay in milliseconds, convert to seconds
        import asyncio
        delay_seconds = config.get(CONF_DELAY_BETWEEN_COMMANDS, DEFAULT_DELAY_BETWEEN_COMMANDS) / 1000.0

        # Set HVAC mode
        if hvac_mode:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.climate_entity, "hvac_mode": hvac_mode},
                blocking=True,
            )
            self._last_set_hvac_mode = hvac_mode
            self._last_mode_change_time = datetime.now()
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        # Set temperature if provided
        if target_temp is not None and climate_state:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": self.climate_entity, "temperature": target_temp},
                blocking=True,
            )
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        # Set fan mode if supported and specified
        if fan_mode and climate_state and climate_state.attributes.get("fan_modes"):
            await self.hass.services.async_call(
                "climate",
                "set_fan_mode",
                {"entity_id": self.climate_entity, "fan_mode": fan_mode},
                blocking=True,
            )
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        # Set swing mode if supported and specified
        if swing_mode and climate_state and climate_state.attributes.get("swing_modes"):
            await self.hass.services.async_call(
                "climate",
                "set_swing_mode",
                {"entity_id": self.climate_entity, "swing_mode": swing_mode},
                blocking=True,
            )
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        # Set horizontal swing mode if supported and service available
        if (
            swing_horizontal_mode
            and climate_state
            and climate_state.attributes.get("swing_horizontal_modes")
        ):
            if self.hass.services.has_service("climate", "set_swing_horizontal_mode"):
                await self.hass.services.async_call(
                    "climate",
                    "set_swing_horizontal_mode",
                    {
                        "entity_id": self.climate_entity,
                        "swing_horizontal_mode": swing_horizontal_mode,
                    },
                    blocking=True,
                )
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
            else:
                if not self._warned_horizontal_service_missing:
                    _LOGGER.warning(
                        "Horizontal swing mode requested (%s) but climate domain has no set_swing_horizontal_mode service",
                        swing_horizontal_mode,
                    )
                    self._warned_horizontal_service_missing = True
