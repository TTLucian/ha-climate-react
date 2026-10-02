"""Adversarial probes for cases the new logic may have broken."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import Event, HomeAssistant

from tests.conftest import make_entry, setup_controller


def _event(hass, controller):
    return Event(
        "state_changed",
        {
            "entity_id": controller.climate_entity,
            "new_state": hass.states.get(controller.climate_entity),
            "old_state": None,
        },
    )


async def test_unit_finishing_its_cycle_in_dead_band(hass: HomeAssistant, climate) -> None:
    """The unit reaching its setpoint must NOT be read as a manual change.

    Scenario: automation starts cooling at 23.3, the room falls into the dead
    band, the unit then stops itself because it reached the setpoint. That stop
    is the device doing its job, not the user intervening.
    """
    entry = make_entry(**{"min_temp_threshold": 22.0, "max_temp_threshold": 24.0, "temp_high_temp": 21.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    # Automation starts the unit.
    with patch.object(controller, "_async_safe_service_call", return_value=True):
        await controller._async_handle_temperature_threshold(25.0)
    assert controller._last_set_hvac_mode == "cool"

    # Room falls into the dead band; the unit keeps cooling then stops itself.
    climate(state="off", current_temperature=23.0, temperature=21.0)
    with patch.object(controller, "_async_evaluate_state"):
        await controller._async_climate_state_changed(_event(hass, controller))

    assert controller.enabled is True, "unit finishing its own cycle disabled the automation"
