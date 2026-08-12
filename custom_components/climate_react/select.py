"""Select platform for Climate React integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate_react import ClimateReactController
from .const import (
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_LIGHT_BEHAVIOR,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_LOW_TEMP,
    CONF_SWING_LOW_TEMP,
    DATA_COORDINATOR,
    DOMAIN,
    LIGHT_BEHAVIOR_OFF,
    LIGHT_BEHAVIOR_ON,
    LIGHT_BEHAVIOR_UNCHANGED,
    MODE_NONE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React select entities from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    ent_registry = entity_registry.async_get(hass)

    # Remove stale light behavior entity when light control is disabled
    if not controller.light_entity:
        suffix = controller._entity_suffix()
        stale_id = ent_registry.async_get_entity_id("select", DOMAIN, f"climate_react_{suffix}_light_behavior")
        if stale_id:
            ent_registry.async_remove(stale_id)

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

        return selects

    # Get initial climate state
    climate_state = hass.states.get(controller.climate_entity)

    # Build candidates - if climate unavailable, we'll still add entities and they'll get enabled when climate becomes available
    entities: list[SelectEntity]
    if climate_state and climate_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        entities = _build_candidates(climate_state)
    else:
        # Climate not available yet - create entities with fallback to detect all capabilities once available
        # This ensures entities are registered even if climate entity is still loading
        entities = [
            ClimateReactModeLowTempSelect(controller, entry),
            ClimateReactModeHighTempSelect(controller, entry),
            ClimateReactFanLowTempSelect(controller, entry),
            ClimateReactFanHighTempSelect(controller, entry),
            ClimateReactSwingLowTempSelect(controller, entry),
            ClimateReactSwingHighTempSelect(controller, entry),
            ClimateReactSwingHorizontalLowTempSelect(controller, entry),
            ClimateReactSwingHorizontalHighTempSelect(controller, entry),
        ]
        # Add light entity if available
        if controller.light_entity:
            entities.append(ClimateReactLightBehaviorSelect(controller, entry))
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
            if not ent_registry.async_get_entity_id("select", DOMAIN, getattr(entity, "unique_id", ""))
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
    _state["unsub_climate"] = controller.register_state_listener([controller.climate_entity], _on_climate_change)
    entry.async_on_unload(_state["unsub_climate"])  # type: ignore[arg-type]


class ClimateReactBaseSelect(SelectEntity):
    """Base class for Climate React select entities."""

    _attr_has_entity_name = True
    _allowed_options: ClassVar[list[str] | None] = None
    _static_extra_options: ClassVar[list[str]] = []
    _attr_options: ClassVar[list[str]] = []
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
    def options(self) -> list[str]:  # type: ignore[override]
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
        self.async_write_ha_state()

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

        # Append static options (e.g. MODE_NONE) that are always available
        for extra in self._static_extra_options:
            if extra not in options:
                options.append(extra)

        self._attr_options = options

        # Restore current option from config entry. If the configured value is not
        # in the supported options, show no selection (None) rather than a misleading
        # fallback that the config does not actually hold.
        config = {**self._entry.data, **self._entry.options}
        config_option = config.get(self._config_key)
        if config_option in options:
            self._attr_current_option = config_option
        else:
            self._attr_current_option = None

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
    _allowed_options: ClassVar[list[str]] = ["heat", "fan_only", "off"]
    _static_extra_options: ClassVar[list[str]] = [MODE_NONE]

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
    _allowed_options: ClassVar[list[str]] = ["cool", "fan_only", "off"]
    _static_extra_options: ClassVar[list[str]] = [MODE_NONE]

    def __init__(self, controller: ClimateReactController, entry: ConfigEntry) -> None:
        """Initialize the select."""
        super().__init__(controller, entry)
        suffix = controller._entity_suffix()
        self._attr_unique_id = f"climate_react_{suffix}_mode_high_temp"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_MODE_HIGH_TEMP, "cool")


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
        self._attr_current_option = config.get(CONF_LIGHT_BEHAVIOR, LIGHT_BEHAVIOR_UNCHANGED)

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
    def available(self) -> bool:  # type: ignore[override]
        return self._controller.light_entity is not None
