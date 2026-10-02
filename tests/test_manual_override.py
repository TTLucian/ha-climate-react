"""Manual override detection.

A manual change to the climate entity must hand control back to the user by
disabling the whole automation. A device self-cycle (compressor dip, attribute
normalisation) must NOT be mistaken for the user, while the automation is
genuinely commanding the unit.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.climate_react.const import (
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MODE_HIGH_TEMP,
    CONF_MODE_LOW_TEMP,
    DOMAIN,
)
from tests.conftest import make_entry, setup_controller


async def _fire_climate_change(hass: HomeAssistant, controller, event_type="state_changed") -> None:
    """Emit a climate state change event through the controller's listener."""
    await controller._async_climate_state_changed(_make_event(hass, controller, event_type))


def _make_event(hass, controller, event_type):
    """Build a minimal Event carrying the climate entity's new state."""
    from homeassistant.core import Event

    return Event(
        event_type,
        {
            "entity_id": controller.climate_entity,
            "new_state": hass.states.get(controller.climate_entity),
            "old_state": None,
        },
    )


async def test_manual_change_in_dead_band_disables_automation(hass: HomeAssistant, climate) -> None:
    """User turns the unit on inside the dead band -> automation switches off."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    assert controller.enabled is True

    # The user switches the unit on while the room is comfortably in range.
    climate(state="cool", current_temperature=23.0, temperature=21.0)
    await _fire_climate_change(hass, controller)

    assert controller.enabled is False
    # The control switch follows the automation.
    control_state = hass.states.get("switch.climate_react_test_ac_control")
    assert control_state is not None
    assert control_state.state == "off"


async def test_manual_change_with_mode_off_band_disables_automation(hass: HomeAssistant, climate) -> None:
    """The cooling-only config must not make manual override unreachable.

    Regression test: with ``mode_low_temp: off`` the room is below the low
    threshold and the band mode is ``off``. Manual override previously treated
    that as "automation is commanding" and re-asserted ``off`` instead of
    handing over control, so the unit could never be used manually.
    """
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, CONF_MODE_LOW_TEMP: "off"})
    climate(state="off", current_temperature=20.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    climate(state="cool", current_temperature=20.0, temperature=21.0)
    await _fire_climate_change(hass, controller)

    assert controller.enabled is False


async def test_device_self_cycle_does_not_disable_automation(hass: HomeAssistant, climate) -> None:
    """A compressor dip while the automation is commanding must not disable it."""
    entry = make_entry(
        **{
            CONF_MIN_TEMP: 22.0,
            CONF_MAX_TEMP: 24.0,
            CONF_MODE_HIGH_TEMP: "cool",
            "fan_high_temp": "auto",
            "swing_high_temp": "off",
            "swing_horizontal_high_temp": "stopped",
            "temp_high_temp": 21.0,
        }
    )
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    # Automation has the unit cooling, exactly as configured.
    climate(
        state="cool",
        current_temperature=25.0,
        temperature=21.0,
        fan_mode="auto",
        swing_mode="off",
        swing_horizontal_mode="stopped",
    )
    assert controller.enabled is True

    # The compressor dips the unit off by itself.
    climate(
        state="off",
        current_temperature=25.0,
        temperature=21.0,
        fan_mode="auto",
        swing_mode="off",
        swing_horizontal_mode="stopped",
    )
    with patch.object(controller, "_async_evaluate_state") as evaluate:
        await _fire_climate_change(hass, controller)

    # Treated as a self-cycle: the automation re-asserts instead of standing down.
    assert controller.enabled is True
    evaluate.assert_called_once()


async def test_rounded_setpoint_is_not_an_override(hass: HomeAssistant, climate) -> None:
    """A unit rounding the setpoint must not be read as a manual change.

    Regression test for an endless re-assert loop: requesting 21.5 on a unit with
    target_temp_step 1 could never be satisfied, so every state change looked
    like a mismatch and triggered another command.
    """
    entry = make_entry(
        **{
            CONF_MIN_TEMP: 22.0,
            CONF_MAX_TEMP: 24.0,
            "fan_high_temp": "auto",
            "swing_high_temp": "off",
            "swing_horizontal_high_temp": "stopped",
            "temp_high_temp": 21.5,
        }
    )
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    # The unit holds 21, not 21.5, and everything else matches.
    climate(
        state="cool",
        current_temperature=25.0,
        temperature=21.0,
        fan_mode="auto",
        swing_mode="off",
        swing_horizontal_mode="stopped",
    )
    await _fire_climate_change(hass, controller)

    assert controller.enabled is True


async def test_target_temp_is_snapped_to_unit_step(hass: HomeAssistant, climate) -> None:
    """A setpoint the unit cannot represent is snapped to one it can."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, "temp_high_temp": 21.5})
    climate(state="off", current_temperature=25.0, target_temp_step=1, min_temp=16, max_temp=30)
    controller = await setup_controller(hass, entry)

    assert controller._clamp_target_temperature(21.5) == 22.0
    assert controller._clamp_target_temperature(21.0) == 21.0


async def test_target_temp_is_clamped_to_unit_range(hass: HomeAssistant, climate) -> None:
    """A setpoint outside the unit's advertised range is clamped."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0, "temp_high_temp": 45.0})
    climate(state="off", current_temperature=25.0, min_temp=16, max_temp=30)
    controller = await setup_controller(hass, entry)

    assert controller._clamp_target_temperature(45.0) == 30.0
    assert controller._clamp_target_temperature(5.0) == 16.0


async def test_logbook_targets_the_real_control_switch(hass: HomeAssistant, climate) -> None:
    """Logbook entries attach to the registered switch, not a guessed entity_id."""
    entry = make_entry(**{CONF_MIN_TEMP: 22.0, CONF_MAX_TEMP: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    resolved = controller._get_switch_entity_id()
    assert resolved is not None
    assert resolved == registry.async_get_entity_id("switch", DOMAIN, "climate_react_test_ac_control")
