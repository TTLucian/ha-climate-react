"""Temperature number entities take their range from the climate entity.

A unit cannot cool below its own min_temp or heat above its max_temp, so
offering a room threshold or a target outside that range offers a setting the
hardware cannot honour.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from tests.conftest import make_entry, setup_controller

MIN = "min_temp_threshold"
MAX = "max_temp_threshold"

TEMPERATURE_NUMBERS = [
    "number.climate_react_test_ac_minimum_temperature",
    "number.climate_react_test_ac_maximum_temperature",
    "number.climate_react_test_ac_target_temperature_low",
    "number.climate_react_test_ac_target_temperature_high",
]


async def test_temperature_numbers_follow_climate_range(hass: HomeAssistant, climate) -> None:
    """Bounds come from the unit's advertised setpoint limits."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, min_temp=16, max_temp=30)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    for entity_id in TEMPERATURE_NUMBERS:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["min"] == 16, entity_id
        assert state.attributes["max"] == 30, entity_id


async def test_narrow_unit_range_is_reflected(hass: HomeAssistant, climate) -> None:
    """A unit with a narrower range than 0-40 is honoured."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, min_temp=18, max_temp=26)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    for entity_id in TEMPERATURE_NUMBERS:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["min"] == 18, entity_id
        assert state.attributes["max"] == 26, entity_id


async def test_non_temperature_numbers_unchanged(hass: HomeAssistant, climate) -> None:
    """Delay, min run time and timer keep their own fixed bounds."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, min_temp=16, max_temp=30)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    delay = hass.states.get("number.climate_react_test_ac_delay_between_commands_ms")
    assert delay is not None
    assert delay.attributes["min"] == 0
    assert delay.attributes["max"] == 5000

    run_time = hass.states.get("number.climate_react_test_ac_minimum_run_time_minutes")
    assert run_time is not None
    assert run_time.attributes["min"] == 0
    assert run_time.attributes["max"] == 120


async def test_bounds_fall_back_while_unit_offline(hass: HomeAssistant, climate) -> None:
    """An offline unit must still leave the numbers with usable bounds."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, min_temp=16, max_temp=30)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    hass.states.async_set("climate.test_ac", "unavailable")
    await hass.async_block_till_done()

    for entity_id in TEMPERATURE_NUMBERS:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        low = state.attributes.get("min")
        high = state.attributes.get("max")
        assert isinstance(low, (int, float)), entity_id
        assert isinstance(high, (int, float)), entity_id
        assert low < high, entity_id


async def test_bounds_track_a_range_change(hass: HomeAssistant, climate) -> None:
    """A unit reporting a different range later updates the entity."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, min_temp=16, max_temp=30)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    entity_id = "number.climate_react_test_ac_minimum_temperature"
    before = hass.states.get(entity_id)
    assert before is not None
    assert before.attributes["max"] == 30

    climate(state="off", current_temperature=23.0, min_temp=20, max_temp=25)
    await hass.async_block_till_done()

    after = hass.states.get(entity_id)
    assert after is not None
    assert after.attributes["max"] == 25
