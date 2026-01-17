"""Select platform for Climate React integration."""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .climate_react import ClimateReactController
from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_FAN_HIGH_HUMIDITY,
    CONF_FAN_HIGH_TEMP,
    CONF_FAN_LOW_TEMP,
    CONF_HUMIDITY_SENSOR,
    CONF_MODE_HIGH_HUMIDITY,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    CONF_SWING_HIGH_HUMIDITY,
    CONF_SWING_HIGH_TEMP,
    CONF_SWING_LOW_TEMP,
    CONF_SWING_HORIZONTAL_HIGH_HUMIDITY,
    CONF_SWING_HORIZONTAL_HIGH_TEMP,
    CONF_SWING_HORIZONTAL_LOW_TEMP,
    CONF_USE_HUMIDITY,
    DATA_COORDINATOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate React select entities from a config entry."""
    controller: ClimateReactController = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    created_ids: set[str] = set()

    def _build_candidates(state) -> list[SelectEntity]:
        """Construct all select entities supported by current state."""
        def _supports(attr: str) -> bool:
            supported = state.attributes.get(attr)
            return isinstance(supported, list) and len(supported) > 0

        selects: list[SelectEntity] = []

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

        if entry.data.get(CONF_USE_HUMIDITY, False):
            if _supports("hvac_modes"):
                selects.append(ClimateReactModeHighHumiditySelect(controller, entry))
            if _supports("fan_modes"):
                selects.append(ClimateReactFanHighHumiditySelect(controller, entry))
            if _supports("swing_modes"):
                selects.append(ClimateReactSwingHighHumiditySelect(controller, entry))
            if _supports("swing_horizontal_modes"):
                selects.append(ClimateReactSwingHorizontalHighHumiditySelect(controller, entry))

        return selects

    async def _sync_entities(state) -> None:
        """Add any missing select entities based on current capabilities."""
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        candidates = _build_candidates(state)
        to_add = [entity for entity in candidates if getattr(entity, "unique_id", None) not in created_ids]
        if to_add:
            created_ids.update(
                uid for uid in (getattr(entity, "unique_id", "") for entity in to_add) if uid
            )
            _LOGGER.info(
                "Adding %d new select entities for climate %s (capabilities: hvac_modes=%s, fan_modes=%s, swing_modes=%s, swing_horizontal_modes=%s)",
                len(to_add),
                controller.climate_entity,
                isinstance(state.attributes.get("hvac_modes"), list),
                isinstance(state.attributes.get("fan_modes"), list),
                isinstance(state.attributes.get("swing_modes"), list),
                isinstance(state.attributes.get("swing_horizontal_modes"), list),
            )
            async_add_entities(to_add, True)
        # Remove select entities if corresponding capability is no longer supported
        supported_attrs = {
            "hvac_modes": ["mode_low_temp", "mode_high_temp", "mode_high_humidity"],
            "fan_modes": ["fan_low_temp", "fan_high_temp", "fan_high_humidity"],
            "swing_modes": ["swing_low_temp", "swing_high_temp", "swing_high_humidity"],
            "swing_horizontal_modes": [
                "swing_horizontal_low_temp",
                "swing_horizontal_high_temp",
                "swing_horizontal_high_humidity",
            ],
        }
        ent_registry = entity_registry.async_get(hass)
        for attr, entity_suffixes in supported_attrs.items():
            if not isinstance(state.attributes.get(attr), list):
                # Capability no longer supported; remove associated entities
                for suffix in entity_suffixes:
                    entity_id = ent_registry.async_get_entity_id(
                        "select", DOMAIN, f"{entry.entry_id}_{suffix}"
                    )
                    if entity_id:
                        _LOGGER.info(
                            "Removing select entity %s (capability %s no longer supported)",
                            entity_id,
                            attr,
                        )
                        ent_registry.async_remove(entity_id)
                        created_ids.discard(f"{entry.entry_id}_{suffix}")

    climate_state = hass.states.get(controller.climate_entity)

    if climate_state and climate_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        await _sync_entities(climate_state)

    @callback
    async def _on_climate_change(event) -> None:
        await _sync_entities(event.data.get("new_state"))

    unsub = async_track_state_change_event(
        hass,
        [controller.climate_entity],
        _on_climate_change,
    )
    entry.async_on_unload(unsub)
    if not climate_state or climate_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        _LOGGER.info(
            "Waiting for climate entity %s to become available before creating select entities",
            controller.climate_entity,
        )


class ClimateReactBaseSelect(SelectEntity):
    """Base class for Climate React select entities."""

    _attr_has_entity_name = True
    _allowed_options: list[str] | None = None  # Optional filter for allowed options
    _attr_options: list[str] = []  # Initialize with empty list

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
        self._unsub_climate = async_track_state_change_event(
            self.hass,
            [self._controller.climate_entity],
            self._async_climate_changed,
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
                self.hass.config_entries.async_update_entry(self._entry, options=new_options)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if self._attr_options and option not in self._attr_options:
            _LOGGER.warning("Option %s not supported by climate entity %s", option, self._controller.climate_entity)
            return

        # Update the config entry options
        new_options = {**self._entry.options}
        new_options[self._config_key] = option
        
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        
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
        self._attr_unique_id = f"{entry.entry_id}_mode_low_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_mode_high_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_mode_high_humidity"
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
        self._attr_unique_id = f"{entry.entry_id}_fan_low_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_fan_high_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_fan_high_humidity"
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
        self._attr_unique_id = f"{entry.entry_id}_swing_low_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_swing_high_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_swing_high_humidity"
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
        self._attr_unique_id = f"{entry.entry_id}_swing_horizontal_low_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_swing_horizontal_high_temp"
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
        self._attr_unique_id = f"{entry.entry_id}_swing_horizontal_high_humidity"
        config = {**entry.data, **entry.options}
        self._attr_current_option = config.get(CONF_SWING_HORIZONTAL_HIGH_HUMIDITY)
