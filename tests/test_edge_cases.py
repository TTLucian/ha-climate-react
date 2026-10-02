"""Edge cases across the whole controller."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import Event, HomeAssistant

from tests.conftest import make_entry, setup_controller

MIN = "min_temp_threshold"
MAX = "max_temp_threshold"


def _event(hass, controller):
    return Event(
        "state_changed",
        {
            "entity_id": controller.climate_entity,
            "new_state": hass.states.get(controller.climate_entity),
            "old_state": None,
        },
    )


async def test_unavailable_climate_does_not_disable(hass: HomeAssistant, climate) -> None:
    """A temporarily unavailable unit must not be read as a manual change."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    await controller._async_climate_state_changed(
        Event("state_changed", {"entity_id": controller.climate_entity, "new_state": None, "old_state": None})
    )
    assert controller.enabled is True


async def test_missing_sensor_does_not_disable(hass: HomeAssistant, climate) -> None:
    """No usable temperature reading must not disable the automation."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=None)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    await controller._async_climate_state_changed(_event(hass, controller))
    assert controller.enabled is True


async def test_unavailable_temperature_does_not_disable(hass: HomeAssistant, climate) -> None:
    """An 'unavailable' climate entity must not disable the automation."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    hass.states.async_set(controller.climate_entity, "unavailable")
    await controller._async_climate_state_changed(_event(hass, controller))
    assert controller.enabled is True


async def test_fan_change_by_user_disables(hass: HomeAssistant, climate) -> None:
    """A user changing the fan mode in the dead band is a genuine override."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0, "temp_high_temp": 21.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    climate(state="cool", current_temperature=23.0, temperature=21.0, fan_mode="low")
    await controller._async_climate_state_changed(_event(hass, controller))
    assert controller.enabled is False


async def test_min_run_time_blocks_switch_while_running(hass: HomeAssistant, climate) -> None:
    """Minimum run time defers a mode change while the unit is running."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0, "min_run_time_minutes": 10})
    climate(state="cool", current_temperature=25.0, temperature=21.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    # Pretend a mode change just happened.
    controller._last_mode_change_time = __import__("datetime").datetime.now(__import__("datetime").UTC) - __import__(
        "datetime"
    ).timedelta(minutes=1)

    with patch.object(controller, "_async_safe_service_call") as call:
        await controller._async_handle_temperature_threshold(25.0)
    call.assert_not_called()


async def test_min_run_time_does_not_block_starting_an_off_unit(hass: HomeAssistant, climate) -> None:
    """An off unit must start immediately, regardless of min run time."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0, "min_run_time_minutes": 60})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    controller._last_mode_change_time = __import__("datetime").datetime.now(__import__("datetime").UTC) - __import__(
        "datetime"
    ).timedelta(seconds=10)

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(25.0)
    assert call.call_count > 0


async def test_min_run_time_does_not_block_turning_off(hass: HomeAssistant, climate) -> None:
    """A move to 'off' must never be blocked by min run time."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0, "min_run_time_minutes": 60, "mode_low_temp": "off"})
    climate(state="cool", current_temperature=20.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    controller._last_mode_change_time = __import__("datetime").datetime.now(__import__("datetime").UTC) - __import__(
        "datetime"
    ).timedelta(seconds=10)

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(20.0)
    services = [c.args[1] for c in call.call_args_list]
    assert "turn_off" in services or "set_hvac_mode" in services


async def test_ui_threshold_change_takes_effect_immediately(hass: HomeAssistant, climate) -> None:
    """Raising min_temp above the current reading must act without waiting.

    Regression test for the removed latch: a UI change previously left the
    automation believing it had already handled this band.
    """
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=22.5)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True):
        # 22.5 is above min 22.0 -> nothing happens yet.
        await controller._async_handle_temperature_threshold(22.5)

    # The user raises the low threshold above the current reading.
    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller.async_update_option(MIN, 23.0)
        await hass.async_block_till_done()

    assert call.call_count > 0, "raising the threshold did not re-evaluate"


async def test_mode_change_from_none_takes_effect(hass: HomeAssistant, climate) -> None:
    """Switching a band from 'none' to a real mode must start working.

    Regression test for the latch being committed before the mode check.
    """
    entry = make_entry(**{MIN: 22.0, MAX: 24.0, "mode_low_temp": "none"})
    climate(state="off", current_temperature=20.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(20.0)
    call.assert_not_called()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller.async_update_option("mode_low_temp", "heat")
        await hass.async_block_till_done()

    services = [(c.args[1], c.args[2].get("hvac_mode")) for c in call.call_args_list]
    assert ("set_hvac_mode", "heat") in services


async def test_external_sensor_is_used_when_configured(hass: HomeAssistant, climate) -> None:
    """A configured external sensor is the temperature source."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={
            "climate_entity": "climate.test_ac",
            "use_external_temp_sensor": True,
            "temperature_sensor": "sensor.test_room",
        },
    )
    climate(state="off", current_temperature=30.0)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controller = hass.data["climate_react"][entry.entry_id]["coordinator"]
    hass.states.async_set("sensor.test_room", "25.0")

    assert controller.temperature_sensor == "sensor.test_room"
    assert controller._read_temperature(hass.states.get("sensor.test_room")) == 25.0


async def test_climate_attribute_is_read_for_climate_source(hass: HomeAssistant, climate) -> None:
    """With no external sensor the climate entity's own reading is used."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=22.7)
    controller = await setup_controller(hass, entry)

    assert controller.temperature_sensor == "climate.test_ac"
    # Must read the attribute, never float("off").
    assert controller._read_temperature(hass.states.get("climate.test_ac")) == 22.7


async def test_external_flag_without_sensor_falls_back_safely(hass: HomeAssistant, climate) -> None:
    """Flag set but no sensor chosen must not raise or disable anything.

    Regression test: the old code took the 'else' branch and parsed "off".
    """
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={"climate_entity": "climate.test_ac", "use_external_temp_sensor": True},
    )
    climate(state="off", current_temperature=22.7)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controller = hass.data["climate_react"][entry.entry_id]["coordinator"]
    await controller.async_enable()

    # Falls back to the climate entity and reads its attribute, never float("off").
    assert controller.temperature_sensor == "climate.test_ac"
    assert controller._read_temperature(hass.states.get("climate.test_ac")) == 22.7

    # An ordinary attribute update from the unit must not disable anything.
    climate(state="off", current_temperature=22.7, temperature=21.0, fan_mode="low")
    await controller._async_climate_state_changed(_event(hass, controller))
    assert controller.enabled is True

    # The threshold handler runs without raising on the fallback path.
    with patch.object(controller, "_async_safe_service_call", return_value=True):
        await controller._async_handle_temperature_threshold(22.7)


async def test_timer_survives_restart(hass: HomeAssistant, climate) -> None:
    """A timer set before unload is restored on the next setup."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    await controller.async_set_timer(30)
    assert controller.timer_minutes > 0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    controller2 = hass.data["climate_react"][entry.entry_id]["coordinator"]
    assert controller2.timer_minutes > 0


async def test_min_temp_above_max_temp_is_reported(hass: HomeAssistant, climate) -> None:
    """Inverted thresholds are still handled without raising."""
    entry = make_entry(**{MIN: 26.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(25.0)
    # 25 is below min 26 -> low band commands applied.
    assert call.call_count > 0
