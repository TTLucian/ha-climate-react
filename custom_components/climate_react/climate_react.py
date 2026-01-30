"""Core Climate React controller."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, TypedDict

from homeassistant.components import logbook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    BASE_RETRY_DELAY_SECONDS,
    CAPABILITY_CACHE_DURATION_SECONDS,
    CIRCUIT_BREAKER_MAX_FAILURES,
    CIRCUIT_BREAKER_TIMEOUT_SECONDS,
    CONF_CLIMATE_ENTITY,
    CONF_DELAY_BETWEEN_COMMANDS,
    CONF_ENABLE_LIGHT_CONTROL,
    CONF_ENABLED,
    CONF_FAN_HIGH_HUMIDITY,
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LAST_MODE_CHANGE_TIME,
    CONF_LAST_SET_HVAC_MODE,
    CONF_LIGHT_BEHAVIOR,
    CONF_LIGHT_ENTITY,
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
    CONF_TIMER_EXPIRY,
    CONF_TIMER_MINUTES,
    CONF_USE_EXTERNAL_HUMIDITY_SENSOR,
    CONF_USE_EXTERNAL_TEMP_SENSOR,
    CONF_USE_HUMIDITY,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_ENABLE_LIGHT_CONTROL,
    DEFAULT_ENABLED,
    DEFAULT_LIGHT_BEHAVIOR,
    DEFAULT_MIN_RUN_TIME,
    DEFAULT_TIMER_MINUTES,
    DOMAIN,
    LIGHT_BEHAVIOR_OFF,
    LIGHT_BEHAVIOR_ON,
    LIGHT_BEHAVIOR_UNCHANGED,
    MAX_CONCURRENT_BACKGROUND_TASKS,
    MAX_RETRY_ATTEMPTS,
    MAX_STATE_LOG_ENTRIES,
    MODE_OFF,
)


class StateChangeDetails(TypedDict, total=False):
    """Type definition for state change log details."""

    temperature: float | None
    threshold: float | None
    action: str | None
    mode: str | None
    humidity: float | None
    action_taken: str | None
    humidifier_entity: str | None
    old_mode: str | None
    new_mode: str | None
    operation: str | None
    details: str | None
    fan_mode: str | None
    swing_mode: str | None
    swing_horizontal_mode: str | None
    target_temp: float | None
    delay_seconds: float | None
    reason: str | None
    last_change: str | None
    entity: str | None
    enabled: bool | None
    timer_minutes: int | None
    timer_expiry: float | None
    climate_entity: str | None
    current_mode: str | None
    manual_override: bool | None


class ClimateCommand(TypedDict, total=False):
    """Type definition for climate command parameters."""

    hvac_mode: str | None
    fan_mode: str | None
    swing_mode: str | None
    swing_horizontal_mode: str | None
    target_temp: float | None


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
        self._cached_config: dict[str, Any] | None = None  # Cache for merged config
        # Initialize timer expiry timestamp (migrate from old minutes format if needed)
        config_data = {**entry.data, **entry.options}
        self._timer_expiry: Optional[float] = None

        # Add locks for thread safety (consolidated for better performance)
        # Lock hierarchy (acquire in this order only to prevent deadlocks):
        # 1. _config_lock (config operations)
        # 2. _state_lock (sensor readings + basic state + thresholds)
        # 3. _service_lock (service calls + circuit breaker + logging)
        self._config_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._service_lock = asyncio.Lock()

        # Circuit breaker for service call failures
        self._service_call_failures: dict[str, int] = {}
        self._service_call_last_failure: dict[str, float] = {}
        self._circuit_breaker_threshold = CIRCUIT_BREAKER_MAX_FAILURES
        self._circuit_breaker_timeout = CIRCUIT_BREAKER_TIMEOUT_SECONDS

        # Climate entity capability validation
        self._validated_capabilities: dict[str, set[str]] = {}
        self._capability_validation_time: dict[str, float] = {}

        # Enhanced state change tracking for debugging
        self._state_change_log = deque(maxlen=MAX_STATE_LOG_ENTRIES)

        # Sensor change debouncing to prevent excessive evaluations
        self._debounce_temp_timer: asyncio.TimerHandle | None = None
        self._debounce_humidity_timer: asyncio.TimerHandle | None = None
        self._pending_temperature: float | None = None
        self._pending_humidity: float | None = None

        # Task throttling
        self._task_semaphore = asyncio.Semaphore(MAX_CONCURRENT_BACKGROUND_TASKS)

        # Task queue for efficient background processing
        self._task_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._task_processor_task: asyncio.Task | None = None

        # Pre-allocated common objects for performance
        self._empty_details = {}

        # Check for new expiry format first
        expiry_value = config_data.get(CONF_TIMER_EXPIRY)
        if expiry_value is not None:
            self._timer_expiry = float(expiry_value)
        else:
            # Migrate from old minutes format - defer to async_setup
            old_minutes = config_data.get(CONF_TIMER_MINUTES, DEFAULT_TIMER_MINUTES)
            if old_minutes > 0:
                self._timer_expiry = time.time() + (old_minutes * 60)
                self._needs_timer_migration = True

        # Restore persisted mode state
        last_change_str = config_data.get(CONF_LAST_MODE_CHANGE_TIME)
        if last_change_str:
            try:
                self._last_mode_change_time = datetime.fromisoformat(last_change_str)
            except ValueError:
                _LOGGER.warning(
                    "Invalid last mode change time format: %s", last_change_str
                )
                self._last_mode_change_time = None

        self._last_set_hvac_mode = config_data.get(CONF_LAST_SET_HVAC_MODE)

        self._timer_task: asyncio.Task | None = None
        self._timer_listeners: list[Callable[[], None]] = []
        self._light_control_enabled: bool = config_data.get(
            CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL
        )

    def _create_tracked_task(self, coro) -> None:
        """Add a coroutine to the task queue for efficient processing.

        Args:
            coro: A coroutine object to queue for background execution
        """
        # Try to add to queue without blocking, drop if full to prevent memory issues
        try:
            self._task_queue.put_nowait(coro)
        except asyncio.QueueFull:
            _LOGGER.warning("Task queue full, dropping task to prevent memory leak")

    async def _create_tracked_task_throttled(self, coro):
        """Create a tracked task with throttling to prevent resource exhaustion."""
        async with self._task_semaphore:
            return await coro

    def _create_timer_task(self, coro) -> asyncio.Task:
        """Create a timer task that is managed separately from pending tasks."""
        return self.hass.loop.create_task(coro)

    @property
    def config(self) -> dict[str, Any]:
        """Get merged configuration (data + options)."""
        # Check if cache needs to be rebuilt
        if self._cached_config is None:
            # Build config outside of lock to avoid holding lock during dict operations
            config_data = {**self.entry.data, **self.entry.options}
            # Use lock only for the final assignment to ensure atomicity
            self._cached_config = config_data
        return self._cached_config

    async def _process_task_queue(self) -> None:
        """Process tasks from the queue efficiently."""
        while True:
            try:
                coro = await self._task_queue.get()
                async with self._task_semaphore:
                    await coro
            except Exception as e:
                _LOGGER.error("Task processing error: %s", e)

    @property
    def _min_run_time_minutes(self) -> int:
        """Get cached minimum run time in minutes."""
        if not hasattr(self, "_cached_min_run_time"):
            self._cached_min_run_time = self.config.get(
                CONF_MIN_RUN_TIME, DEFAULT_MIN_RUN_TIME
            )
        return self._cached_min_run_time

    def _invalidate_config_cache(self) -> None:
        """Invalidate the config cache when options are updated."""
        self._cached_config = None
        # Clear cached derived values
        if hasattr(self, "_cached_min_run_time"):
            delattr(self, "_cached_min_run_time")

    def _validate_entity_id(self, entity_id: str) -> bool:
        """Validate entity exists and is accessible."""
        if not entity_id or "." not in entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None

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

    def get_room_name(self) -> str:
        """Get the room name from the climate entity ID for use in entity IDs."""
        return self.climate_entity.split(".")[-1]

    @property
    def timer_minutes(self) -> int:
        """Return remaining timer minutes calculated from expiry timestamp.

        Note: This is a best-effort read without locking for performance.
        Slight inaccuracies are acceptable for UI display.
        """
        # Take a snapshot to avoid race conditions
        expiry = self._timer_expiry
        if expiry is None:
            return 0
        remaining_seconds = max(0, expiry - time.time())
        return int(remaining_seconds // 60)

    async def async_get_timer_minutes(self) -> int:
        """Get remaining timer minutes (thread-safe with proper locking)."""
        # Lock protects access to _timer_expiry to prevent race conditions
        # where timer expiry could be modified by async_set_timer while being read
        async with self._state_lock:
            if self._timer_expiry is None:
                return 0
            remaining_seconds = max(0, self._timer_expiry - time.time())
            return int(remaining_seconds // 60)

    def add_timer_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback to be notified on timer updates."""
        self._timer_listeners.append(callback)

        def _remove() -> None:
            if callback in self._timer_listeners:
                self._timer_listeners.remove(callback)

        return _remove

    def _notify_timer_listeners(self) -> None:
        """Notify timer listeners of an update."""
        # Create a copy of the list to avoid issues if listeners modify the list
        for listener in list(self._timer_listeners):
            try:
                listener()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Error notifying timer listener: %s", exc)

    def _can_change_mode(self) -> bool:
        """Check if minimum run time has elapsed since last mode change.

        Note: This is called from within _threshold_lock, so the race condition
        with _last_mode_change_time (which is only modified in _async_set_climate)
        is acceptable since threshold operations are already serialized.
        """
        # Snapshot the value to avoid TOCTTOU
        last_change = self._last_mode_change_time
        if last_change is None:
            return True

        elapsed = datetime.now() - last_change
        return elapsed >= timedelta(minutes=self._min_run_time_minutes)

    def _log_state_change(self, change_type: str, details: StateChangeDetails) -> None:
        """Log complex state changes for debugging."""

        async def _do_log():
            # Lock protects the state change log deque to prevent concurrent
            # modifications that could cause data corruption or inconsistent state
            async with self._service_lock:
                entry = {
                    "timestamp": time.time(),
                    "type": change_type,
                    "entity": self.climate_entity,
                    "enabled": self._enabled,
                    "details": details,
                }

                self._state_change_log.append(entry)

                # Enhanced logging based on change type (only when info/debug enabled)
                if change_type == "temperature_threshold" and _LOGGER.isEnabledFor(
                    logging.INFO
                ):
                    temp = details.get("temperature")
                    threshold = details.get("threshold")
                    action = details.get("action")
                    _LOGGER.info(
                        "🌡️ Temperature threshold triggered for %s: %.1f°C %s %.1f°C -> %s",
                        self.climate_entity,
                        temp,
                        ">" if action == "high" else "<",
                        threshold,
                        details.get("mode", "unknown"),
                    )
                elif change_type == "humidity_threshold" and _LOGGER.isEnabledFor(
                    logging.INFO
                ):
                    humidity = details.get("humidity")
                    threshold = details.get("threshold")
                    action = details.get("action")
                    _LOGGER.info(
                        "💧 Humidity threshold triggered for %s: %.1f%% %s %.1f%% -> %s",
                        self.climate_entity,
                        humidity,
                        ">" if action == "high" else "<",
                        threshold,
                        details.get("action_taken", "unknown"),
                    )
                elif change_type == "manual_override" and _LOGGER.isEnabledFor(
                    logging.WARNING
                ):
                    _LOGGER.warning(
                        "👤 Manual override detected for %s: mode changed from %s to %s",
                        self.climate_entity,
                        details.get("old_mode"),
                        details.get("new_mode"),
                    )
                elif change_type == "climate_command" and _LOGGER.isEnabledFor(
                    logging.INFO
                ):
                    _LOGGER.info(
                        "🏠 Climate command sent to %s: mode=%s, fan=%s, swing=%s, temp=%s",
                        self.climate_entity,
                        details.get("mode"),
                        details.get("fan_mode"),
                        details.get("swing_mode"),
                        details.get("target_temp"),
                    )
                elif change_type == "timer_operation":
                    _LOGGER.info(
                        "⏰ Timer %s for %s: %s",
                        details.get("operation"),
                        self.climate_entity,
                        details.get("details", ""),
                    )

        # Schedule the logging task - don't await to avoid blocking
        if self.hass:
            self._create_tracked_task(_do_log())

    async def _check_circuit_breaker(self, service_key: str) -> bool:
        """Check if circuit breaker is tripped for a service call."""
        # Lock protects circuit breaker state (_service_call_failures, _service_call_last_failure)
        # to prevent race conditions when multiple service calls are happening concurrently
        async with self._service_lock:
            current_time = time.time()

            # Reset if timeout expired
            if service_key in self._service_call_last_failure:
                time_since_failure = (
                    current_time - self._service_call_last_failure[service_key]
                )
                if time_since_failure > self._circuit_breaker_timeout:
                    self._service_call_failures[service_key] = 0
                    del self._service_call_last_failure[service_key]
                    return False

            failure_count = self._service_call_failures.get(service_key, 0)
            if failure_count >= self._circuit_breaker_threshold:
                _LOGGER.warning(
                    "🔌 Circuit breaker tripped for %s on %s (failures: %d/%d)",
                    service_key,
                    self.climate_entity,
                    failure_count,
                    self._circuit_breaker_threshold,
                )
                return True
            return False

    def _record_service_call_result(self, service_key: str, success: bool) -> None:
        """Record the result of a service call for circuit breaker logic."""

        async def _record():
            # Lock protects circuit breaker state updates to ensure atomic operations
            # and prevent race conditions when multiple service calls complete simultaneously
            async with self._service_lock:
                if success:
                    # Reset failure count on success
                    if service_key in self._service_call_failures:
                        del self._service_call_failures[service_key]
                    if service_key in self._service_call_last_failure:
                        del self._service_call_last_failure[service_key]
                else:
                    # Increment failure count
                    self._service_call_failures[service_key] = (
                        self._service_call_failures.get(service_key, 0) + 1
                    )
                    self._service_call_last_failure[service_key] = time.time()

        # Schedule the recording task
        if self.hass:
            self._create_tracked_task(_record())

    def _validate_climate_capability(
        self, capability_type: str, value: str | None
    ) -> bool:
        """Validate that the climate entity supports a given capability value."""
        if not value:
            return True  # None values are always valid

        current_time = time.time()
        cache_key = f"{self.climate_entity}_{capability_type}"

        # Check cache first (valid for configured duration)
        if (
            cache_key in self._capability_validation_time
            and current_time - self._capability_validation_time[cache_key]
            < CAPABILITY_CACHE_DURATION_SECONDS
        ):
            supported_values = self._validated_capabilities.get(cache_key, set())
            return value in supported_values

        # Get current climate state and check capabilities
        climate_state = self.hass.states.get(self.climate_entity)
        if not climate_state:
            _LOGGER.warning(
                "Cannot validate %s capability: climate entity %s not found",
                capability_type,
                self.climate_entity,
            )
            return False

        supported_values = set()
        if capability_type == "hvac_modes":
            supported_values = set(climate_state.attributes.get("hvac_modes", []))
        elif capability_type == "fan_modes":
            supported_values = set(climate_state.attributes.get("fan_modes", []))
        elif capability_type == "swing_modes":
            supported_values = set(climate_state.attributes.get("swing_modes", []))
        elif capability_type == "swing_horizontal_modes":
            supported_values = set(
                climate_state.attributes.get("swing_horizontal_modes", [])
            )

        # Cache the validation result
        self._validated_capabilities[cache_key] = supported_values
        self._capability_validation_time[cache_key] = current_time

        if value not in supported_values:
            _LOGGER.warning(
                "❌ Climate entity %s does not support %s='%s'. Supported: %s",
                self.climate_entity,
                capability_type,
                value,
                list(supported_values),
            )
            return False

        return True

    async def _async_safe_service_call(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> bool:
        """Make a service call with retry logic and circuit breaker protection."""
        service_key = f"{domain}.{service}"

        # Check circuit breaker
        if await self._check_circuit_breaker(service_key):
            return False

        # Attempt service call with exponential backoff retry
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                await self.hass.services.async_call(
                    domain, service, data, blocking=True
                )
                # Success - reset circuit breaker state
                self._record_service_call_result(service_key, True)
                if attempt > 0:
                    _LOGGER.info(
                        "Service call succeeded after %d retries: %s.%s",
                        attempt,
                        domain,
                        service,
                    )
                return True
            except Exception as exc:
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    # Calculate exponential backoff delay
                    delay = BASE_RETRY_DELAY_SECONDS * (2**attempt)
                    _LOGGER.warning(
                        "Service call failed (attempt %d/%d), retrying in %d seconds: %s.%s with data %s: %s",
                        attempt + 1,
                        MAX_RETRY_ATTEMPTS,
                        delay,
                        domain,
                        service,
                        data,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    # All retries exhausted - record failure for circuit breaker
                    _LOGGER.warning(
                        "Service call failed after %d attempts: %s.%s with data %s: %s",
                        MAX_RETRY_ATTEMPTS,
                        domain,
                        service,
                        data,
                        exc,
                    )
                    self._record_service_call_result(service_key, False)
                    return False

        # This should never be reached, but just in case
        return False

    async def _async_validate_configuration(self) -> None:
        """Validate configuration and log warnings for potential issues."""
        config = self.config
        issues_found = []

        # 1. Check temperature thresholds
        min_temp = config.get(CONF_MIN_TEMP)
        max_temp = config.get(CONF_MAX_TEMP)
        if min_temp is not None and max_temp is not None and min_temp >= max_temp:
            issues_found.append(
                f"⚠️  Temperature thresholds invalid: min_temp ({min_temp}°C) >= max_temp ({max_temp}°C). "
                "This will prevent temperature-based automation from working."
            )

        # 2. Check humidity thresholds
        min_humidity = config.get(CONF_MIN_HUMIDITY)
        max_humidity = config.get(CONF_MAX_HUMIDITY)
        if (
            min_humidity is not None
            and max_humidity is not None
            and min_humidity >= max_humidity
        ):
            issues_found.append(
                f"⚠️  Humidity thresholds invalid: min_humidity ({min_humidity}%) >= max_humidity ({max_humidity}%). "
                "This will prevent humidity-based automation from working."
            )

        # 3. Check entity existence
        entities_to_check = [
            (CONF_CLIMATE_ENTITY, self.climate_entity, "Climate entity"),
            (CONF_TEMPERATURE_SENSOR, self.temperature_sensor, "Temperature sensor"),
        ]

        if self.humidity_sensor:
            entities_to_check.append(
                (CONF_HUMIDITY_SENSOR, self.humidity_sensor, "Humidity sensor")
            )

        if self.humidifier_entity:
            entities_to_check.append(
                (CONF_HUMIDIFIER_ENTITY, self.humidifier_entity, "Humidifier entity")
            )

        if self.light_entity:
            entities_to_check.append(
                (CONF_LIGHT_ENTITY, self.light_entity, "Light entity")
            )

        for conf_key, entity_id, description in entities_to_check:
            if not self.hass.states.get(entity_id):
                issues_found.append(
                    f"⚠️  {description} '{entity_id}' does not exist or is not available. "
                    "This may cause automation failures."
                )

        # 4. Validate climate entity modes
        climate_state = self.hass.states.get(self.climate_entity)
        if climate_state:
            supported_hvac_modes = climate_state.attributes.get("hvac_modes", [])
            configured_modes = [
                (
                    CONF_MODE_LOW_TEMP,
                    config.get(CONF_MODE_LOW_TEMP),
                    "Low temperature mode",
                ),
                (
                    CONF_MODE_HIGH_TEMP,
                    config.get(CONF_MODE_HIGH_TEMP),
                    "High temperature mode",
                ),
                (
                    CONF_MODE_HIGH_HUMIDITY,
                    config.get(CONF_MODE_HIGH_HUMIDITY),
                    "High humidity mode",
                ),
            ]

            for conf_key, mode, description in configured_modes:
                if mode and mode not in supported_hvac_modes:
                    issues_found.append(
                        f"⚠️  {description} '{mode}' is not supported by climate entity '{self.climate_entity}'. "
                        f"Supported modes: {supported_hvac_modes}"
                    )

            # Validate fan modes if configured
            supported_fan_modes = climate_state.attributes.get("fan_modes", [])
            configured_fan_modes = [
                (
                    "fan_low_temp",
                    config.get("fan_low_temp"),
                    "Low temperature fan mode",
                ),
                (
                    "fan_high_temp",
                    config.get("fan_high_temp"),
                    "High temperature fan mode",
                ),
                (
                    "fan_high_humidity",
                    config.get("fan_high_humidity"),
                    "High humidity fan mode",
                ),
            ]

            for conf_key, fan_mode, description in configured_fan_modes:
                if fan_mode and fan_mode not in supported_fan_modes:
                    issues_found.append(
                        f"⚠️  {description} '{fan_mode}' is not supported by climate entity '{self.climate_entity}'. "
                        f"Supported fan modes: {supported_fan_modes}"
                    )

            # Validate swing modes if configured
            supported_swing_modes = climate_state.attributes.get("swing_modes", [])
            configured_swing_modes = [
                (
                    "swing_low_temp",
                    config.get("swing_low_temp"),
                    "Low temperature swing mode",
                ),
                (
                    "swing_high_temp",
                    config.get("swing_high_temp"),
                    "High temperature swing mode",
                ),
                (
                    "swing_high_humidity",
                    config.get("swing_high_humidity"),
                    "High humidity swing mode",
                ),
            ]

            for conf_key, swing_mode, description in configured_swing_modes:
                if swing_mode and swing_mode not in supported_swing_modes:
                    issues_found.append(
                        f"⚠️  {description} '{swing_mode}' is not supported by climate entity '{self.climate_entity}'. "
                        f"Supported swing modes: {supported_swing_modes}"
                    )

        # Log all issues found
        if issues_found:
            _LOGGER.warning(
                "Configuration validation found %d issue(s) for Climate React (%s):",
                len(issues_found),
                self.climate_entity,
            )
            for issue in issues_found:
                _LOGGER.warning("  %s", issue)
        else:
            _LOGGER.info(
                "✅ Configuration validation passed for Climate React (%s)",
                self.climate_entity,
            )

    async def async_setup(self) -> None:
        """Set up the controller."""
        # Validate configuration first
        await self._async_validate_configuration()

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

        # Start the task processor for efficient background processing
        self._task_processor_task = self.hass.loop.create_task(
            self._process_task_queue()
        )

        # Initial state evaluation
        await self._async_evaluate_state()
        await self._async_start_timer_if_needed()

        # Handle timer migration if needed
        if hasattr(self, "_needs_timer_migration") and self._needs_timer_migration:
            try:
                await self._async_migrate_timer_format()
            except Exception as exc:
                _LOGGER.error("Timer migration failed, clearing flag: %s", exc)
                self._needs_timer_migration = False

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

        # Cancel timer task with proper cleanup
        # Lock protects timer task cancellation to prevent race conditions
        # during shutdown when timer operations might still be active
        async with self._state_lock:
            if self._timer_task:
                self._timer_task.cancel()
                try:
                    await self._timer_task
                except asyncio.CancelledError:
                    pass
                self._timer_task = None

        # Cancel task processor
        if self._task_processor_task and not self._task_processor_task.done():
            self._task_processor_task.cancel()
            try:
                await self._task_processor_task
            except asyncio.CancelledError:
                pass
            self._task_processor_task = None

        # Cancel debounce timers
        if self._debounce_temp_timer:
            self._debounce_temp_timer.cancel()
            self._debounce_temp_timer = None
        if self._debounce_humidity_timer:
            self._debounce_humidity_timer.cancel()
            self._debounce_humidity_timer = None

        # Clear timer listeners to prevent memory leaks
        self._timer_listeners.clear()

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
        if self.timer_minutes > 0 and self._is_climate_off():
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
        # Lock protects config updates to ensure atomic operations and prevent
        # race conditions when multiple config changes happen simultaneously
        async with self._config_lock:
            self._light_control_enabled = enabled
            new_options = {**self.entry.options}
            new_options[CONF_ENABLE_LIGHT_CONTROL] = enabled
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()
        _LOGGER.info(
            "Light control %s for %s",
            "enabled" if enabled else "disabled",
            self.climate_entity,
        )

        # Re-apply behavior to enforce desired light state immediately
        await self._async_apply_light_behavior(enabled=self._enabled)

    async def async_update_thresholds(self, data: dict[str, Any]) -> None:
        """Update thresholds dynamically."""
        # Lock protects threshold config updates to ensure atomic operations
        # and prevent race conditions during concurrent threshold modifications
        async with self._config_lock:
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
            self._invalidate_config_cache()

        # Re-evaluate state with new thresholds
        await self._async_evaluate_state()

        _LOGGER.info("Thresholds updated for %s: %s", self.climate_entity, data)

    async def async_update_option(self, key: str, value: Any) -> None:
        """Update a single config option without triggering full reload."""
        # Lock protects config option updates to ensure atomic operations
        # and prevent race conditions when multiple options are updated concurrently
        async with self._config_lock:
            new_options = {**self.entry.options}
            new_options[key] = value
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()
        _LOGGER.debug("Option updated for %s: %s = %s", self.climate_entity, key, value)

    @callback
    async def _async_climate_available(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle climate entity becoming available."""
        new_state: State | None = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        await self._async_sync_thresholds_to_climate(new_state)
        await self._async_evaluate_state()

    async def _async_sync_thresholds_to_climate(self, climate_state: State) -> None:
        """Sync configured thresholds to climate entity limits."""
        # Lock protects climate limit synchronization to ensure atomic updates
        # and prevent race conditions when climate availability changes occur
        async with self._config_lock:
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
            if (
                self._climate_min_temp is not None
                and configured_min_temp < self._climate_min_temp
            ):
                _LOGGER.warning(
                    "Configured min_temp %.1f°C is below climate entity minimum %.1f°C; clamping",
                    configured_min_temp,
                    self._climate_min_temp,
                )
                new_options[CONF_MIN_TEMP] = self._climate_min_temp
                needs_update = True

            # Clamp max_temp
            configured_max_temp = config.get(CONF_MAX_TEMP, 26.0)
            if (
                self._climate_max_temp is not None
                and configured_max_temp > self._climate_max_temp
            ):
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
                self.hass.config_entries.async_update_entry(
                    self.entry, options=new_options
                )
                self._invalidate_config_cache()

    @callback
    async def _async_temperature_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
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

            # Always keep the last reading for UI/diagnostics (thread-safe)
            # Lock protects _last_temp to prevent race conditions when multiple
            # temperature updates occur simultaneously from different event sources
            async with self._state_lock:
                self._last_temp = temperature
            _LOGGER.debug(
                "Temperature changed to %.1f°C for %s", temperature, self.climate_entity
            )

            # Debounce threshold evaluation to prevent excessive processing
            if self._enabled:
                await self._debounce_temperature_threshold(temperature)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid temperature state: %s (%s)", new_state.state, err)

    async def _debounce_temperature_threshold(self, temperature: float) -> None:
        """Debounce temperature threshold evaluation to prevent excessive processing."""
        self._pending_temperature = temperature

        # Cancel existing timer
        if self._debounce_temp_timer:
            self._debounce_temp_timer.cancel()

        # Schedule new evaluation after debounce delay
        self._debounce_temp_timer = self.hass.loop.call_later(
            1.0,  # 1 second debounce
            lambda: asyncio.create_task(self._process_pending_temperature()),
        )

    async def _process_pending_temperature(self) -> None:
        """Process pending temperature threshold evaluation."""
        if self._pending_temperature is not None:
            temperature = self._pending_temperature
            self._pending_temperature = None
            await self._async_handle_temperature_threshold(temperature)

    async def _debounce_humidity_threshold(self, humidity: float) -> None:
        """Debounce humidity threshold evaluation to prevent excessive processing."""
        self._pending_humidity = humidity

        # Cancel existing timer
        if self._debounce_humidity_timer:
            self._debounce_humidity_timer.cancel()

        # Schedule new evaluation after debounce delay
        self._debounce_humidity_timer = self.hass.loop.call_later(
            1.0,  # 1 second debounce
            lambda: asyncio.create_task(self._process_pending_humidity()),
        )

    async def _process_pending_humidity(self) -> None:
        """Process pending humidity threshold evaluation."""
        if self._pending_humidity is not None:
            humidity = self._pending_humidity
            self._pending_humidity = None
            await self._async_handle_humidity_threshold(humidity)

    @callback
    async def _async_climate_state_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Detect manual mode changes outside of automation."""
        new_state: State | None = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        # Capture enabled state and timer expiry atomically
        # Lock protects reading timer state to get consistent snapshot
        # and prevent race conditions when timer is being modified concurrently
        async with self._state_lock:
            timer_active = self._timer_expiry is not None
            enabled = self._enabled

        if not enabled and timer_active and self._is_climate_off_state(new_state):
            await self.async_set_timer(0)
            return

        if not enabled:
            return

        current_mode = new_state.state

        # If we set a mode and it changed to something else, it's a manual override
        if (
            self._last_set_hvac_mode is not None
            and current_mode != self._last_set_hvac_mode
        ):
            self._log_state_change(
                "manual_override",
                {
                    "old_mode": self._last_set_hvac_mode,
                    "new_mode": current_mode,
                    "action": "disable_automation",
                },
            )

            self._enabled = False
            self._last_set_hvac_mode = None
            # Persist cleared mode state for HA restart recovery
            await self._async_persist_mode_state()
            await self._async_apply_light_behavior(enabled=False)

    @callback
    async def _async_humidity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
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
            # Always keep the last reading for UI/diagnostics (thread-safe)
            # Lock protects _last_humidity to prevent race conditions when multiple
            # humidity updates occur simultaneously from different event sources
            async with self._state_lock:
                self._last_humidity = humidity
            _LOGGER.debug(
                "Humidity changed to %.1f%% for %s", humidity, self.climate_entity
            )

            # Debounce threshold evaluation to prevent excessive processing
            if self._enabled:
                await self._debounce_humidity_threshold(humidity)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid humidity state: %s (%s)", new_state.state, err)

    async def _async_evaluate_state(self) -> None:
        """Evaluate current sensor states."""
        # Collect data under lock to get consistent snapshot of sensor states
        # and enabled flag, preventing race conditions during evaluation
        async with self._state_lock:
            temp_state = self.hass.states.get(self.temperature_sensor)
            humidity_state = self.humidity_sensor and self.hass.states.get(
                self.humidity_sensor
            )
            enabled = self._enabled

        # Process temperature (outside lock)
        if temp_state and temp_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                use_external_temp = self.entry.data.get(
                    CONF_USE_EXTERNAL_TEMP_SENSOR, False
                )
                if (
                    not use_external_temp
                    and temp_state.entity_id == self.climate_entity
                ):
                    temperature = temp_state.attributes.get("current_temperature")
                    if temperature is not None:
                        temperature = float(temperature)
                else:
                    temperature = float(temp_state.state)

                # Update state under lock
                # Lock protects _last_temp update to ensure thread-safe access
                # and prevent data corruption from concurrent temperature updates
                async with self._state_lock:
                    self._last_temp = temperature

                # Schedule task outside lock
                if enabled:
                    self._create_tracked_task(
                        self._async_handle_temperature_threshold(temperature)
                    )
            except (ValueError, TypeError):
                pass

        # Process humidity (outside lock)
        if humidity_state and humidity_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            try:
                use_external_humidity = self.entry.data.get(
                    CONF_USE_EXTERNAL_HUMIDITY_SENSOR, False
                )
                if (
                    not use_external_humidity
                    and humidity_state.entity_id == self.climate_entity
                ):
                    humidity = humidity_state.attributes.get("current_humidity")
                    if humidity is not None:
                        humidity = float(humidity)
                else:
                    humidity = float(humidity_state.state)

                # Update state under lock
                # Lock protects _last_humidity update to ensure thread-safe access
                # and prevent data corruption from concurrent humidity updates
                async with self._state_lock:
                    self._last_humidity = humidity

                # Schedule task outside lock
                if enabled:
                    self._create_tracked_task(
                        self._async_handle_humidity_threshold(humidity)
                    )
            except (ValueError, TypeError):
                pass

    async def _async_handle_temperature_threshold(self, temperature: float) -> None:
        """Handle temperature threshold logic."""
        # Lock protects threshold evaluation to ensure consistent state
        # and prevent race conditions when mode change timing is checked
        async with self._state_lock:
            if not self._can_change_mode():
                self._log_state_change(
                    "temperature_threshold_blocked",
                    {
                        "temperature": temperature,
                        "reason": "minimum_run_time_not_elapsed",
                        "last_change": str(self._last_mode_change_time),
                    },
                )
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Temperature threshold triggered but minimum run time not elapsed for %s",
                        self.climate_entity,
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

            self._log_state_change(
                "temperature_threshold",
                {
                    "temperature": temperature,
                    "threshold": min_temp,
                    "action": "low",
                    "mode": mode,
                    "fan_mode": fan_mode,
                    "swing_mode": swing_mode,
                    "target_temp": target_temp,
                },
            )

            logbook.async_log_entry(
                self.hass,
                "Low Temperature",
                message=f"Temperature {temperature:.1f}°C below minimum {min_temp:.1f}°C - switching to {mode}",
                entity_id=self._get_switch_entity_id(),
                domain=DOMAIN,
            )

            await self._async_set_climate(
                mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp
            )

        elif temperature > max_temp:
            # High temperature - trigger cooling
            mode = config[CONF_MODE_HIGH_TEMP]
            fan_mode = config.get(CONF_FAN_HIGH_TEMP)
            swing_mode = config.get(CONF_SWING_HIGH_TEMP)
            swing_horizontal_mode = config.get(CONF_SWING_HORIZONTAL_HIGH_TEMP)
            target_temp = config.get(CONF_TEMP_HIGH_TEMP)

            self._log_state_change(
                "temperature_threshold",
                {
                    "temperature": temperature,
                    "threshold": max_temp,
                    "action": "high",
                    "mode": mode,
                    "fan_mode": fan_mode,
                    "swing_mode": swing_mode,
                    "target_temp": target_temp,
                },
            )

            logbook.async_log_entry(
                self.hass,
                "High Temperature",
                message=f"Temperature {temperature:.1f}°C above maximum {max_temp:.1f}°C - switching to {mode}",
                entity_id=self._get_switch_entity_id(),
                domain=DOMAIN,
            )

            await self._async_set_climate(
                mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp
            )
        else:
            _LOGGER.debug(
                "Temperature %.1f°C within range [%.1f, %.1f] for %s",
                temperature,
                min_temp,
                max_temp,
                self.climate_entity,
            )
            # Close the threshold lock

    async def _async_handle_humidity_threshold(self, humidity: float) -> None:
        """Handle humidity threshold logic."""
        # Lock protects threshold evaluation to ensure consistent state
        # and prevent race conditions when mode change timing is checked
        async with self._state_lock:
            if not self._can_change_mode():
                self._log_state_change(
                    "humidity_threshold_blocked",
                    {
                        "humidity": humidity,
                        "reason": "minimum_run_time_not_elapsed",
                        "last_change": str(self._last_mode_change_time),
                    },
                )
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Humidity threshold triggered but minimum run time not elapsed for %s",
                        self.climate_entity,
                    )
                return

        config = self.config
        min_humidity = config.get(CONF_MIN_HUMIDITY)
        max_humidity = config.get(CONF_MAX_HUMIDITY)

        # Check if humidity is too low (turn on humidifier)
        if min_humidity and humidity < min_humidity:
            if self.humidifier_entity:
                self._log_state_change(
                    "humidity_threshold",
                    {
                        "humidity": humidity,
                        "threshold": min_humidity,
                        "action": "low",
                        "action_taken": "turn_on_humidifier",
                        "humidifier_entity": self.humidifier_entity,
                    },
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
                success = await self._async_safe_service_call(
                    domain, service, {"entity_id": self.humidifier_entity}
                )
                if not success:
                    _LOGGER.warning(
                        "Failed to turn on humidifier %s", self.humidifier_entity
                    )
            else:
                _LOGGER.debug(
                    "Humidity %.1f%% < %.1f%% (min) but no humidifier configured",
                    humidity,
                    min_humidity,
                )
        # Check if humidity is too high (turn off humidifier and/or trigger dehumidify mode)
        elif max_humidity and humidity > max_humidity:
            # Turn off humidifier if it's on
            if self.humidifier_entity:
                self._log_state_change(
                    "humidity_threshold",
                    {
                        "humidity": humidity,
                        "threshold": max_humidity,
                        "action": "high",
                        "action_taken": "turn_off_humidifier",
                        "humidifier_entity": self.humidifier_entity,
                    },
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
                success = await self._async_safe_service_call(
                    domain, service, {"entity_id": self.humidifier_entity}
                )
                if not success:
                    _LOGGER.warning(
                        "Failed to turn off humidifier %s", self.humidifier_entity
                    )

            # Trigger dehumidify mode on climate entity
            mode = config.get(CONF_MODE_HIGH_HUMIDITY)
            fan_mode = config.get(CONF_FAN_HIGH_HUMIDITY)
            swing_mode = config.get(CONF_SWING_HIGH_HUMIDITY)
            swing_horizontal_mode = config.get(CONF_SWING_HORIZONTAL_HIGH_HUMIDITY)
            target_temp = config.get(CONF_TEMP_HIGH_HUMIDITY)

            self._log_state_change(
                "humidity_threshold",
                {
                    "humidity": humidity,
                    "threshold": max_humidity,
                    "action": "high",
                    "action_taken": "set_climate_mode",
                    "mode": mode,
                    "fan_mode": fan_mode,
                    "swing_mode": swing_mode,
                    "target_temp": target_temp,
                },
            )

            await self._async_set_climate(
                mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp
            )
        else:
            # Humidity is within acceptable range - turn off humidifier
            if self.humidifier_entity:
                _LOGGER.debug(
                    "Humidity %.1f%% within range [%.1f, %.1f] - turning off humidifier %s",
                    humidity,
                    min_humidity or 0,
                    max_humidity or 100,
                    self.humidifier_entity,
                )
                domain = self.humidifier_entity.split(".")[0]
                service = "turn_off"
                success = await self._async_safe_service_call(
                    domain, service, {"entity_id": self.humidifier_entity}
                )
                if not success:
                    _LOGGER.warning(
                        "Failed to turn off humidifier %s", self.humidifier_entity
                    )
            _LOGGER.debug(
                "Humidity %.1f%% within acceptable range for %s",
                humidity,
                self.climate_entity,
            )
            # Close the threshold lock

    async def _async_set_climate(
        self,
        hvac_mode: str | None,
        fan_mode: str | None,
        swing_mode: str | None,
        swing_horizontal_mode: str | None,
        target_temp: float | None = None,
    ) -> None:
        # Validate and prepare climate command parameters
        command = await self._validate_and_prepare_climate_command(
            hvac_mode, fan_mode, swing_mode, swing_horizontal_mode
        )
        if not command:
            return

        hvac_mode = command.get("hvac_mode")
        fan_mode = command.get("fan_mode")
        swing_mode = command.get("swing_mode")
        swing_horizontal_mode = command.get("swing_horizontal_mode")

        climate_state = self.hass.states.get(self.climate_entity)
        config = self.config

        # Skip ancillary calls (fan/swing/temperature) when HVAC is off unless we are turning it on now.
        current_state = climate_state.state if climate_state else None
        turning_off = hvac_mode == MODE_OFF
        staying_off = hvac_mode is None and current_state == MODE_OFF
        allow_auxiliary_calls = not (turning_off or staying_off)

        # Get configured delay in milliseconds, convert to seconds
        delay_seconds = (
            config.get(CONF_DELAY_BETWEEN_COMMANDS, DEFAULT_DELAY_BETWEEN_COMMANDS)
            / 1000.0
        )

        # Log the climate command
        self._log_state_change(
            "climate_command",
            {
                "mode": hvac_mode,
                "fan_mode": fan_mode,
                "swing_mode": swing_mode,
                "swing_horizontal_mode": swing_horizontal_mode,
                "target_temp": target_temp,
                "delay_seconds": delay_seconds,
            },
        )

        # Handle light control
        await self._handle_light_control(True, delay_seconds)

        # Set HVAC mode
        climate_state = await self._set_hvac_mode(
            hvac_mode, climate_state, delay_seconds
        )
        if climate_state is None:  # Command failed
            return

        # Set auxiliary parameters
        await self._set_auxiliary_parameters(
            climate_state,
            allow_auxiliary_calls,
            target_temp,
            fan_mode,
            swing_mode,
            swing_horizontal_mode,
            delay_seconds,
        )

        # Restore light control
        await self._handle_light_control(False, delay_seconds)

    async def _validate_and_prepare_climate_command(
        self,
        hvac_mode: str | None,
        fan_mode: str | None,
        swing_mode: str | None,
        swing_horizontal_mode: str | None,
    ) -> ClimateCommand | None:
        """Validate climate entity capabilities and prepare command parameters."""
        # Validate climate entity capabilities before attempting commands
        if hvac_mode and not self._validate_climate_capability("hvac_modes", hvac_mode):
            _LOGGER.warning(
                "Skipping climate command due to invalid HVAC mode: %s", hvac_mode
            )
            return None
        if fan_mode and not self._validate_climate_capability("fan_modes", fan_mode):
            _LOGGER.warning(
                "Skipping fan mode setting due to invalid fan mode: %s", fan_mode
            )
            fan_mode = None
        if swing_mode and not self._validate_climate_capability(
            "swing_modes", swing_mode
        ):
            _LOGGER.warning(
                "Skipping swing mode setting due to invalid swing mode: %s", swing_mode
            )
            swing_mode = None
        if swing_horizontal_mode and not self._validate_climate_capability(
            "swing_horizontal_modes", swing_horizontal_mode
        ):
            _LOGGER.warning(
                "Skipping horizontal swing mode setting due to invalid mode: %s",
                swing_horizontal_mode,
            )
            swing_horizontal_mode = None

        climate_state = self.hass.states.get(self.climate_entity)

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

        return {
            "hvac_mode": hvac_mode,
            "fan_mode": fan_mode,
            "swing_mode": swing_mode,
            "swing_horizontal_mode": swing_horizontal_mode,
        }

    async def _handle_light_control(self, turn_off: bool, delay_seconds: float) -> None:
        """Handle light control toggling for climate commands."""
        light_entity = self.light_entity if self._light_control_enabled else None
        light_behavior = self.light_behavior
        toggle_light = light_entity and light_behavior != LIGHT_BEHAVIOR_UNCHANGED

        if toggle_light:
            assert light_entity is not None
            option = "off" if turn_off else "on"
            await self._async_set_light(light_entity, option)
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

    async def _set_hvac_mode(
        self,
        hvac_mode: str | None,
        climate_state: State | None,
        delay_seconds: float,
    ) -> State | None:
        """Set HVAC mode with proper turn_on/off/set_hvac_mode logic."""
        if not hvac_mode or hvac_mode == (
            climate_state.state if climate_state else None
        ):
            return climate_state

        if hvac_mode == MODE_OFF:
            # Turning off - use turn_off service
            if not await self._async_safe_service_call(
                "climate",
                "turn_off",
                {"entity_id": self.climate_entity},
            ):
                _LOGGER.warning(
                    "Failed to turn off climate entity %s", self.climate_entity
                )
                return None
            # Verify it's actually off, fall back to set_hvac_mode if not
            climate_state = self.hass.states.get(self.climate_entity)
            if climate_state and climate_state.state != MODE_OFF:
                _LOGGER.debug(
                    "turn_off didn't set mode to off for %s, using set_hvac_mode fallback",
                    self.climate_entity,
                )
                if not await self._async_safe_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": self.climate_entity, "hvac_mode": MODE_OFF},
                ):
                    _LOGGER.warning(
                        "Failed to set HVAC mode to off for %s", self.climate_entity
                    )
                    return None
        elif climate_state and climate_state.state == MODE_OFF:
            # Currently off, turning on - use turn_on service
            if not await self._async_safe_service_call(
                "climate",
                "turn_on",
                {"entity_id": self.climate_entity},
            ):
                _LOGGER.warning(
                    "Failed to turn on climate entity %s", self.climate_entity
                )
                return None
            # Verify it's in the correct mode, fall back to set_hvac_mode if not
            climate_state = self.hass.states.get(self.climate_entity)
            if climate_state and (
                climate_state.state == MODE_OFF or climate_state.state != hvac_mode
            ):
                _LOGGER.debug(
                    "turn_on didn't set %s to required mode %s (current: %s), using set_hvac_mode fallback",
                    self.climate_entity,
                    hvac_mode,
                    climate_state.state,
                )
                if not await self._async_safe_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": self.climate_entity, "hvac_mode": hvac_mode},
                ):
                    _LOGGER.warning(
                        "Failed to set HVAC mode to %s for %s",
                        hvac_mode,
                        self.climate_entity,
                    )
                    return None
        else:
            # Mode change (e.g., heat to cool) - use set_hvac_mode
            if not await self._async_safe_service_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.climate_entity, "hvac_mode": hvac_mode},
            ):
                _LOGGER.warning(
                    "Failed to set HVAC mode to %s for %s",
                    hvac_mode,
                    self.climate_entity,
                )
                return None

        self._last_set_hvac_mode = hvac_mode
        self._last_mode_change_time = datetime.now()

        # Persist mode state for HA restart recovery
        await self._async_persist_mode_state()

        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        # Refresh climate state after HVAC changes to get updated attributes
        return self.hass.states.get(self.climate_entity)

    async def _set_auxiliary_parameters(
        self,
        climate_state: State,
        allow_auxiliary_calls: bool,
        target_temp: float | None,
        fan_mode: str | None,
        swing_mode: str | None,
        swing_horizontal_mode: str | None,
        delay_seconds: float,
    ) -> None:
        """Set auxiliary climate parameters (temperature, fan, swing modes)."""
        # Set temperature if provided
        if allow_auxiliary_calls and target_temp is not None:
            current_target_temp = climate_state.attributes.get("temperature")
            # Only set if different or not currently set
            if current_target_temp == target_temp:
                _LOGGER.debug(
                    "Temperature already at %.1f°C for %s, skipping",
                    target_temp,
                    self.climate_entity,
                )
            elif current_target_temp != target_temp:
                if not await self._async_safe_service_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": self.climate_entity, "temperature": target_temp},
                ):
                    _LOGGER.warning(
                        "Failed to set temperature to %.1f°C for %s",
                        target_temp,
                        self.climate_entity,
                    )
                    return
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

        # Set fan mode if supported and specified
        if (
            allow_auxiliary_calls
            and fan_mode
            and climate_state.attributes.get("fan_modes")
        ):
            current_fan_mode = climate_state.attributes.get("current_fan_mode")
            # Only set if different from current
            if current_fan_mode == fan_mode:
                _LOGGER.debug(
                    "Fan mode already set to %s for %s, skipping",
                    fan_mode,
                    self.climate_entity,
                )
            elif current_fan_mode != fan_mode:
                if not await self._async_safe_service_call(
                    "climate",
                    "set_fan_mode",
                    {"entity_id": self.climate_entity, "fan_mode": fan_mode},
                ):
                    _LOGGER.warning(
                        "Failed to set fan mode to %s for %s",
                        fan_mode,
                        self.climate_entity,
                    )
                    return
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

        # Set swing mode if supported and specified
        if (
            allow_auxiliary_calls
            and swing_mode
            and climate_state.attributes.get("swing_modes")
        ):
            current_swing_mode = climate_state.attributes.get("swing_mode")
            # Only set if different from current
            if current_swing_mode == swing_mode:
                _LOGGER.debug(
                    "Swing mode already set to %s for %s, skipping",
                    swing_mode,
                    self.climate_entity,
                )
            elif current_swing_mode != swing_mode:
                if not await self._async_safe_service_call(
                    "climate",
                    "set_swing_mode",
                    {"entity_id": self.climate_entity, "swing_mode": swing_mode},
                ):
                    _LOGGER.warning(
                        "Failed to set swing mode to %s for %s",
                        swing_mode,
                        self.climate_entity,
                    )
                    return
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

        # Set horizontal swing mode if supported and service available
        if (
            allow_auxiliary_calls
            and swing_horizontal_mode
            and climate_state.attributes.get("swing_horizontal_modes")
        ):
            current_swing_horizontal = climate_state.attributes.get(
                "swing_horizontal_mode"
            )
            # Only set if different from current
            if current_swing_horizontal == swing_horizontal_mode:
                _LOGGER.debug(
                    "Swing horizontal mode already set to %s for %s, skipping",
                    swing_horizontal_mode,
                    self.climate_entity,
                )
            elif current_swing_horizontal != swing_horizontal_mode:
                if self.hass.services.has_service(
                    "climate", "set_swing_horizontal_mode"
                ):
                    if not await self._async_safe_service_call(
                        "climate",
                        "set_swing_horizontal_mode",
                        {
                            "entity_id": self.climate_entity,
                            "swing_horizontal_mode": swing_horizontal_mode,
                        },
                    ):
                        _LOGGER.warning(
                            "Failed to set horizontal swing mode to %s for %s",
                            swing_horizontal_mode,
                            self.climate_entity,
                        )
                        return
                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
                else:
                    if not self._warned_horizontal_service_missing:
                        _LOGGER.warning(
                            "Horizontal swing mode requested (%s) but climate domain has no set_swing_horizontal_mode service",
                            swing_horizontal_mode,
                        )
                        self._warned_horizontal_service_missing = True

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
                    CONF_LIGHT_SELECT_OFF_OPTION,
                    CONF_LIGHT_SELECT_ON_OPTION,
                    DEFAULT_LIGHT_SELECT_OFF_OPTION,
                    DEFAULT_LIGHT_SELECT_ON_OPTION,
                )

                if option == "on":
                    select_option = self.config.get(
                        CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION
                    )
                else:
                    select_option = self.config.get(
                        CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION
                    )

                # Only set if different from current
                current_option = light_state.state
                if current_option != select_option:
                    if not await self._async_safe_service_call(
                        "select",
                        "select_option",
                        {"entity_id": entity_id, "option": select_option},
                    ):
                        _LOGGER.warning(
                            "Failed to set select option %s for %s",
                            select_option,
                            entity_id,
                        )
            elif domain in ("light", "switch"):
                # For light/switch entities, check current state before toggling
                service = "turn_on" if option == "on" else "turn_off"
                current_state = light_state.state
                target_state = "on" if option == "on" else "off"

                # Only set if different from current
                if current_state != target_state:
                    if not await self._async_safe_service_call(
                        domain,
                        service,
                        {"entity_id": entity_id},
                    ):
                        _LOGGER.warning(
                            "Failed to set %s to %s for %s",
                            domain,
                            target_state,
                            entity_id,
                        )
            else:
                _LOGGER.warning("Unsupported light control entity domain: %s", domain)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Failed to set light %s to %s: %s", entity_id, option, exc)

    async def async_set_timer(self, minutes: int) -> None:
        """Set or reset the minute countdown timer using expiry timestamp."""
        # Lock protects timer state (_timer_expiry, _timer_task) to prevent race conditions
        # where timer operations could conflict with concurrent timer reads or updates
        async with self._state_lock:
            new_minutes: int = max(0, minutes)

            # If timer requested while both automation and climate are off, reset to zero
            if new_minutes > 0 and not self._enabled and self._is_climate_off():
                new_minutes = 0

            # Cancel existing task
            if self._timer_task:
                self._timer_task.cancel()
                self._timer_task = None

            # Calculate expiry timestamp (None for no timer)
            if new_minutes > 0:
                self._timer_expiry = time.time() + (new_minutes * 60)
            else:
                self._timer_expiry = None

            await self._async_persist_timer()
            self._notify_timer_listeners()

            if self._timer_expiry is not None:
                self._timer_task = self._create_timer_task(self._async_timer_loop())
                _LOGGER.info(
                    "Timer started for %s: %d minutes (expires at %s)",
                    self.climate_entity,
                    new_minutes,
                    datetime.fromtimestamp(self._timer_expiry).isoformat(),
                )
            else:
                _LOGGER.debug("Timer cleared for %s", self.climate_entity)

    async def _async_migrate_timer_format(self) -> None:
        """Migrate timer from old minutes format to new expiry format."""
        try:
            new_options = {**self.entry.options}
            new_options[CONF_TIMER_EXPIRY] = self._timer_expiry
            new_options[CONF_TIMER_MINUTES] = 0  # Clear old format
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()
            self._needs_timer_migration = False
            _LOGGER.debug("Migrated timer format for %s", self.climate_entity)
        except Exception as exc:
            _LOGGER.warning("Failed to migrate timer format: %s", exc)

    async def _async_start_timer_if_needed(self) -> None:
        """Restart timer loop on setup if timer hasn't expired."""
        # Lock protects timer state check and task creation to prevent
        # race conditions when multiple timer operations occur during startup
        async with self._state_lock:
            if (
                self._timer_expiry is not None
                and time.time() < self._timer_expiry
                and not self._timer_task
            ):
                self._timer_task = self._create_timer_task(self._async_timer_loop())

    async def _async_timer_loop(self) -> None:
        """Timer loop that runs until expiry timestamp."""
        try:
            while True:
                # Lock protects timer expiry check to prevent race conditions
                # when timer is being modified by async_set_timer concurrently
                async with self._state_lock:
                    current_time = time.time()
                    if self._timer_expiry is None or current_time >= self._timer_expiry:
                        # Timer has expired or was cleared
                        if self._timer_expiry is not None:
                            await self._async_handle_timer_expired()
                        break

                    # Sleep until next minute boundary or expiry, whichever comes first
                    remaining_seconds = self._timer_expiry - current_time
                    sleep_time = min(60, remaining_seconds)

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                # Notify listeners of time update (for UI refresh)
                self._notify_timer_listeners()

        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled for %s", self.climate_entity)
        finally:
            # Lock protects timer task cleanup to ensure thread-safe
            # task reference management during timer loop termination
            async with self._state_lock:
                self._timer_task = None

    async def _async_handle_timer_expired(self) -> None:
        """Handle actions when timer reaches zero."""
        _LOGGER.info("Timer expired for %s", self.climate_entity)

        # Extract timer expiry outside of lock
        # Lock protects timer expiry reset to prevent race conditions
        # when timer expiration is handled concurrently with timer updates
        async with self._state_lock:
            self._timer_expiry = None

        # Don't hold timer lock while calling async_disable to avoid deadlocks
        if self._enabled:
            await self.async_disable()
        else:
            # Turn off climate if not already off
            climate_state = self.hass.states.get(self.climate_entity)
            if climate_state and not self._is_climate_off_state(climate_state):
                if not await self._async_safe_service_call(
                    "climate",
                    "turn_off",
                    {"entity_id": self.climate_entity},
                ):
                    _LOGGER.warning(
                        "Failed to turn off climate entity %s during timer expiration",
                        self.climate_entity,
                    )

        # Now persist without holding timer lock
        await self._async_persist_timer_value(None)
        self._notify_timer_listeners()
        await self._async_apply_light_behavior(enabled=False)

    async def _async_persist_timer(self) -> None:
        """Persist current timer expiry timestamp to config entry options."""
        await self._async_persist_timer_value(self._timer_expiry)

    async def _async_persist_timer_value(self, timer_expiry: float | None) -> None:
        """Persist timer expiry value to config (call without holding timer lock)."""
        # Lock protects config updates to ensure atomic timer persistence
        # and prevent race conditions when multiple timer operations update config
        async with self._config_lock:
            new_options = {**self.entry.options}
            new_options[CONF_TIMER_EXPIRY] = timer_expiry
            # Clear old format to avoid confusion
            new_options[CONF_TIMER_MINUTES] = 0
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()

    async def _async_persist_mode_state(self) -> None:
        """Persist current mode state to config entry options."""
        # Lock protects config updates to ensure atomic mode state persistence
        # and prevent race conditions when multiple operations update config
        async with self._config_lock:
            new_options = {**self.entry.options}
            new_options[CONF_LAST_MODE_CHANGE_TIME] = (
                self._last_mode_change_time.isoformat()
                if self._last_mode_change_time
                else None
            )
            new_options[CONF_LAST_SET_HVAC_MODE] = self._last_set_hvac_mode
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()

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
