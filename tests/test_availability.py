"""Offline / unavailable entity handling.

A missing or unavailable unit must never be treated as 'off' (which would make
the automation skip a command it owes) nor as 'available' (which would send
service calls into the void). Commands are held until the entity returns.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import Event, HomeAssistant

from tests.conftest import make_entry, setup_controller

MIN = "min_temp_threshold"
MAX = "max_temp_threshold"


def _event(controller, new_state):
    return Event(
        "state_changed",
        {"entity_id": controller.climate_entity, "new_state": new_state, "old_state": None},
    )


async def _notify(hass, controller, new_state):
    await controller._async_climate_state_changed(_event(controller, new_state))
    await hass.async_block_till_done()


async def test_unavailable_entity_is_not_reported_off(hass: HomeAssistant, climate) -> None:
    """An unavailable unit must not be reported as off."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)

    assert controller._is_climate_off() is True
    hass.states.async_set(controller.climate_entity, "unavailable")
    assert controller._is_entity_available() is False
    assert controller._is_climate_off() is False, "unavailable must not read as off"


async def test_missing_entity_is_not_reported_off(hass: HomeAssistant, climate) -> None:
    """A missing entity must not be reported as off either."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)

    hass.states.async_set(controller.climate_entity, "unavailable")
    hass.states.async_remove(controller.climate_entity)
    assert controller._is_entity_available() is False
    assert controller._is_climate_off() is False


async def test_no_command_while_unavailable(hass: HomeAssistant, climate) -> None:
    """No service calls are sent while the unit is offline."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    hass.states.async_set(controller.climate_entity, "unavailable")
    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller._async_handle_temperature_threshold(25.0)
    call.assert_not_called()


async def test_command_issued_once_unit_returns(hass: HomeAssistant, climate) -> None:
    """The threshold that came due during the outage is applied on return."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    # Unit drops off the network while a threshold is outstanding.
    offline = hass.states.get(controller.climate_entity)
    hass.states.async_set(controller.climate_entity, "unavailable")
    await _notify(hass, controller, hass.states.get(controller.climate_entity))

    # It comes back, still above the threshold.
    climate(state="off", current_temperature=25.0)
    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await _notify(hass, controller, hass.states.get(controller.climate_entity))
        services = [c.args[1] for c in call.call_args_list]

    assert "turn_on" in services or "set_hvac_mode" in services
    assert offline is not None


async def test_offline_does_not_disable_automation(hass: HomeAssistant, climate) -> None:
    """An outage must not be mistaken for a manual change."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    hass.states.async_set(controller.climate_entity, "unavailable")
    await _notify(hass, controller, hass.states.get(controller.climate_entity))
    assert controller.enabled is True


async def test_capability_cache_not_poisoned_by_outage(hass: HomeAssistant, climate) -> None:
    """An offline unit must not cache an empty capability set.

    Caching it would make every capability check fail for the whole cache
    duration, long after the unit returned.
    """
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)

    # Offline: validation must decline, and must not be cached.
    hass.states.async_set(controller.climate_entity, "unavailable")
    assert controller._validate_climate_capability("fan_modes", "auto") is False
    assert controller._validated_capabilities == {}, "offline capabilities were cached"

    # Back online: validation works again.
    climate(state="off", current_temperature=25.0, fan_modes=["auto", "low"])
    assert controller._validate_climate_capability("fan_modes", "auto") is True


async def test_capability_cache_cleared_on_transition(hass: HomeAssistant, climate) -> None:
    """Going offline and back clears cached capabilities."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0, fan_modes=["auto"])
    controller = await setup_controller(hass, entry)
    controller._validate_climate_capability("fan_modes", "auto")
    assert controller._validated_capabilities

    hass.states.async_set(controller.climate_entity, "unavailable")
    await _notify(hass, controller, hass.states.get(controller.climate_entity))
    assert controller._validated_capabilities == {}


async def test_timer_kept_while_unit_offline(hass: HomeAssistant, climate) -> None:
    """A timer set during an outage is kept, not silently discarded."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="cool", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    # Automation disabled so the "disabled and off -> drop timer" rule applies.
    controller._enabled = False

    hass.states.async_set(controller.climate_entity, "unavailable")
    await controller.async_set_timer(30)
    assert controller.timer_minutes > 0, "timer was discarded while the unit was offline"


async def test_timer_still_dropped_when_automation_off_and_unit_off(hass: HomeAssistant, climate) -> None:
    """The genuine no-op case is unchanged."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    controller._enabled = False

    await controller.async_set_timer(30)
    assert controller.timer_minutes == 0


async def test_disable_does_not_command_offline_unit(hass: HomeAssistant, climate) -> None:
    """Disabling while offline does not send a command to a missing unit."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="cool", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    hass.states.async_set(controller.climate_entity, "unavailable")
    with patch.object(controller, "_async_safe_service_call", return_value=True) as call:
        await controller.async_disable()
    call.assert_not_called()
    assert controller.enabled is False
