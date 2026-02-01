"""Select platform for Climate React integration."""

from __future__ import annotations

import logging
from typing import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate_react import ClimateReactController
from .const import (
    CONF_FAN_HIGH_HUMIDITY,
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_LIGHT_BEHAVIOR,
    CONF_MODE_HIGH_HUMIDITY,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    CONF_SWING_HIGH_HUMIDITY,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_HIGH_HUMIDITY,
    CONF_SWING_HORIZONTAL_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_LOW_TEMP,
    CONF_SWING_LOW_TEMP,
    CONF_USE_HUMIDITY,
    DATA_COORDINATOR,
    DOMAIN,
    LIGHT_BEHAVIOR_OFF,
    LIGHT_BEHAVIOR_ON,
    LIGHT_BEHAVIOR_UNCHANGED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React select entities from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    ent_registry = entity_registry.async_get(hass)

    def _build_candidates(state) -> list[SelectEntity]:
        """Construct all select entities supported by current state."""

        def _supports(attr: str) -> bool:
            supported = state.attributes.get(attr)
            return isinstance(supported, list) and len(supported) > 0

        selects: list[SelectEntity] = []

        # Light behavior select (requires configured light entity)
        if controller.light_entity:
            selects.append(ClimateReactLightBehaviorSelect(controller, entry))

        if _supports("hvac_modes"):
            selects.extend(
                [
                    ClimateReactModeLowTempSelect(controller, entry),
                    ClimateReactModeHighTempSelect(controller, entry),
                ]
            )
        if _supports("fan_modes"):
            selects.extend(
                [
                    ClimateReactFanLowTempSelect(controller, entry),
                    ClimateReactFanHighTempSelect(controller, entry),
                ]
            )
        if _supports("swing_modes"):
            selects.extend(
                [
                    ClimateReactSwingLowTempSelect(controller, entry),
                    ClimateReactSwingHighTempSelect(controller, entry),
                ]
            )
        if _supports("swing_horizontal_modes"):
            selects.extend(
                [
                    ClimateReactSwingHorizontalLowTempSelect(controller, entry),
                    ClimateReactSwingHorizontalHighTempSelect(controller, entry),
                ]
            )

        # --- HYBRID HUMIDITY LOGIC ---
        ac_humidity_controls = entry.data.get("ac_humidity_controls", False)
        if entry.data.get(CONF_USE_HUMIDITY, False):
            # Detect if climate supports humidity control
            supports_humidity = "target_humidity" in state.attributes or _supports(
                "humidity_modes"
            )
            if supports_humidity and ac_humidity_controls:
                # AC supports humidity: create selects for both high and low humidity
                if _supports("hvac_modes"):
                    selects.append(
                        ClimateReactModeHighHumiditySelect(controller, entry)
                    )
                if _supports("fan_modes"):
                    selects.append(ClimateReactFanHighHumiditySelect(controller, entry))
                if _supports("swing_modes"):
                    selects.append(
                        ClimateReactSwingHighHumiditySelect(controller, entry)
                    )
                if _supports("swing_horizontal_modes"):
                    selects.append(
                        ClimateReactSwingHorizontalHighHumiditySelect(controller, entry)
                    )
                # For low humidity (humidification)
                if _supports("hvac_modes"):
                    selects.append(ClimateReactModeLowHumiditySelect(controller, entry))
                if _supports("fan_modes"):
                    selects.append(ClimateReactFanLowHumiditySelect(controller, entry))
                if _supports("swing_modes"):
                    selects.append(
                        ClimateReactSwingLowHumiditySelect(controller, entry)
                    )
                if _supports("swing_horizontal_modes"):
                    selects.append(
                        ClimateReactSwingHorizontalLowHumiditySelect(controller, entry)
                    )
            # else: No AC humidity support or not enabled: only create humidifier control (if implemented)
        return selects

    # Get initial climate state
    climate_state = hass.states.get(controller.climate_entity)

    # Build candidates - if climate unavailable, we'll still add entities and they'll get enabled when climate becomes available
    if climate_state and climate_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        entities = _build_candidates(climate_state)
    else:
        # Climate not available yet - create entities with fallback to detect all capabilities once available
        # This ensures entities are registered even if climate entity is still loading
        entities = [
            (
                ClimateReactLightBehaviorSelect(controller, entry)
                if controller.light_entity
                else None
            ),
            ClimateReactModeLowTempSelect(controller, entry),
            ClimateReactModeHighTempSelect(controller, entry),
            ClimateReactFanLowTempSelect(controller, entry),
            ClimateReactFanHighTempSelect(controller, entry),
            ClimateReactSwingLowTempSelect(controller, entry),
            ClimateReactSwingHighTempSelect(controller, entry),
            ClimateReactSwingHorizontalLowTempSelect(controller, entry),
            ClimateReactSwingHorizontalHighTempSelect(controller, entry),
        ]
        # Add humidity entities if enabled
        if entry.data.get(CONF_USE_HUMIDITY, False):
            entities.extend(
                [
                    ClimateReactModeHighHumiditySelect(controller, entry),
                    ClimateReactFanHighHumiditySelect(controller, entry),
                    ClimateReactSwingHighHumiditySelect(controller, entry),
                    ClimateReactSwingHorizontalHighHumiditySelect(controller, entry),
                ]
            )
        # Filter out None values
        entities = [e for e in entities if e is not None]
        _LOGGER.info(
            "Climate entity %s unavailable at setup, created %d select entities (will become available when climate loads)",
            controller.climate_entity,
            len(entities),
        )

    _LOGGER.info(
        "Setting up %d select entities for climate %s",
        len(entities),
        controller.climate_entity,
    )
    async_add_entities(entities, True)

    # Store tracking state for listener management
    _state: dict[str, Callable[[], None] | None] = {"unsub_climate": None}

    # Track climate entity changes to add new entities if capabilities expand
    async def _on_climate_change(event) -> None:
        new_state = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        # Build candidates and check for new entities
        candidates = _build_candidates(new_state)
        to_add = [
            entity
            for entity in candidates
            if not ent_registry.async_get_entity_id(
                "select", DOMAIN, getattr(entity, "unique_id", "")
            )
        ]

        if to_add:
            _LOGGER.info(
                "Adding %d new select entities for climate %s (capabilities expanded)",
                len(to_add),
                controller.climate_entity,
            )
            async_add_entities(to_add, True)

    # Centralized registration via controller helper to avoid repeating
    # direct `async_track_state_change_event` usage across entities.
    _state["unsub_climate"] = controller.register_state_listener(
        [controller.climate_entity], _on_climate_change
    )
    entry.async_on_unload(_state["unsub_climate"])


class ClimateReactBaseSelect(SelectEntity):
    """Base class for Climate React select entities."""

    _attr_has_entity_name = True
    _allowed_options: list[str] | None = None  # Optional filter for allowed options
    _attr_options: list[str] = []  # Initialize with empty list
    _climate_attr: str | None = None
    _config_key: str

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select entity."""
        self._controller = controller
        self._entry = entry
        self._unsub_climate: Callable[[], None] | None = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": controller.get_device_name(),
            "manufacturer": "TTLucian",
            "model": "Climate Automation Controller",
        }

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        return getattr(self, "_attr_options", [])

    async def async_added_to_hass(self) -> None:
        """Handle entity addition."""
        await super().async_added_to_hass()

        # Track climate entity to refresh supported options dynamically
        # Use controller helper to centralize listener management
        self._unsub_climate = self._controller.register_state_listener(
            [self._controller.climate_entity], self._async_climate_changed
        )

        # Initialize options based on current climate state
        self._refresh_options(self.hass.states.get(self._controller.climate_entity))

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal."""
        if self._unsub_climate:
            self._unsub_climate()

    @callback
    async def _async_climate_changed(self, event) -> None:
        """Handle climate entity state changes."""
        self._refresh_options(event.data.get("new_state"))
        self.async_write_ha_state()

    def _refresh_options(self, state) -> None:
        """Refresh options based on climate supported features."""
        options: list[str] = []
        if state:
            supported = state.attributes.get(self._climate_attr)
            if isinstance(supported, list):
                options = [opt for opt in supported if isinstance(opt, str)]

                # Apply allowed options filter if defined
                if self._allowed_options is not None:
                    options = [opt for opt in options if opt in self._allowed_options]

        self._attr_options = options

        # Clamp current option to supported list
        config = {**self._entry.data, **self._entry.options}
        config_option = config.get(self._config_key)
        if config_option in options:
            self._attr_current_option = config_option
        else:
            fallback = options[0] if options else None
            self._attr_current_option = fallback
            # Persist fallback to options to keep controller in sync
            if fallback is not None:
                new_options = {**self._entry.options}
                new_options[self._config_key] = fallback
                self.hass.config_entries.async_update_entry(
                    self._entry, options=new_options
                )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if self._attr_options and option not in self._attr_options:
            _LOGGER.warning(
                "Option %s not supported by climate entity %s",
                option,
                self._controller.climate_entity,
            )
            return

        # Update controller - this updates options without full reload
        await self._controller.async_update_option(self._config_key, option)

        # Update local state
        self._attr_current_option = option
        self.async_write_ha_state()


# HVAC Mode Selects


class ClimateReactModeLowTempSelect(ClimateReactBaseSelect):
    """Select entity for HVAC mode when temperature is low."""

    _attr_name = "Mode Low Temperature"
    _attr_icon = "mdi:thermostat"
    _config_key = CONF_MODE_LOW_TEMP
    _climate_attr = "hvac_modes"
    _allowed_options = ["heat", "fan_only", "off"]

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_mode_low_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_MODE_LOW_TEMP, "heat")


