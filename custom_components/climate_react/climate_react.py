"""Core Climate React controller."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.components import logbook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
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
    CONF_ENABLE_LIGHT_CONTROL,
    CONF_LIGHT_ENTITY,
    CONF_LIGHT_BEHAVIOR,
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
    CONF_TIMER_MINUTES,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_ENABLED,
    DEFAULT_ENABLE_LIGHT_CONTROL,
    DEFAULT_LIGHT_BEHAVIOR,
    DEFAULT_MIN_RUN_TIME,
    DEFAULT_TIMER_MINUTES,
    DOMAIN,
    MODE_OFF,
    LIGHT_BEHAVIOR_ON,
    LIGHT_BEHAVIOR_OFF,
    LIGHT_BEHAVIOR_UNCHANGED,
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
        self._last_mode_change_time: datetime | None = None
        self._last_set_hvac_mode: str | None = None
        self._timer_minutes: int = max(0, int(self.config.get(CONF_TIMER_MINUTES, DEFAULT_TIMER_MINUTES)))
        self._timer_task: asyncio.Task | None = None
        self._timer_listeners: list[Callable[[], None]] = []
        self._light_control_enabled: bool = bool(self.config.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL))

    @property
    def config(self) -> dict[str, Any]:
        """Get merged configuration (data + options)."""
        return {**self.entry.data, **self.entry.options}

    def _get_switch_entity_id(self) -> str:
        """Get the switch entity ID for logbook entries."""
        return f"switch.climate_react_{self.entry.entry_id.replace('-', '_')}"

    @property
    def climate_entity(self) -> str:
        """Get the climate entity ID."""
        return self.entry.data[CONF_CLIMATE_ENTITY]

    @property
    def temperature_sensor(self) -> str:
        """Get the temperature sensor entity ID (or climate entity if using built-in)."""
        use_external = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
        if use_external:
            sensor = self.entry.data.get(CONF_TEMPERATURE_SENSOR)
            if sensor:  # Only return external sensor if it's actually set
                return sensor
        return self.climate_entity

    @property
    def humidity_sensor(self) -> str | None:
        """Get the humidity sensor entity ID (or climate entity if using built-in)."""
        use_humidity = self.entry.data.get(CONF_USE_HUMIDITY, False)
        if not use_humidity:
            return None
        
        use_external = self.entry.data.get(CONF_USE_EXTERNAL_HUMIDITY_SENSOR, False)
        if use_external:
            sensor = self.entry.data.get(CONF_HUMIDITY_SENSOR)
            if sensor:  # Only return external sensor if it's actually set
                return sensor
        return self.climate_entity

    @property
    def humidifier_entity(self) -> str | None:
        """Get the humidifier entity ID."""
        return self.entry.data.get(CONF_HUMIDIFIER_ENTITY)

    @property
    def enabled(self) -> bool:
        """Check if Climate React is enabled."""
        return self._enabled

    @property
    def light_control_enabled(self) -> bool:
        """Check if light control is enabled."""
        return self._light_control_enabled

    @property
    def light_entity(self) -> str | None:
        """Light/select entity used for light control."""
        return self.config.get(CONF_LIGHT_ENTITY)

    @property
    def light_behavior(self) -> str:
        """Return configured light behavior."""
        return self.config.get(CONF_LIGHT_BEHAVIOR, DEFAULT_LIGHT_BEHAVIOR)

    def get_device_name(self) -> str:
        """Get the device name for all entities."""
        climate_entity = self.climate_entity
        state = self.hass.states.get(climate_entity)
        if state:
            friendly_name = state.attributes.get("friendly_name")
            if friendly_name:
                # If friendly_name is just the entity_id, extract the name part
                if friendly_name.startswith("climate."):
                    entity_name = friendly_name.split(".")[-1].replace("_", " ").title()
                    return f"Climate React {entity_name}"
                return f"Climate React {friendly_name}"
        # Fallback: extract entity name from entity_id (e.g., climate.study -> Study)
        entity_name = climate_entity.split(".")[-1].replace("_", " ").title()
        return f"Climate React {entity_name}"

    @property
    def timer_minutes(self) -> int:
        """Return remaining timer minutes."""
        return self._timer_minutes

    def add_timer_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback to be notified on timer updates."""
        self._timer_listeners.append(callback)

        def _remove() -> None:
            if callback in self._timer_listeners:
                self._timer_listeners.remove(callback)

        return _remove

    def _notify_timer_listeners(self) -> None:
        """Notify timer listeners of an update."""
        for listener in list(self._timer_listeners):
            listener()

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
        await self._async_start_timer_if_needed()

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
        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
            self._timer_task = None
        _LOGGER.info("Climate React controller shut down for %s", self.climate_entity)

    async def async_enable(self) -> None:
        """Enable Climate React."""
        self._enabled = True
        await self._async_evaluate_state()
        await self._async_apply_light_behavior(enabled=True)
        _LOGGER.info("Climate React enabled for %s", self.climate_entity)
        logbook.async_log_entry(
            self.hass,
            "Enabled",
            message="Climate React automation enabled",
            entity_id=self._get_switch_entity_id(),
            domain=DOMAIN,
        )

    async def async_disable(self) -> None:
        """Disable Climate React."""
        self._enabled = False
        if self._timer_minutes > 0 and self._is_climate_off():
            await self.async_set_timer(0)
        await self._async_apply_light_behavior(enabled=False)
        _LOGGER.info("Climate React disabled for %s", self.climate_entity)
        logbook.async_log_entry(
            self.hass,
            "Disabled",
            message="Climate React automation disabled",
            entity_id=self._get_switch_entity_id(),
            domain=DOMAIN,
        )

    async def async_set_light_control_enabled(self, enabled: bool) -> None:
        """Enable or disable light control and persist the choice."""
        self._light_control_enabled = enabled
        new_options = {**self.entry.options}
        new_options[CONF_ENABLE_LIGHT_CONTROL] = enabled
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        _LOGGER.info("Light control %s for %s", "enabled" if enabled else "disabled", self.climate_entity)

        # Re-apply behavior to enforce desired light state immediately
        await self._async_apply_light_behavior(enabled=self._enabled)

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

    async def async_update_option(self, key: str, value: Any) -> None:
        """Update a single config option without triggering full reload."""
        new_options = {**self.entry.options}
        new_options[key] = value
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        _LOGGER.debug("Option updated for %s: %s = %s", self.climate_entity, key, value)

    @callback
    async def _async_climate_available(self, event: Event[EventStateChangedData]) -> None:
        """Handle climate entity becoming available."""
        new_state: State | None = event.data.get("new_state")
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
    async def _async_temperature_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle temperature sensor state change.

        Always capture the reading for UI attributes; only run automation when enabled.
        """
        new_state: State | None = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            # If using climate entity, read from current_temperature attribute
            use_external = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
            if not use_external and new_state.entity_id == self.climate_entity:
                temperature = new_state.attributes.get("current_temperature")
                if temperature is None:
                    return
                temperature = float(temperature)
            else:
                temperature = float(new_state.state)
            
            # Always keep the last reading for UI/diagnostics
            self._last_temp = temperature
            _LOGGER.debug("Temperature changed to %.1f°C for %s", temperature, self.climate_entity)

            # Only run automation when enabled
            if self._enabled:
                await self._async_handle_temperature_threshold(temperature)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid temperature state: %s (%s)", new_state.state, err)

    @callback
    async def _async_climate_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Detect manual mode changes outside of automation."""
        new_state: State | None = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        # If automation is disabled and a timer is running, reset when climate is off
        if not self._enabled and self._timer_minutes > 0 and self._is_climate_off_state(new_state):
            await self.async_set_timer(0)
            return

        if not self._enabled:
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
            await self._async_apply_light_behavior(enabled=False)

    @callback
    async def _async_humidity_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle humidity sensor state change.

        Always capture the reading for UI attributes; only run automation when enabled.
        """

        new_state: State | None = event.data.get("new_state")
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

            # Only run automation when enabled
            if self._enabled:
                await self._async_handle_humidity_threshold(humidity)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid humidity state: %s (%s)", new_state.state, err)

    async def _async_evaluate_state(self) -> None:
        """Evaluate current sensor states."""
        # Get current temperature
        temp_state = self.hass.states.get(self.temperature_sensor)
        if temp_state and temp_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                # If using climate entity, read from current_temperature attribute
                use_external_temp = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
                if not use_external_temp and temp_state.entity_id == self.climate_entity:
                    temperature = temp_state.attributes.get("current_temperature")
                    if temperature is not None:
                        temperature = float(temperature)
                        self._last_temp = temperature
                        if self._enabled:
                            await self._async_handle_temperature_threshold(temperature)
                else:
                    temperature = float(temp_state.state)
                    self._last_temp = temperature
                    if self._enabled:
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
                            humidity = float(humidity)
                            self._last_humidity = humidity
                            if self._enabled:
                                await self._async_handle_humidity_threshold(humidity)
                    else:
                        humidity = float(humidity_state.state)
                        self._last_humidity = humidity
                        if self._enabled:
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
            logbook.async_log_entry(
                self.hass,
                "Low Temperature",
                message=f"Temperature {temperature:.1f}°C below minimum {min_temp:.1f}°C - switching to {mode}",
                entity_id=self._get_switch_entity_id(),
                domain=DOMAIN,
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
            logbook.async_log_entry(
                self.hass,
                "High Temperature",
                message=f"Temperature {temperature:.1f}°C above maximum {max_temp:.1f}°C - switching to {mode}",
                entity_id=self._get_switch_entity_id(),
                domain=DOMAIN,
            )
            
            await self._async_set_climate(mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp)
        else:
            _LOGGER.debug(
                "Temperature %.1f°C within range [%.1f, %.1f] for %s",
                temperature, min_temp, max_temp, self.climate_entity
            )

    async def _async_handle_humidity_threshold(self, humidity: float) -> None:
        """Handle humidity threshold logic."""
        if not self._can_change_mode():
            _LOGGER.debug(
                "Humidity threshold triggered but minimum run time not elapsed for %s",
                self.climate_entity
            )
            return
        
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
                logbook.async_log_entry(
                    self.hass,
                    "Low Humidity",
                    message=f"Humidity {humidity:.1f}% below minimum {min_humidity:.1f}% - turning on humidifier",
                    entity_id=self._get_switch_entity_id(),
                    domain=DOMAIN,
                )
                # Determine the correct domain based on entity_id
                domain = self.humidifier_entity.split(".")[0]
                service = "turn_on"
                await self.hass.services.async_call(
                    domain,
                    service,
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
                logbook.async_log_entry(
                    self.hass,
                    "High Humidity",
                    message=f"Humidity {humidity:.1f}% above maximum {max_humidity:.1f}% - turned off humidifier",
                    entity_id=self._get_switch_entity_id(),
                    domain=DOMAIN,
                )
                # Determine the correct domain based on entity_id
                domain = self.humidifier_entity.split(".")[0]
                service = "turn_off"
                await self.hass.services.async_call(
                    domain,
                    service,
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

        # Skip ancillary calls (fan/swing/temperature) when HVAC is off unless we are turning it on now.
        current_state = climate_state.state if climate_state else None
        turning_off = hvac_mode == MODE_OFF
        staying_off = hvac_mode is None and current_state == MODE_OFF
        allow_auxiliary_calls = not (turning_off or staying_off)

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
        delay_seconds = config.get(CONF_DELAY_BETWEEN_COMMANDS, DEFAULT_DELAY_BETWEEN_COMMANDS) / 1000.0

        # Optionally toggle display light off before commands (mirrors Node-RED flow) and back on after.
        light_entity = self.light_entity if self._light_control_enabled else None
        light_behavior = self.light_behavior
        toggle_light = light_entity and light_behavior != LIGHT_BEHAVIOR_UNCHANGED
        if toggle_light:
            assert light_entity is not None
            await self._async_set_light(light_entity, "off")
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

        # Set HVAC mode - use turn_on/off when possible, set_hvac_mode only when changing modes
        if hvac_mode and hvac_mode != (climate_state.state if climate_state else None):
            if hvac_mode == MODE_OFF:
                # Turning off - use turn_off service
                await self.hass.services.async_call(
                    "climate",
                    "turn_off",
                    {"entity_id": self.climate_entity},
                    blocking=True,
                )
                # Verify it's actually off, fall back to set_hvac_mode if not
                climate_state = self.hass.states.get(self.climate_entity)
                if climate_state and climate_state.state != MODE_OFF:
                    _LOGGER.debug(
                        "turn_off didn't set mode to off for %s, using set_hvac_mode fallback",
                        self.climate_entity,
                    )
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": self.climate_entity, "hvac_mode": MODE_OFF},
                        blocking=True,
                    )
            elif climate_state and climate_state.state == MODE_OFF:
                # Currently off, turning on - use turn_on service
                await self.hass.services.async_call(
                    "climate",
                    "turn_on",
                    {"entity_id": self.climate_entity},
                    blocking=True,
                )
                # Verify it's in the correct mode, fall back to set_hvac_mode if not
                climate_state = self.hass.states.get(self.climate_entity)
                if climate_state and (climate_state.state == MODE_OFF or climate_state.state != hvac_mode):
                    _LOGGER.debug(
                        "turn_on didn't set %s to required mode %s (current: %s), using set_hvac_mode fallback",
                        self.climate_entity,
                        hvac_mode,
                        climate_state.state,
                    )
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": self.climate_entity, "hvac_mode": hvac_mode},
                        blocking=True,
                    )
            else:
                # Mode change (e.g., heat to cool) - use set_hvac_mode
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

        # Refresh climate state after HVAC changes to get updated attributes
        climate_state = self.hass.states.get(self.climate_entity)

        # Set temperature if provided
        if allow_auxiliary_calls and target_temp is not None and climate_state:
            current_target_temp = climate_state.attributes.get("temperature")
            # Only set if different or not currently set
            if current_target_temp == target_temp:
                _LOGGER.debug("Temperature already at %.1f°C for %s, skipping", target_temp, self.climate_entity)
            elif current_target_temp != target_temp:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": self.climate_entity, "temperature": target_temp},
                    blocking=True,
                )
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

        # Set fan mode if supported and specified
        if allow_auxiliary_calls and fan_mode and climate_state and climate_state.attributes.get("fan_modes"):
            current_fan_mode = climate_state.attributes.get("current_fan_mode")
            # Only set if different from current
            if current_fan_mode == fan_mode:
                _LOGGER.debug("Fan mode already set to %s for %s, skipping", fan_mode, self.climate_entity)
            elif current_fan_mode != fan_mode:
                await self.hass.services.async_call(
                    "climate",
                    "set_fan_mode",
                    {"entity_id": self.climate_entity, "fan_mode": fan_mode},
                    blocking=True,
                )
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

        # Set swing mode if supported and specified
        if allow_auxiliary_calls and swing_mode and climate_state and climate_state.attributes.get("swing_modes"):
            current_swing_mode = climate_state.attributes.get("swing_mode")
            # Only set if different from current
            if current_swing_mode == swing_mode:
                _LOGGER.debug("Swing mode already set to %s for %s, skipping", swing_mode, self.climate_entity)
            elif current_swing_mode != swing_mode:
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
            allow_auxiliary_calls
            and swing_horizontal_mode
            and climate_state
            and climate_state.attributes.get("swing_horizontal_modes")
        ):
            current_swing_horizontal = climate_state.attributes.get("swing_horizontal_mode")
            # Only set if different from current
            if current_swing_horizontal == swing_horizontal_mode:
                _LOGGER.debug("Swing horizontal mode already set to %s for %s, skipping", swing_horizontal_mode, self.climate_entity)
            elif current_swing_horizontal != swing_horizontal_mode:
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

        if toggle_light:
            assert light_entity is not None
            await self._async_set_light(light_entity, "on")
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

    async def _async_set_light(self, entity_id: str, option: str) -> None:
        """Set light control entity (light, switch, or select) to on/off.
        
        For select entities, uses configured on/off option values from config.
        """
        domain = entity_id.split(".")[0] if "." in entity_id else None
        if not domain:
            _LOGGER.warning("Invalid entity_id format: %s", entity_id)
            return

        # Check current state before sending command
        light_state = self.hass.states.get(entity_id)
        if not light_state:
            _LOGGER.debug("Light entity %s not found", entity_id)
            return

        try:
            if domain == "select":
                # For select entities, map on/off to configured select options
                from .const import (
                    CONF_LIGHT_SELECT_ON_OPTION,
                    CONF_LIGHT_SELECT_OFF_OPTION,
                    DEFAULT_LIGHT_SELECT_ON_OPTION,
                    DEFAULT_LIGHT_SELECT_OFF_OPTION,
                )
                
                if option == "on":
                    select_option = self.config.get(CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION)
                else:
                    select_option = self.config.get(CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION)
                
                # Only set if different from current
                current_option = light_state.state
                if current_option != select_option:
                    await self.hass.services.async_call(
                        "select",
                        "select_option",
                        {"entity_id": entity_id, "option": select_option},
                        blocking=True,
                    )
            elif domain in ("light", "switch"):
                # For light/switch entities, check current state before toggling
                service = "turn_on" if option == "on" else "turn_off"
                current_state = light_state.state
                target_state = "on" if option == "on" else "off"
                
                # Only set if different from current
                if current_state != target_state:
                    await self.hass.services.async_call(
                        domain,
                        service,
                        {"entity_id": entity_id},
                        blocking=True,
                    )
            else:
                _LOGGER.warning("Unsupported light control entity domain: %s", domain)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Failed to set light %s to %s: %s", entity_id, option, exc)

    async def async_set_timer(self, minutes: float) -> None:
        """Set or reset the minute countdown timer."""
        new_minutes = max(0, int(minutes))

        # If timer requested while both automation and climate are off, reset to zero
        if new_minutes > 0 and not self._enabled and self._is_climate_off():
            new_minutes = 0

        # Cancel existing task
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

        self._timer_minutes = new_minutes
        await self._async_persist_timer()
        self._notify_timer_listeners()

        if self._timer_minutes > 0:
            self._timer_task = self.hass.loop.create_task(self._async_timer_loop())
            _LOGGER.info("Timer started for %s: %d minutes", self.climate_entity, self._timer_minutes)
        else:
            _LOGGER.debug("Timer cleared for %s", self.climate_entity)

    async def _async_start_timer_if_needed(self) -> None:
        """Restart timer loop on setup if there is remaining time."""
        if self._timer_minutes > 0 and not self._timer_task:
            self._timer_task = self.hass.loop.create_task(self._async_timer_loop())

    async def _async_timer_loop(self) -> None:
        """Countdown timer loop."""
        try:
            while self._timer_minutes > 0:
                await asyncio.sleep(60)
                self._timer_minutes -= 1
                await self._async_persist_timer()
                self._notify_timer_listeners()

                if self._timer_minutes == 0:
                    await self._async_handle_timer_expired()
                    break
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled for %s", self.climate_entity)
        finally:
            self._timer_task = None

    async def _async_handle_timer_expired(self) -> None:
        """Handle actions when timer reaches zero."""
        _LOGGER.info("Timer expired for %s", self.climate_entity)

        if self._enabled:
            await self.async_disable()
        else:
            # Turn off climate if not already off
            climate_state = self.hass.states.get(self.climate_entity)
            if climate_state and not self._is_climate_off_state(climate_state):
                await self.hass.services.async_call(
                    "climate",
                    "turn_off",
                    {"entity_id": self.climate_entity},
                    blocking=True,
                )

        self._timer_minutes = 0
        await self._async_persist_timer()
        self._notify_timer_listeners()
        await self._async_apply_light_behavior(enabled=False)

    async def _async_persist_timer(self) -> None:
        """Persist timer value to config entry options."""
        new_options = {**self.entry.options}
        new_options[CONF_TIMER_MINUTES] = self._timer_minutes
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

    async def _async_apply_light_behavior(self, enabled: bool) -> None:
        """Apply configured light behavior when automation toggles."""
        if not self._light_control_enabled:
            return
        light_entity = self.light_entity
        if not light_entity:
            return
        behavior = self.light_behavior
        if behavior == LIGHT_BEHAVIOR_UNCHANGED:
            return

        desired = None
        if behavior == LIGHT_BEHAVIOR_ON:
            desired = "on" if enabled else "off"
        elif behavior == LIGHT_BEHAVIOR_OFF:
            desired = "off" if enabled else "on"

        if desired:
            await self._async_set_light(light_entity, desired)

    def _is_climate_off(self) -> bool:
        """Return True if climate entity is currently off."""
        state = self.hass.states.get(self.climate_entity)
        return self._is_climate_off_state(state)

    @staticmethod
    def _is_climate_off_state(state: State | None) -> bool:
        if not state:
            return True
        return state.state == MODE_OFF or state.state == "off"
