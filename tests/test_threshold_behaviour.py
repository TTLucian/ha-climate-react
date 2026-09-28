"""Tests pinning the two-threshold behaviour:

* above max_temp  -> apply the high-temperature commands
* below min_temp  -> apply the low-temperature commands
* in between      -> do nothing at all
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.climate_react.const import CONF_MAX_TEMP, CONF_MIN_TEMP, CONF_MODE_LOW_TEMP
from tests.conftest import make_entry, setup_controller


async def test_above_max_applies_high_commands(hass: HomeAssistant, climate) -> None:
    """Temperature above the high threshold applies the high band commands."""
    entry = make_entry(
        **{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, "fan_high_temp": "low", "swing_high_temp": "fixedtop"}
    )
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(25.0)

    services = [(c.args[0], c.args[1], c.args[2].get("hvac_mode")) for c in call.call_args_list]
    assert ("climate", "turn_on", None) in services
    assert ("climate", "set_hvac_mode", "cool") in services


async def test_below_min_applies_low_commands(hass: HomeAssistant, climate) -> None:
    """Temperature below the low threshold applies the low band commands."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, "fan_low_temp": "high"})
    climate(state="off", current_temperature=21.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(21.0)

    services = [(c.args[0], c.args[1], c.args[2].get("hvac_mode")) for c in call.call_args_list]
    assert ("climate", "set_hvac_mode", "heat") in services


async def test_inside_band_does_nothing(hass: HomeAssistant, climate) -> None:
    """Between the thresholds the integration takes no action whatsoever."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0})
    climate(state="cool", current_temperature=23.0, temperature=21.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call") as call:
        await controller._async_handle_temperature_threshold(23.0)

    call.assert_not_called()


async def test_inside_band_does_not_turn_the_unit_off(hass: HomeAssistant, climate) -> None:
    """Coming back into the dead band must not switch the unit off.

    The unit's own thermostat governs inside the band; turning it off here would
    also discard the setpoint the user configured.
    """
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0})
    climate(state="cool", current_temperature=23.5, temperature=21.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(23.5)

    turn_offs = [c for c in call.call_args_list if c.args[1] in ("turn_off", "set_hvac_mode")]
    assert turn_offs == []


async def test_mode_none_in_band_is_inert(hass: HomeAssistant, climate) -> None:
    """A band configured to ``none`` never commands anything."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, CONF_MODE_LOW_TEMP: "none"})
    climate(state="heat", current_temperature=20.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call") as call:
        await controller._async_handle_temperature_threshold(20.0)

    call.assert_not_called()


async def test_mode_off_in_band_turns_unit_off(hass: HomeAssistant, climate) -> None:
    """A band configured to ``off`` commands the unit off (a cooling-only setup).

    ``off`` is a real command, not a no-op: below the low threshold the room is
    cool enough, so the automation stops the unit. Only ``none`` means "do
    nothing at all".
    """
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, CONF_MODE_LOW_TEMP: "off"})
    climate(state="cool", current_temperature=20.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(20.0)

    services = [(c.args[0], c.args[1], c.args[2].get("hvac_mode")) for c in call.call_args_list]
    assert ("climate", "turn_off", None) in services
    assert ("climate", "set_hvac_mode", "off") in services


async def test_evaluation_is_stateless_across_repeat_calls(hass: HomeAssistant, climate) -> None:
    """The same band is re-applied on a later evaluation if it is not satisfied.

    Regression test for the removed ``_last_threshold_state`` latch, which
    suppressed every later attempt once a band had been seen.
    """
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(25.0)
        first = call.call_count
        assert first > 0
        # The unit still reports 'off' (the mock does not change state), so a
        # second evaluation must act again rather than be skipped as a duplicate.
        await controller._async_handle_temperature_threshold(25.0)

    assert call.call_count > first


async def test_no_command_when_already_satisfying_config(hass: HomeAssistant, climate) -> None:
    """If the unit already matches the band's command, nothing is re-sent."""
    entry = make_entry(
        **{
            CONF_MIN_TEMP: 22.0,
            CONF_MAX_TEMP: 24.0,
            "fan_high_temp": "auto",
            "swing_high_temp": "off",
            "swing_horizontal_high_temp": "stopped",
            "temp_high_temp": 21.0,
        }
    )
    climate(
        state="cool",
        current_temperature=25.0,
        temperature=21.0,
        fan_mode="auto",
        swing_mode="off",
        swing_horizontal_mode="stopped",
    )
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call") as call:
        await controller._async_handle_temperature_threshold(25.0)

    call.assert_not_called()