class ClimateReactModeHighTempSelect(ClimateReactBaseSelect):
    """Select entity for HVAC mode when temperature is high."""

    _attr_name = "Mode High Temperature"
    _attr_icon = "mdi:thermostat"
    _config_key = CONF_MODE_HIGH_TEMP
    _climate_attr = "hvac_modes"
    _allowed_options = ["cool", "fan_only", "off"]

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_mode_high_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_MODE_HIGH_TEMP, "cool")


class ClimateReactModeHighHumiditySelect(ClimateReactBaseSelect):
    """Select entity for HVAC mode when humidity is high."""

    _attr_name = "Mode High Humidity"
    _attr_icon = "mdi:thermostat"
    _config_key = CONF_MODE_HIGH_HUMIDITY
    _climate_attr = "hvac_modes"
    _allowed_options = ["dry", "fan_only", "off"]

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_mode_high_humidity"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_MODE_HIGH_HUMIDITY, "dry")


# Fan Mode Selects


class ClimateReactFanLowTempSelect(ClimateReactBaseSelect):
    """Select entity for fan mode when temperature is low."""

    _attr_name = "Fan Low Temperature"
    _attr_icon = "mdi:fan"
    _config_key = CONF_FAN_LOW_TEMP
    _climate_attr = "fan_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_fan_low_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_FAN_LOW_TEMP, "auto")


