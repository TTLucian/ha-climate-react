"""Shared fixtures for Climate React tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_react.const import (
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    DOMAIN,
)

CLIMATE_ENTITY = "climate.test_ac"
EXTERNAL_SENSOR = "sensor.test_room"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components for every test."""
    return


def make_entry(**options) -> MockConfigEntry:
    """Build a config entry with sensible defaults for the tested behaviour."""
    defaults = {
        CONF_MIN_TEMP: 22.0,
        CONF_MAX_TEMP: 24.0,
        CONF_MODE_LOW_TEMP: "heat",
        CONF_MODE_HIGH_TEMP: "cool",
        "enabled": False,
    }
    defaults.update(options)
    return MockConfigEntry(
        domain=DOMAIN,
        data={"climate_entity": CLIMATE_ENTITY},
        options=defaults,
        title="Climate React Test",
    )


async def setup_controller(hass: HomeAssistant, entry: MockConfigEntry):
    """Set up the integration and return the controller."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]["coordinator"]


def set_climate(
    hass: HomeAssistant,
    state: str = "off",
    current_temperature: float | None = 23.0,
    temperature: float | None = None,
    **attributes,
) -> None:
    """Publish a climate entity state."""
    attrs = {
        "hvac_modes": ["off", "cool", "heat", "fan_only"],
        "fan_modes": ["auto", "low", "high"],
        "swing_modes": ["off", "fixedtop"],
        "swing_horizontal_modes": ["stopped", "fixedcenter"],
        "min_temp": 16,
        "max_temp": 30,
        "target_temp_step": 1,
        "current_temperature": current_temperature,
        "temperature": temperature,
    }
    attrs.update(attributes)
    hass.states.async_set(CLIMATE_ENTITY, state, attrs)


@pytest.fixture
def climate(hass: HomeAssistant):
    """Return a helper for publishing climate states."""
    return lambda **kwargs: set_climate(hass, **kwargs)
