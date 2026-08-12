"""Core Climate React controller."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from homeassistant.components import logbook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
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
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_LAST_MODE_CHANGE_TIME,
    CONF_LAST_SET_HVAC_MODE,
    CONF_LIGHT_BEHAVIOR,
    CONF_LIGHT_ENTITY,
    CONF_MAX_TEMP,
    CONF_MIN_RUN_TIME,
    CONF_MIN_TEMP,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_LOW_TEMP,
    CONF_SWING_LOW_TEMP,
    CONF_TEMP_HIGH_TEMP,
    CONF_TEMP_LOW_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TIMER_EXPIRY,
    CONF_TIMER_MINUTES,
    CONF_USE_EXTERNAL_TEMP_SENSOR,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_ENABLE_LIGHT_CONTROL,
    DEFAULT_ENABLED,
    DEFAULT_LIGHT_BEHAVIOR,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_RUN_TIME,
    DEFAULT_MIN_TEMP,
    DEFAULT_TIMER_MINUTES,
    DOMAIN,
    LIGHT_BEHAVIOR_OFF,
    LIGHT_BEHAVIOR_ON,
    MAX_CONCURRENT_BACKGROUND_TASKS,
    MAX_RETRY_ATTEMPTS,
    MAX_STATE_LOG_ENTRIES,
    MODE_NONE,
    MODE_OFF,
)


class StateChangeDetails(TypedDict, total=False):
    """Type definition for state change log details."""

    temperature: float | None
    threshold: float | None
    action: str | None
    mode: str | None
    action_taken: str | None
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
        self._unsub_temp: Callable[[], None] | None = None
        self._unsub_climate: Callable[[], None] | None = None
        config_data = {**entry.data, **entry.options}
        self._enabled = config_data.get(CONF_ENABLED, DEFAULT_ENABLED)
        self._last_temp: float | None = None
        self._warned_horizontal_service_missing = False
        self._climate_min_temp: float | None = None
        self._climate_max_temp: float | None = None
        self._last_mode_change_time: datetime | None = None
        self._last_set_hvac_mode: str | None = None
        # Snapshot of the climate parameters (hvac mode, fan, swing, target temp)
        # that this automation last set or observed on enable. Used to detect
        # manual overrides: any of these changing outside an automation command
        # means the user took manual control.
        self._last_automation_params: dict[str, Any] | None = None
        self._climate_command_in_progress = False
        self._last_threshold_state: str | None = None  # Track: "low", "high", or "normal"
        self._cached_config: dict[str, Any] | None = None  # Cache for merged config
        self._cached_min_run_time: int | None = None  # Cached min run time in minutes
        self._needs_timer_migration: bool = False
        # Initialize timer expiry timestamp (migrate from old minutes format if needed)
        self._timer_expiry: float | None = None

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
        self._state_change_log: deque[dict[str, Any]] = deque(maxlen=MAX_STATE_LOG_ENTRIES)

        # Sensor change debouncing to prevent excessive evaluations
        self._debounce_temp_timer: asyncio.TimerHandle | None = None
        self._pending_temperature: float | None = None

        # Task throttling
        self._task_semaphore = asyncio.Semaphore(MAX_CONCURRENT_BACKGROUND_TASKS)

        # Task queue for efficient background processing
        # Queue holds asyncio.Task objects to ensure consistent cancellation/awaiting
        # Invariant: items pushed into this queue are `asyncio.Task` instances
        # created by `self.hass.loop.create_task(coro)`; during shutdown we
        # drain the queue and cancel those Task objects to release references.
        self._task_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        # Metrics
        self._dropped_task_count: int = 0
        self._queue_peak: int = 0
        # Shutdown & processor control
        self._shutting_down: bool = False
        self._processor_stop_event: asyncio.Event = asyncio.Event()
        self._task_processor_task: asyncio.Task | None = None

        # Pre-allocated common objects for performance
        self._empty_details: dict[str, Any] = {}

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
                restored = datetime.fromisoformat(last_change_str)
                # Legacy persisted values may be naive (stored before UTC-aware
                # datetimes were used). Ensure the restored datetime is always
                # timezone-aware to avoid TypeError when subtracting from
                # datetime.now(UTC) in _can_change_mode.
                if restored.tzinfo is None:
                    restored = restored.replace(tzinfo=UTC)
                self._last_mode_change_time = restored
            except ValueError:
                _LOGGER.warning("Invalid last mode change time format: %s", last_change_str)
                self._last_mode_change_time = None

        self._last_set_hvac_mode = config_data.get(CONF_LAST_SET_HVAC_MODE)

        self._timer_task: asyncio.Task | None = None
        self._timer_listeners: list[Callable[[], None]] = []
        # Listeners notified when the enabled state changes (for UI refresh,
        # e.g. when manual override detection or timer expiry disables automation).
        self._enabled_listeners: list[Callable[[], None]] = []
        # Listeners notified when config options change (for entity UI refresh,
        # e.g. fan/swing selects disabling when the mode select is set to off).
        self._config_listeners: list[Callable[[], None]] = []

    def _debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Centralized debug logging helper for controller messages.

        Prefixes debug messages with the climate entity id for consistency and
        forwards all kwargs (such as `exc_info`) to the logger.
        """
        try:
            _LOGGER.debug("%s: " + msg, self.climate_entity, *args, **kwargs)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(msg, *args, **kwargs)

    def _create_tracked_task(self, coro) -> None:
        """Add a coroutine to the task queue for efficient processing.

        Args:
            coro: A coroutine object to queue for background execution
        """
        # Don't accept new tasks during shutdown
        if getattr(self, "_shutting_down", False):
            self._dropped_task_count += 1
            self._debug("Controller shutting down; dropping new tracked task")
            return

        # Always wrap coroutine into a Task so shutdown can cancel/await consistently
        try:
            task = self.hass.loop.create_task(coro)
        except Exception:
            _LOGGER.exception("Failed to create tracked task")
            return
        try:
            self._task_queue.put_nowait(task)
            # Track peak queue size for observability
            try:
                qsize = self._task_queue.qsize()
                self._queue_peak = max(self._queue_peak, qsize)
            except Exception:  # noqa: BLE001, S110
                pass
        except asyncio.QueueFull:
            # Task was already started — cancel it so it doesn't run untracked
            task.cancel()
            self._dropped_task_count += 1
            _LOGGER.warning("Task queue full; cancelling untracked task to prevent memory growth")
        except Exception:
            _LOGGER.exception("Failed to create/enqueue tracked task")

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
        # Loop until stop event is set and queue emptied. Use a short timeout on get
        # so we can react to the stop event promptly.
        while True:
            # Exit condition: stop requested and queue empty
            if self._processor_stop_event.is_set() and self._task_queue.empty():
                break
            try:
                try:
                    task: asyncio.Task = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                # Ensure we have a Task; if not, wrap defensively
                if not isinstance(task, asyncio.Task):
                    task = self.hass.loop.create_task(task)

                async with self._task_semaphore:
                    try:
                        await task
                    except asyncio.CancelledError:
                        # Task cancelled during shutdown or by caller
                        self._debug("Background task was cancelled")
                    except Exception:
                        _LOGGER.exception("Task processing error")
            except asyncio.CancelledError:
                self._debug("Task processor cancelled")
                break
            except RuntimeError:
                _LOGGER.exception("Runtime error in task processor")
            except Exception:
                _LOGGER.exception("Unexpected error in task processor")

    @property
    def _min_run_time_minutes(self) -> int:
        """Get cached minimum run time in minutes."""
        result = self._cached_min_run_time
        if result is None:
            result = self.config.get(CONF_MIN_RUN_TIME, DEFAULT_MIN_RUN_TIME)
            self._cached_min_run_time = result
        return result

    def _invalidate_config_cache(self) -> None:
        """Invalidate the config cache when options are updated."""
        self._cached_config = None
        # Reset cached derived values
        self._cached_min_run_time = None

    def _validate_entity_id(self, entity_id: str) -> bool:
        """Validate entity exists and is accessible."""
        if not entity_id or "." not in entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None

    def register_state_listener(self, entity_ids: list[str], callback: Callable) -> Callable[[], None]:
        """Register a state-change listener and return an unsubscribe callable.

        This centralizes the use of `async_track_state_change_event` so entity
        classes can use `controller.register_state_listener(...)` and avoid
        repeating registration/unregistration logic.
        """
        return async_track_state_change_event(self.hass, entity_ids, callback)

    def _get_switch_entity_id(self) -> str:
        """Get the switch entity ID for logbook entries."""
        # Attach logbook entries to the control switch for the climate.
        # Use the sanitized climate name so activity logs appear under
        # `switch.climate_react_<climate>_control` (e.g. switch.climate_react_study_control).
        climate_part = self.climate_entity.split(".")[-1].lower()
        climate_safe = re.sub(r"[^a-z0-9]", "_", climate_part)
        return f"switch.climate_react_{climate_safe}_control"

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
    def enabled(self) -> bool:
        """Check if Climate React is enabled."""
        return self._enabled

    @property
    def light_entity(self) -> str | None:
        """Light/select entity used for light control."""
        enabled = self.config.get(CONF_ENABLE_LIGHT_CONTROL, DEFAULT_ENABLE_LIGHT_CONTROL)
        if not enabled:
            # Light control explicitly disabled in config; treat as if no light configured
            return None
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

    def _entity_suffix(self) -> str:
        """Return a sanitized suffix for entity IDs: <climate_name>_<entry_id>.

        Both parts are lowercased and non-alphanumeric chars replaced with
        underscores to produce valid, unique identifiers.
        """
        climate_part = self.climate_entity.split(".")[-1].lower()
        # Only use the sanitized climate name as the suffix. Omitting the
        # config entry id keeps unique_ids stable to the climate name and
        # avoids exposing UUID-like strings in IDs.
        climate_safe = re.sub(r"[^a-z0-9]", "_", climate_part)
        return climate_safe

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
        self._debug("Added timer listener (total listeners: %d)", len(self._timer_listeners))

        def _remove() -> None:
            if callback in self._timer_listeners:
                self._timer_listeners.remove(callback)
                self._debug(
                    "Removed timer listener (total listeners: %d)",
                    len(self._timer_listeners),
                )

        return _remove

    def _notify_timer_listeners(self) -> None:
        """Notify timer listeners of an update."""
        # Create a copy of the list to avoid issues if listeners modify the list
        total = len(self._timer_listeners)
        self._debug(
            "Notifying %d timer listener(s) (timer minutes: %d)",
            total,
            self.timer_minutes,
        )

        for listener in list(self._timer_listeners):
            try:
                listener()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Error notifying timer listener: %s", exc)

    def add_enabled_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback to be notified when the enabled state changes.

        This lets entities (e.g. the control switch) refresh their UI when the
        automation disables itself via manual override detection or timer expiry.
        """
        self._enabled_listeners.append(callback)
        self._debug("Added enabled listener (total listeners: %d)", len(self._enabled_listeners))

        def _remove() -> None:
            if callback in self._enabled_listeners:
                self._enabled_listeners.remove(callback)
                self._debug(
                    "Removed enabled listener (total listeners: %d)",
                    len(self._enabled_listeners),
                )

        return _remove

    def _notify_enabled_listeners(self) -> None:
        """Notify enabled listeners of an update."""
        # Create a copy of the list to avoid issues if listeners modify the list
        total = len(self._enabled_listeners)
        self._debug(
            "Notifying %d enabled listener(s) (enabled: %s)",
            total,
            self._enabled,
        )

        for listener in list(self._enabled_listeners):
            try:
                listener()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Error notifying enabled listener: %s", exc)

    def add_config_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback to be notified when config options change."""
        self._config_listeners.append(callback)

        def _remove() -> None:
            if callback in self._config_listeners:
                self._config_listeners.remove(callback)

        return _remove

    def _notify_config_listeners(self) -> None:
        """Notify config listeners of an update."""
        for listener in list(self._config_listeners):
            try:
                listener()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Error notifying config listener: %s", exc)

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

        # Defensive: ensure last_change is timezone-aware. Legacy persisted
        # values restored before the UTC fix may still be naive, and subtracting
        # a naive datetime from datetime.now(UTC) raises TypeError.
        if last_change.tzinfo is None:
            last_change = last_change.replace(tzinfo=UTC)

        elapsed = datetime.now(UTC) - last_change
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
                if change_type == "temperature_threshold" and _LOGGER.isEnabledFor(logging.INFO):
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
                elif change_type == "manual_override" and _LOGGER.isEnabledFor(logging.WARNING):
                    _LOGGER.warning(
                        "👤 Manual override detected for %s: mode changed from %s to %s",
                        self.climate_entity,
                        details.get("old_mode"),
                        details.get("new_mode"),
                    )
                elif change_type == "climate_command" and _LOGGER.isEnabledFor(logging.INFO):
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
                time_since_failure = current_time - self._service_call_last_failure[service_key]
                if time_since_failure > self._circuit_breaker_timeout:
                    self._service_call_failures[service_key] = 0
                    del self._service_call_last_failure[service_key]
                    self._debug("Circuit breaker reset for %s after timeout", service_key)
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
                        self._debug(
                            "Cleared failure count for %s due to successful call",
                            service_key,
                        )
                    if service_key in self._service_call_last_failure:
                        del self._service_call_last_failure[service_key]
                else:
                    # Increment failure count
                    self._service_call_failures[service_key] = self._service_call_failures.get(service_key, 0) + 1
                    self._service_call_last_failure[service_key] = time.time()

        # Schedule the recording task
        if self.hass:
            self._create_tracked_task(_record())

    def _validate_climate_capability(self, capability_type: str, value: str | None) -> bool:
        """Validate that the climate entity supports a given capability value."""
        if not value:
            return True  # None values are always valid

        # Home Assistant climate entities may support turning off even when
        # `off` is not explicitly listed in `hvac_modes`.
        if capability_type == "hvac_modes" and value == MODE_OFF:
            return True

        current_time = time.time()
        cache_key = f"{self.climate_entity}_{capability_type}"

        # Check cache first (valid for configured duration)
        if (
            cache_key in self._capability_validation_time
            and current_time - self._capability_validation_time[cache_key] < CAPABILITY_CACHE_DURATION_SECONDS
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
            supported_values = set(climate_state.attributes.get("swing_horizontal_modes", []))

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

    async def _async_safe_service_call(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        """Make a service call with retry logic and circuit breaker protection."""
        service_key = f"{domain}.{service}"

        # Check circuit breaker
        if await self._check_circuit_breaker(service_key):
            return False

        # Attempt service call with exponential backoff retry
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                _LOGGER.debug("Sending %s.%s to %s", domain, service, data)
                await self.hass.services.async_call(domain, service, data, blocking=True)
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
            except Exception as exc:  # noqa: BLE001
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

        # 2. Check entity existence
        entities_to_check = [
            (CONF_CLIMATE_ENTITY, self.climate_entity, "Climate entity"),
            (CONF_TEMPERATURE_SENSOR, self.temperature_sensor, "Temperature sensor"),
        ]

        if self.light_entity:
            entities_to_check.append((CONF_LIGHT_ENTITY, self.light_entity, "Light entity"))

        for _conf_key, entity_id, description in entities_to_check:
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
            ]

            for _conf_key, mode, description in configured_modes:
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
            ]

            for _conf_key, fan_mode, description in configured_fan_modes:
                if fan_mode and fan_mode not in supported_fan_modes:
                    issues_found.append(
                        f"⚠️  {description} '{fan_mode}' is not supported by climate entity '{self.climate_entity}'. "
                        f"Supported fan modes: {supported_fan_modes}"
                    )

            # Validate swing modes if configured
            supported_swing_modes = climate_state.attributes.get("swing_modes", [])
            configured_swing_modes = [
                (
                    CONF_SWING_LOW_TEMP,
                    config.get(CONF_SWING_LOW_TEMP),
                    "Low temperature swing mode",
                ),
                (
                    CONF_SWING_HIGH_TEMP,
                    config.get(CONF_SWING_HIGH_TEMP),
                    "High temperature swing mode",
                ),
            ]

            for _conf_key, swing_mode, description in configured_swing_modes:
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

        # Subscribe to climate entity changes: manual override detection, threshold
        # sync, and state evaluation. A single listener replaces what was previously
        # two separate listeners on the same entity.
        self._unsub_climate = async_track_state_change_event(
            self.hass,
            [self.climate_entity],
            self._async_climate_state_changed,
        )

        # Start the task processor for efficient background processing
        self._debug("Starting task processor")
        self._task_processor_task = self.hass.loop.create_task(self._process_task_queue())

        # Initial state evaluation
        await self._async_evaluate_state()
        await self._async_start_timer_if_needed()

        # Handle timer migration if needed
        if self._needs_timer_migration:
            try:
                await self._async_migrate_timer_format()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Timer migration failed, clearing flag: %s", exc)
                self._needs_timer_migration = False

        _LOGGER.info(
            "Climate React controller initialized for %s (temp: %s)",
            self.climate_entity,
            self.temperature_sensor,
        )

    async def async_shutdown(self) -> None:
        """Shut down the controller."""
        if self._unsub_temp:
            self._unsub_temp()
        if self._unsub_climate:
            self._unsub_climate()

        # Cancel timer task without holding _state_lock.
        # The timer loop's finally block assigns self._timer_task = None directly
        # (without a lock), so cancelling and awaiting here is safe without the lock.
        # Holding _state_lock while awaiting the timer task would deadlock because
        # the task's finally block previously tried to acquire the same lock.
        timer_task = self._timer_task
        self._timer_task = None
        if timer_task:
            timer_task.cancel()
            try:
                await timer_task
            except asyncio.CancelledError:
                pass

        # Cancel task processor
        # Signal processor to stop accepting new work and exit when queue empty
        self._shutting_down = True
        self._processor_stop_event.set()

        # Drain task queue, cancel each task, then await all to suppress warnings
        cancelled_tasks: list[asyncio.Task] = []
        try:
            while True:
                task = self._task_queue.get_nowait()
                if isinstance(task, asyncio.Task):
                    try:
                        task.cancel()
                        cancelled_tasks.append(task)
                    except RuntimeError:
                        _LOGGER.exception("RuntimeError cancelling queued task during shutdown")
                    except Exception:
                        _LOGGER.exception("Failed to cancel queued task during shutdown")
        except asyncio.QueueEmpty:
            pass
        if cancelled_tasks:
            await asyncio.gather(*cancelled_tasks, return_exceptions=True)

        # Cancel and await the processor to ensure it exits cleanly
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

        # Clear timer listeners to prevent memory leaks
        self._timer_listeners.clear()

        # Clear enabled listeners to prevent memory leaks
        self._enabled_listeners.clear()

        _LOGGER.info("Climate React controller shut down for %s", self.climate_entity)

    async def async_enable(self) -> None:
        """Enable Climate React."""
        self._enabled = True
        # Reset the threshold-state latch so re-enabling re-evaluates the
        # current temperature (e.g. the AC was off but the temp is still above
        # the high threshold — it must turn on, not be skipped as a duplicate).
        self._last_threshold_state = None
        # Establish a baseline of the climate parameters under automation control
        # so any subsequent external change is detected as a manual override.
        self._last_automation_params = self._capture_climate_params(self.hass.states.get(self.climate_entity))
        await self._async_persist_enabled_state()
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
        self._notify_enabled_listeners()

    async def async_disable(self) -> None:
        """Disable Climate React."""
        self._enabled = False
        # Clear the threshold latch so the automation re-evaluates from scratch
        # when it is next enabled (prevents stale "high/low" from suppressing
        # commands after re-enable).
        self._last_threshold_state = None
        await self._async_persist_enabled_state()
        # Turn off the climate entity when automation is disabled (matches Node-RED behavior:
        # switch turning off immediately sends climate.set_hvac_mode("off"))
        if not self._is_climate_off() and not await self._async_safe_service_call(
            "climate", "turn_off", {"entity_id": self.climate_entity}
        ):
            _LOGGER.warning(
                "Failed to turn off climate entity %s on disable",
                self.climate_entity,
            )
        if self.timer_minutes > 0:
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
        self._notify_enabled_listeners()

    async def async_update_thresholds(self, data: dict[str, Any]) -> None:
        """Update thresholds dynamically."""
        # Lock protects threshold config updates to ensure atomic operations
        # and prevent race conditions during concurrent threshold modifications
        async with self._config_lock:
            # Update config entry options
            new_options = {**self.entry.options}

            if CONF_MIN_TEMP in data:
                new_options[CONF_MIN_TEMP] = data[CONF_MIN_TEMP]
            if CONF_MAX_TEMP in data:
                new_options[CONF_MAX_TEMP] = data[CONF_MAX_TEMP]

            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()

        # Reset the threshold latch so the new thresholds are applied immediately
        self._last_threshold_state = None

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
        # Notify entities (e.g. fan/swing selects) so they can refresh their
        # availability when the mode for their threshold side changes.
        self._notify_config_listeners()

    async def _async_sync_thresholds_to_climate(self, climate_state: State) -> None:
        """No-op: room-temperature thresholds are independent of the climate
        entity's setpoint range (the min_temp/max_temp attributes), so we no
        longer clamp or persist them here. Kept as a hook for future use."""
        return

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

            # Always keep the last reading for UI/diagnostics (thread-safe)
            # Lock protects _last_temp to prevent race conditions when multiple
            # temperature updates occur simultaneously from different event sources
            async with self._state_lock:
                self._last_temp = temperature
            _LOGGER.debug("Temperature changed to %.1f°C for %s", temperature, self.climate_entity)

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
            self._debug("Canceling existing temperature debounce timer")
            self._debounce_temp_timer.cancel()

        # Schedule new evaluation after debounce delay
        delay = 1.0
        self._debug(
            "Scheduling temperature debounce (%.1fs) with pending temp %.2f",
            delay,
            temperature,
        )
        self._debounce_temp_timer = self.hass.loop.call_later(
            delay,
            lambda: self._create_tracked_task(self._process_pending_temperature()),
        )

    async def _process_pending_temperature(self) -> None:
        """Process pending temperature threshold evaluation."""
        if self._pending_temperature is not None:
            temperature = self._pending_temperature
            self._pending_temperature = None
            await self._async_handle_temperature_threshold(temperature)

    async def _async_climate_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle all climate entity state changes.

        Covers: threshold sync, state evaluation, timer management when disabled,
        and manual override detection when enabled.
        """
        new_state: State | None = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        # Sync thresholds to climate entity limits on every valid state update.
        # This replaces the former separate _async_climate_available listener.
        await self._async_sync_thresholds_to_climate(new_state)

        # Skip full state evaluation when the climate entity is also the temperature
        # sensor: _async_temperature_changed fires for the same event and handles
        # threshold evaluation via the debounce path, so calling _async_evaluate_state
        # here would produce a duplicate (un-debounced) evaluation 1 second early.
        if self.temperature_sensor != self.climate_entity:
            await self._async_evaluate_state()

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

        if self._climate_command_in_progress:
            return

        current_mode = new_state.state

        # Manual override detection: if any climate parameter under this
        # automation's control changes outside of a command issued by the
        # automation, the user has taken manual control. Log a warning and
        # deactivate the automation (turns off the control switch).
        if not self._climate_params_match(new_state, self._last_automation_params):
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
            self._last_automation_params = None
            # Clear the threshold latch so a subsequent re-enable re-evaluates
            # from a clean state.
            self._last_threshold_state = None
            # Persist cleared mode state for HA restart recovery
            await self._async_persist_enabled_state()
            await self._async_persist_mode_state()
            await self._async_apply_light_behavior(enabled=False)
            self._notify_enabled_listeners()

    async def _async_evaluate_state(self) -> None:
        """Evaluate current sensor states."""
        # Collect data under lock to get consistent snapshot of sensor states
        # and enabled flag, preventing race conditions during evaluation
        async with self._state_lock:
            temp_state = self.hass.states.get(self.temperature_sensor)
            enabled = self._enabled

        # Process temperature (outside lock)
        if temp_state and temp_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                use_external_temp = self.entry.data.get(CONF_USE_EXTERNAL_TEMP_SENSOR, False)
                if not use_external_temp and temp_state.entity_id == self.climate_entity:
                    temperature = temp_state.attributes.get("current_temperature")
                    if temperature is None:
                        return
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
                    self._create_tracked_task(self._async_handle_temperature_threshold(temperature))
            except Exception:
                pass

    async def _async_handle_temperature_threshold(self, temperature: float) -> None:
        """Handle temperature threshold logic."""
        # Never command the climate once the automation has been disabled (e.g.
        # after a manual override): a debounce task scheduled before the override
        # could still be pending, and it must not touch the user's climate settings.
        if not self._enabled:
            return

        config = self.config
        # Use .get() with sensible defaults so legacy entries missing these keys
        # don't raise KeyError when a temperature threshold is crossed.
        min_temp = config.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
        max_temp = config.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)

        # Determine current threshold state
        if temperature < min_temp:
            current_threshold_state = "low"
        elif temperature > max_temp:
            current_threshold_state = "high"
        else:
            current_threshold_state = "normal"

        async with self._state_lock:
            # Check if we're already in this threshold state - if so, skip
            if self._last_threshold_state == current_threshold_state:
                _LOGGER.debug(
                    "Temperature %.1f°C is in '%s' threshold state for %s (thresholds: min=%.1f°C, max=%.1f°C)",
                    temperature,
                    current_threshold_state,
                    self.climate_entity,
                    min_temp,
                    max_temp,
                )
                return

            # The minimum-run-time gate only applies while the AC is running.
            # If the AC is off, turn it on immediately when a threshold is
            # crossed (e.g. on enable, or after the AC self-cycled off).
            if not self._is_climate_off() and not self._can_change_mode():
                self._log_state_change(
                    "temperature_threshold_blocked",
                    {
                        "temperature": temperature,
                        "reason": "minimum_run_time_not_elapsed",
                        "last_change": str(self._last_mode_change_time),
                    },
                )
                if temperature < min_temp:
                    _LOGGER.debug(
                        "Low temp threshold crossed (%.1f°C < %.1f°C) for %s but minimum run time not elapsed; skipping",
                        temperature,
                        min_temp,
                        self.climate_entity,
                    )
                elif temperature > max_temp:
                    _LOGGER.debug(
                        "High temp threshold crossed (%.1f°C > %.1f°C) for %s but minimum run time not elapsed; skipping",
                        temperature,
                        max_temp,
                        self.climate_entity,
                    )
                return

            # Update threshold state only after the min-run-time gate: a
            # transition blocked by minimum run time must NOT be committed,
            # otherwise the duplicate-state check above would suppress every
            # later retry and the climate would never switch (e.g. the AC
            # never turning on once the minimum run time has elapsed).
            self._last_threshold_state = current_threshold_state

        # Determine action based on thresholds
        if temperature < min_temp:
            # Low temperature - trigger heating
            mode = config.get(CONF_MODE_LOW_TEMP)
            if mode == MODE_NONE:
                _LOGGER.debug(
                    "Low temp threshold crossed (%.1f°C < %.1f°C) for %s but mode is 'none', skipping",
                    temperature,
                    min_temp,
                    self.climate_entity,
                )
                return
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

            await self._async_set_climate(mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp)

        elif temperature > max_temp:
            # High temperature - trigger cooling
            mode = config.get(CONF_MODE_HIGH_TEMP)
            if mode == MODE_NONE:
                _LOGGER.debug(
                    "High temp threshold crossed (%.1f°C > %.1f°C) for %s but mode is 'none', skipping",
                    temperature,
                    max_temp,
                    self.climate_entity,
                )
                return
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

            await self._async_set_climate(mode, fan_mode, swing_mode, swing_horizontal_mode, target_temp)
        else:
            # Temperature is within normal range - turn off the climate only if
            # the automation itself turned it on (never a manually-started AC).
            _LOGGER.debug(
                "Temperature %.1f°C within range [%.1f, %.1f] for %s",
                temperature,
                min_temp,
                max_temp,
                self.climate_entity,
            )
            if self._last_set_hvac_mode is not None and not self._is_climate_off():
                _LOGGER.info(
                    "Temperature returned to normal range, turning off %s",
                    self.climate_entity,
                )
                await self._async_set_climate(MODE_OFF, None, None, None, None)

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

        self._climate_command_in_progress = True
        try:
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
            delay_seconds = config.get(CONF_DELAY_BETWEEN_COMMANDS, DEFAULT_DELAY_BETWEEN_COMMANDS) / 1000.0

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

            # Set HVAC mode
            climate_state = await self._set_hvac_mode(hvac_mode, climate_state, delay_seconds)
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

            # Record the parameters under automation control from the actual
            # reported state (falling back to what we sent for any the AC hasn't
            # echoed yet), so subsequent external changes are detected as overrides.
            captured = self._capture_climate_params(self.hass.states.get(self.climate_entity))
            self._last_automation_params = {
                "hvac_mode": captured["hvac_mode"] or hvac_mode,
                "fan_mode": captured["fan_mode"] if captured["fan_mode"] is not None else fan_mode,
                "swing_mode": captured["swing_mode"] if captured["swing_mode"] is not None else swing_mode,
                "swing_horizontal_mode": (
                    captured["swing_horizontal_mode"]
                    if captured["swing_horizontal_mode"] is not None
                    else swing_horizontal_mode
                ),
                "temperature": captured["temperature"] if captured["temperature"] is not None else target_temp,
            }
        finally:
            self._climate_command_in_progress = False

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
            _LOGGER.warning("Skipping climate command due to invalid HVAC mode: %s", hvac_mode)
            return None
        if fan_mode and not self._validate_climate_capability("fan_modes", fan_mode):
            _LOGGER.warning("Skipping fan mode setting due to invalid fan mode: %s", fan_mode)
            fan_mode = None
        if swing_mode and not self._validate_climate_capability("swing_modes", swing_mode):
            _LOGGER.warning("Skipping swing mode setting due to invalid swing mode: %s", swing_mode)
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
            if supported_attr == "hvac_modes" and option == MODE_OFF:
                return option
            if not climate_state:
                return option
            supported = climate_state.attributes.get(supported_attr)
            if isinstance(supported, list) and option not in supported:
                # Skip rather than silently substituting supported[0], which could
                # pick an unintended mode (e.g. "off" for fan) or turn off the AC.
                _LOGGER.debug(
                    "Option '%s' not in supported %s for %s, skipping",
                    option,
                    supported_attr,
                    self.climate_entity,
                )
                return None
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

    async def _set_hvac_mode(
        self,
        hvac_mode: str | None,
        climate_state: State | None,
        delay_seconds: float,
    ) -> State | None:
        """Set HVAC mode with proper turn_on/off/set_hvac_mode logic."""
        if not hvac_mode or hvac_mode == (climate_state.state if climate_state else None):
            _LOGGER.debug(
                "HVAC mode already %s for %s, skipping",
                hvac_mode or "unset",
                self.climate_entity,
            )
            # Still update _last_set_hvac_mode to prevent false manual override detection
            if hvac_mode:
                self._last_set_hvac_mode = hvac_mode
            return climate_state

        if hvac_mode == MODE_OFF:
            # Turning off - use turn_off service
            if not await self._async_safe_service_call(
                "climate",
                "turn_off",
                {"entity_id": self.climate_entity},
            ):
                _LOGGER.warning("Failed to turn off climate entity %s", self.climate_entity)
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
                    _LOGGER.warning("Failed to set HVAC mode to off for %s", self.climate_entity)
                    return None
        elif climate_state and climate_state.state == MODE_OFF:
            # Currently off, turning on - use turn_on service
            if not await self._async_safe_service_call(
                "climate",
                "turn_on",
                {"entity_id": self.climate_entity},
            ):
                _LOGGER.warning("Failed to turn on climate entity %s", self.climate_entity)
                return None
            # Verify it actually turned on; only fall back to set_hvac_mode if it
            # is still off (many ACs briefly transition through another mode after
            # turn_on, which is not an error).
            climate_state = self.hass.states.get(self.climate_entity)
            if climate_state and climate_state.state == MODE_OFF:
                _LOGGER.debug(
                    "turn_on didn't turn on %s (current: %s), using set_hvac_mode fallback",
                    self.climate_entity,
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
        self._last_mode_change_time = datetime.now(UTC)

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
            else:
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
        if allow_auxiliary_calls and fan_mode and climate_state.attributes.get("fan_modes"):
            current_fan_mode = climate_state.attributes.get("fan_mode")
            # Only set if different from current
            if current_fan_mode == fan_mode:
                _LOGGER.debug(
                    "Fan mode already set to %s for %s, skipping",
                    fan_mode,
                    self.climate_entity,
                )
            else:
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
        if allow_auxiliary_calls and swing_mode and climate_state.attributes.get("swing_modes"):
            current_swing_mode = climate_state.attributes.get("swing_mode")
            # Only set if different from current
            if current_swing_mode == swing_mode:
                _LOGGER.debug(
                    "Swing mode already set to %s for %s, skipping",
                    swing_mode,
                    self.climate_entity,
                )
            else:
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
        if allow_auxiliary_calls and swing_horizontal_mode and climate_state.attributes.get("swing_horizontal_modes"):
            current_swing_horizontal = climate_state.attributes.get("swing_horizontal_mode")
            # Only set if different from current
            if current_swing_horizontal == swing_horizontal_mode:
                _LOGGER.debug(
                    "Swing horizontal mode already set to %s for %s, skipping",
                    swing_horizontal_mode,
                    self.climate_entity,
                )
            else:
                if self.hass.services.has_service("climate", "set_swing_horizontal_mode"):
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
                    select_option = self.config.get(CONF_LIGHT_SELECT_ON_OPTION, DEFAULT_LIGHT_SELECT_ON_OPTION)
                else:
                    select_option = self.config.get(CONF_LIGHT_SELECT_OFF_OPTION, DEFAULT_LIGHT_SELECT_OFF_OPTION)

                # Only set if different from current
                current_option = light_state.state
                if current_option != select_option and not await self._async_safe_service_call(
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
                if current_state != target_state and not await self._async_safe_service_call(
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

            # Capture expiry for use outside the lock
            timer_expiry = self._timer_expiry

            if timer_expiry is not None:
                self._timer_task = self._create_timer_task(self._async_timer_loop())

        # Persist and notify OUTSIDE state_lock to maintain lock hierarchy:
        # _config_lock must never be acquired while holding _state_lock.
        await self._async_persist_timer_value(timer_expiry)
        self._notify_timer_listeners()

        if timer_expiry is not None:
            _LOGGER.info(
                "Timer started for %s: %d minutes (expires at %s)",
                self.climate_entity,
                new_minutes,
                datetime.fromtimestamp(timer_expiry, tz=UTC).isoformat(),
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
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to migrate timer format: %s", exc)

    async def _async_start_timer_if_needed(self) -> None:
        """Restart timer loop on setup, or fire missed expiry if HA was down when it elapsed."""
        missed_expiry: float | None = None
        async with self._state_lock:
            expiry = self._timer_expiry
            if expiry is None:
                return
            if time.time() < expiry:
                # Timer still in the future — resume the countdown
                if not self._timer_task:
                    self._timer_task = self._create_timer_task(self._async_timer_loop())
            else:
                # Timer expired while HA was down — consume the stale expiry
                # so _async_handle_timer_expired finds a clean state (no double-fire),
                # then fire the action outside the lock (avoid lock re-entrancy).
                self._timer_expiry = None
                missed_expiry = expiry

        if missed_expiry is not None:
            _LOGGER.warning(
                "Timer for %s expired while HA was down (expiry: %s); executing missed expiry action now",
                self.climate_entity,
                datetime.fromtimestamp(missed_expiry, tz=UTC).isoformat(),
            )
            await self._async_handle_timer_expired()

    async def _async_timer_loop(self) -> None:
        """Timer loop that runs until expiry timestamp."""
        try:
            while True:
                # Take a consistent snapshot under lock, then release before any await.
                # This prevents the loop from holding _state_lock across a suspension
                # point, which would cause a deadlock with _async_handle_timer_expired
                # (which also needs _state_lock) and with async_shutdown.
                async with self._state_lock:
                    current_time = time.time()
                    expiry_snapshot = self._timer_expiry  # local copy so Pylance can narrow
                    timer_expired = expiry_snapshot is not None and current_time >= expiry_snapshot
                    should_stop = expiry_snapshot is None or timer_expired
                    # expiry_snapshot is guaranteed non-None when not should_stop
                    remaining_seconds = (
                        (expiry_snapshot - current_time) if expiry_snapshot is not None and not should_stop else 0.0
                    )

                # Handle expiry and break OUTSIDE the lock to avoid re-entrant
                # lock acquisition inside _async_handle_timer_expired.
                if timer_expired:
                    await self._async_handle_timer_expired()
                if should_stop:
                    break

                sleep_time = min(60, remaining_seconds)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                # Notify listeners of time update (for UI refresh)
                self._notify_timer_listeners()

        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled for %s", self.climate_entity)
        finally:
            # Direct assignment without acquiring _state_lock: the lock may be held
            # by async_shutdown (which cancels this task and then awaits it).
            # Acquiring _state_lock here would deadlock shutdown.
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
            # async_disable internally calls _async_apply_light_behavior(enabled=False)
            await self.async_disable()
        else:
            # Turn off climate if not already off
            climate_state = self.hass.states.get(self.climate_entity)
            if (
                climate_state
                and not self._is_climate_off_state(climate_state)
                and not await self._async_safe_service_call(
                    "climate",
                    "turn_off",
                    {"entity_id": self.climate_entity},
                )
            ):
                _LOGGER.warning(
                    "Failed to turn off climate entity %s during timer expiration",
                    self.climate_entity,
                )
            # Automation was already disabled; still apply light behavior
            await self._async_apply_light_behavior(enabled=False)

        # Now persist without holding timer lock
        await self._async_persist_timer_value(None)
        self._notify_timer_listeners()

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
                self._last_mode_change_time.isoformat() if self._last_mode_change_time else None
            )
            new_options[CONF_LAST_SET_HVAC_MODE] = self._last_set_hvac_mode
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()

    async def _async_persist_enabled_state(self) -> None:
        """Persist enabled state to config entry options."""
        async with self._config_lock:
            new_options = {**self.entry.options}
            new_options[CONF_ENABLED] = self._enabled
            self.hass.config_entries.async_update_entry(self.entry, options=new_options)
            self._invalidate_config_cache()

    async def _async_apply_light_behavior(self, enabled: bool) -> None:
        """Apply light behavior when automation switch toggles."""
        light_entity = self.light_entity
        if not light_entity:
            return
        behavior = self.light_behavior
        if behavior == LIGHT_BEHAVIOR_OFF:
            # "off" means: light follows inverse of switch (off when AC runs, on when stopped)
            await self._async_set_light(light_entity, "off" if enabled else "on")
        elif behavior == LIGHT_BEHAVIOR_ON:
            await self._async_set_light(light_entity, "on" if enabled else "off")
        # LIGHT_BEHAVIOR_UNCHANGED: do nothing

    def _is_climate_off(self) -> bool:
        """Return True if climate entity is currently off."""
        state = self.hass.states.get(self.climate_entity)
        return self._is_climate_off_state(state)

    def _capture_climate_params(self, state: State | None) -> dict[str, Any]:
        """Capture the climate parameters that fall under automation control.

        Only these are tracked for manual-override detection; the constantly
        changing current_temperature reading is intentionally excluded.
        """
        if not state:
            return {}
        return {
            "hvac_mode": state.state,
            "fan_mode": state.attributes.get("fan_mode"),
            "swing_mode": state.attributes.get("swing_mode"),
            "swing_horizontal_mode": state.attributes.get("swing_horizontal_mode"),
            "temperature": state.attributes.get("temperature"),
        }

    def _climate_params_match(self, state: State | None, expected: dict[str, Any] | None) -> bool:
        """Return True if the climate state matches the params the automation last set."""
        if not state or not expected:
            return True

        def _eq(a: Any, b: Any) -> bool:
            if a is None or b is None:
                return a is b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return round(float(a), 1) == round(float(b), 1)
            return str(a).strip().lower() == str(b).strip().lower()

        if expected.get("hvac_mode") is not None and not _eq(state.state, expected["hvac_mode"]):
            return False
        for attr in ("fan_mode", "swing_mode", "swing_horizontal_mode", "temperature"):
            val = expected.get(attr)
            if val is None:
                continue
            current = state.attributes.get(attr)
            if current is None:
                continue  # AC hasn't reported it yet — don't flag as an override
            if not _eq(current, val):
                return False
        return True

    @staticmethod
    def _is_climate_off_state(state: State | None) -> bool:
        if not state:
            return True
        return state.state == MODE_OFF