class ClimateReactFanHighTempSelect(ClimateReactBaseSelect):
    """Select entity for fan mode when temperature is high."""

    _attr_name = "Fan High Temperature"
    _attr_icon = "mdi:fan"
    _config_key = CONF_FAN_HIGH_TEMP
    _climate_attr = "fan_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_fan_high_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_FAN_HIGH_TEMP, "auto")


class ClimateReactFanHighHumiditySelect(ClimateReactBaseSelect):
    """Select entity for fan mode when humidity is high."""

    _attr_name = "Fan High Humidity"
    _attr_icon = "mdi:fan"
    _config_key = CONF_FAN_HIGH_HUMIDITY
    _climate_attr = "fan_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_fan_high_humidity"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_FAN_HIGH_HUMIDITY, "auto")


# Swing Mode Selects


class ClimateReactSwingLowTempSelect(ClimateReactBaseSelect):
    """Select entity for swing mode when temperature is low."""

    _attr_name = "Swing Low Temperature"
    _attr_icon = "mdi:arrow-oscillating"
    _config_key = CONF_SWING_LOW_TEMP
    _climate_attr = "swing_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_low_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_LOW_TEMP, "off")


class ClimateReactSwingHighTempSelect(ClimateReactBaseSelect):
    """Select entity for swing mode when temperature is high."""

    _attr_name = "Swing High Temperature"
    _attr_icon = "mdi:arrow-oscillating"
    _config_key = CONF_SWING_HIGH_TEMP
    _climate_attr = "swing_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_high_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_HIGH_TEMP, "off")


class ClimateReactSwingHighHumiditySelect(ClimateReactBaseSelect):
    """Select entity for swing mode when humidity is high."""

    _attr_name = "Swing High Humidity"
    _attr_icon = "mdi:arrow-oscillating"
    _config_key = CONF_SWING_HIGH_HUMIDITY
    _climate_attr = "swing_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_high_humidity"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_HIGH_HUMIDITY, "off")


