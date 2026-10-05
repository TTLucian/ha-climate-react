"""Number platform for Climate React integration."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate_react import ClimateReactController
from .const import (
    CONF_DELAY_BETWEEN_COMMANDS,
    CONF_MAX_TEMP,
    CONF_MIN_RUN_TIME,
    CONF_MIN_TEMP,
    CONF_TEMP_HIGH_TEMP,
    CONF_TEMP_LOW_TEMP,
    CONF_TIMER_MINUTES,
    DATA_COORDINATOR,
    DEFAULT_DELAY_BETWEEN_COMMANDS,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_RUN_TIME,
    DEFAULT_MIN_TEMP,
    DEFAULT_TEMP_HIGH_TEMP,
    DEFAULT_TEMP_LOW_TEMP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React number entities from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    numbers = [
        ClimateReactMinTempNumber(controller, entry),
        ClimateReactMaxTempNumber(controller, entry),
        ClimateReactTempLowTempNumber(controller, entry),
        ClimateReactTempHighTempNumber(controller, entry),
        ClimateReactDelayBetweenCommandsNumber(controller, entry),
        ClimateReactMinRunTimeNumber(controller, entry),
        ClimateReactTimerNumber(controller, entry),
    ]

    async_add_entities(numbers, True)


class ClimateReactBaseNumber(NumberEntity):
    """Base class for Climate React number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _config_key: str
    _default_value: float = 0.0
    # Set on temperature-valued entities so their allowed range follows the
    # setpoint limits the climate entity advertises.
    _uses_climate_range: bool = False
    # Fallback bounds, used only while the unit reports no usable range.
    _fallback_min_value: float = 0.0
    _fallback_max_value: float = 40.0

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        self._controller = controller
        self._entry = entry
        self._remove_bounds_listener: Callable[[], None] | None = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
        }

    def _climate_temperature_bounds(self) -> tuple[float, float]:
        """Return the setpoint range the climate entity advertises.

        A unit cannot cool below its own ``min_temp`` or heat above its
        ``max_temp``, so a threshold or target outside that range is one the
        hardware cannot honour. Falls back to the entity defaults while the
        unit is offline or reports nothing usable, so the number always has
        bounds.
        """
        state = self.hass.states.get(self._controller.climate_entity)
        low = high = None
        if state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raw_low = state.attributes.get("min_temp")
            raw_high = state.attributes.get("max_temp")
            if isinstance(raw_low, (int, float)):
                low = float(raw_low)
            if isinstance(raw_high, (int, float)):
                high = float(raw_high)

        if low is None or high is None or low >= high:
            return (self._fallback_min_value, self._fallback_max_value)
        return (low, high)

    @property
    def native_min_value(self) -> float:  # type: ignore[override]
        """Lower bound; from the climate entity when this entity is a temperature."""
        if self._uses_climate_range:
            return self._climate_temperature_bounds()[0]
        return self._attr_native_min_value

    @property
    def native_max_value(self) -> float:  # type: ignore[override]
        """Upper bound; from the climate entity when this entity is a temperature."""
        if self._uses_climate_range:
            return self._climate_temperature_bounds()[1]
        return self._attr_native_max_value

    @property
    def native_value(self) -> float | None:
        """Always read from the live config entry so restarts never show stale data."""
        return self._controller.config.get(self._config_key, self._default_value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._uses_climate_range:
            # The bounds are read live, so refresh when the unit reports a
            # range it did not report at startup.
            self._remove_bounds_listener = self._controller.register_state_listener(
                [self._controller.climate_entity],
                self._async_climate_bounds_changed,
            )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from climate updates."""
        if self._remove_bounds_listener:
            self._remove_bounds_listener()
            self._remove_bounds_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _async_climate_bounds_changed(self, event) -> None:
        """Refresh when the unit reports a different setpoint range."""
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Update the threshold value."""
        await self._controller.async_update_option(self._config_key, value)
        self.async_write_ha_state()


class ClimateReactMinTempNumber(ClimateReactBaseNumber):
    """Number entity for minimum temperature threshold."""

    _attr_name = "Minimum Temperature"
    _attr_icon = "mdi:thermometer-low"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _uses_climate_range = True
    _attr_native_step = 0.1
    _config_key = CONF_MIN_TEMP
    _default_value = DEFAULT_MIN_TEMP

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the min temp number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_min_temp"


class ClimateReactMaxTempNumber(ClimateReactBaseNumber):
    """Number entity for maximum temperature threshold."""

    _attr_name = "Maximum Temperature"
    _attr_icon = "mdi:thermometer-high"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _uses_climate_range = True
    _attr_native_step = 0.1
    _config_key = CONF_MAX_TEMP
    _default_value = DEFAULT_MAX_TEMP

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the max temp number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_max_temp"


class ClimateReactTempLowTempNumber(ClimateReactBaseNumber):
    """Number entity for target temperature at low threshold."""

    _attr_name = "Target Temperature Low"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _uses_climate_range = True
    _attr_native_step = 0.5
    _config_key = CONF_TEMP_LOW_TEMP
    _default_value = DEFAULT_TEMP_LOW_TEMP

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the target temp low number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_temp_low_temp"


class ClimateReactTempHighTempNumber(ClimateReactBaseNumber):
    """Number entity for target temperature at high threshold."""

    _attr_name = "Target Temperature High"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _uses_climate_range = True
    _attr_native_step = 0.5
    _config_key = CONF_TEMP_HIGH_TEMP
    _default_value = DEFAULT_TEMP_HIGH_TEMP

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the target temp high number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_temp_high_temp"


class ClimateReactDelayBetweenCommandsNumber(ClimateReactBaseNumber):
    """Number entity for delay between commands."""

    _attr_name = "Delay Between Commands (ms)"
    _attr_icon = "mdi:clock"
    _attr_native_unit_of_measurement = "ms"
    _attr_native_min_value = 0
    _attr_native_max_value = 5000
    _attr_native_step = 100
    _config_key = CONF_DELAY_BETWEEN_COMMANDS
    _default_value = DEFAULT_DELAY_BETWEEN_COMMANDS

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the delay between commands number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_delay_between_commands"


class ClimateReactMinRunTimeNumber(ClimateReactBaseNumber):
    """Number entity for minimum runtime between mode changes."""

    _attr_name = "Minimum Run Time (minutes)"
    _attr_icon = "mdi:timer"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _config_key = CONF_MIN_RUN_TIME
    _default_value = DEFAULT_MIN_RUN_TIME

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the min run time number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_min_run_time"


class ClimateReactTimerNumber(ClimateReactBaseNumber):
    """Number entity for the shutdown timer in minutes."""

    _attr_name = "Timer"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 240
    _attr_native_step = 10
    _attr_mode = NumberMode.SLIDER
    _config_key = CONF_TIMER_MINUTES

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the timer number."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_timer"
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self._controller.add_timer_listener(self._on_timer_updated)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    def _on_timer_updated(self) -> None:
        # Don't set _attr_native_value - use property getter instead
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        return self._controller.timer_minutes

    async def async_set_native_value(self, value: float) -> None:
        """Set timer minutes and propagate to controller."""
        await self._controller.async_set_timer(round(value))