class ClimateReactSwingHorizontalLowTempSelect(ClimateReactBaseSelect):
    """Select entity for horizontal swing mode when temperature is low."""

    _attr_name = "Swing Horizontal Low Temperature"
    _attr_icon = "mdi:arrow-left-right"
    _config_key = CONF_SWING_HORIZONTAL_LOW_TEMP
    _climate_attr = "swing_horizontal_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_horizontal_low_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_HORIZONTAL_LOW_TEMP)


class ClimateReactSwingHorizontalHighTempSelect(ClimateReactBaseSelect):
    """Select entity for horizontal swing mode when temperature is high."""

    _attr_name = "Swing Horizontal High Temperature"
    _attr_icon = "mdi:arrow-left-right"
    _config_key = CONF_SWING_HORIZONTAL_HIGH_TEMP
    _climate_attr = "swing_horizontal_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_horizontal_high_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_HORIZONTAL_HIGH_TEMP)


class ClimateReactSwingHorizontalHighHumiditySelect(ClimateReactBaseSelect):
    """Select entity for horizontal swing mode when humidity is high."""

    _attr_name = "Swing Horizontal High Humidity"
    _attr_icon = "mdi:arrow-left-right"
    _config_key = CONF_SWING_HORIZONTAL_HIGH_HUMIDITY
    _climate_attr = "swing_horizontal_modes"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_horizontal_high_humidity"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_HORIZONTAL_HIGH_HUMIDITY)


class ClimateReactLightBehaviorSelect(ClimateReactBaseSelect):
    """Select entity for light behavior when automation toggles."""

    _attr_name = "Light Behavior"
    _attr_icon = "mdi:lightbulb-auto"
    _config_key = CONF_LIGHT_BEHAVIOR
    _climate_attr = None

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_light_behavior"
        config = {**entry.data, **entry.options}
        self._allowed_options = [
            LIGHT_BEHAVIOR_ON,
            LIGHT_BEHAVIOR_OFF,
            LIGHT_BEHAVIOR_UNCHANGED,
        ]
        self._attr_current_option = config.get(
            CONF_LIGHT_BEHAVIOR, LIGHT_BEHAVIOR_UNCHANGED
        )

    def _refresh_options(self, state) -> None:
        """Light behavior select options are static."""
        assert self._allowed_options is not None
        self._attr_options = self._allowed_options
        config = {**self._entry.data, **self._entry.options}
        config_option = config.get(self._config_key)
        if config_option and config_option in self._allowed_options:
            self._attr_current_option = config_option
        else:
            self._attr_current_option = LIGHT_BEHAVIOR_UNCHANGED

    @property
    def available(self) -> bool:
        return self._controller.light_entity is not None


class ClimateReactModeLowHumiditySelect(ClimateReactBaseSelect):
    """Select for AC mode when humidity is below min threshold (humidification)."""

    _attr_translation_key = "mode_low_humidity"
    _allowed_options = ["auto", "dry", "off", "heat", "cool", "fan_only"]

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_mode_low_humidity"

    def _refresh_options(self, state) -> None:
        options = []
        if state and "hvac_modes" in state.attributes:
            options = [
                opt
                for opt in state.attributes["hvac_modes"]
                if opt in self._allowed_options
            ]
        self._attr_options = options


class ClimateReactFanLowHumiditySelect(ClimateReactBaseSelect):
    """Select for AC fan mode when humidity is below min threshold (humidification)."""

    _attr_translation_key = "fan_low_humidity"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_fan_low_humidity"

    def _refresh_options(self, state) -> None:
        options = []
        if state and "fan_modes" in state.attributes:
            options = list(state.attributes["fan_modes"])
        self._attr_options = options


class ClimateReactSwingLowHumiditySelect(ClimateReactBaseSelect):
    """Select for AC swing mode when humidity is below min threshold (humidification)."""

    _attr_translation_key = "swing_low_humidity"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_low_humidity"

    def _refresh_options(self, state) -> None:
        options = []
        if state and "swing_modes" in state.attributes:
            options = list(state.attributes["swing_modes"])
        self._attr_options = options


class ClimateReactSwingHorizontalLowHumiditySelect(ClimateReactBaseSelect):
    """Select for AC horizontal swing mode when humidity is below min threshold (humidification)."""

    _attr_translation_key = "swing_horizontal_low_humidity"

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_swing_horizontal_low_humidity"

    def _refresh_options(self, state) -> None:
        options = []
        if state and "swing_horizontal_modes" in state.attributes:
            options = list(state.attributes["swing_horizontal_modes"])
        self._attr_options = options
