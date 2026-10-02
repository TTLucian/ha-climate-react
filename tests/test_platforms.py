"""Entity platform behaviour: switch, numbers, selects."""

from __future__ import annotations


from homeassistant.core import HomeAssistant

from tests.conftest import make_entry, setup_controller


async def test_switch_reflects_manual_override(hass: HomeAssistant, climate) -> None:
    """The control switch must follow the automation when it disables itself."""
    entry = make_entry(**{"min_temp_threshold": 22.0, "max_temp_threshold": 24.0})
    climate(state="off", current_temperature=23.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    await hass.async_block_till_done()

    sw = "switch.climate_react_test_ac_control"
    sw_state = hass.states.get(sw)
    assert sw_state is not None
    assert sw_state.state == "on"

    climate(state="cool", current_temperature=23.0, temperature=21.0)
    await controller._async_climate_state_changed(
        __import__("homeassistant.core", fromlist=["Event"]).Event(
            "state_changed",
            {
                "entity_id": controller.climate_entity,
                "new_state": hass.states.get(controller.climate_entity),
                "old_state": None,
            },
        )
    )
    await hass.async_block_till_done()
    sw_state = hass.states.get(sw)
    assert sw_state is not None
    assert sw_state.state == "off"


async def test_switch_attributes_have_defaults(hass: HomeAssistant, climate) -> None:
    """Switch attributes must never expose None for the thresholds."""
    entry = make_entry(**{"min_temp_threshold": 22.0, "max_temp_threshold": 24.0})
    climate(state="off", current_temperature=23.0)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    state = hass.states.get("switch.climate_react_test_ac_control")
    assert state is not None
    assert state.attributes["min_temp"] == 22.0
    assert state.attributes["max_temp"] == 24.0
    assert "current_temperature" in state.attributes


async def test_number_entities_reflect_config(hass: HomeAssistant, climate) -> None:
    """Number entities read live config, not a stale snapshot."""
    entry = make_entry(**{"min_temp_threshold": 22.0, "max_temp_threshold": 24.0})
    climate(state="off", current_temperature=23.0)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    min_state = hass.states.get("number.climate_react_test_ac_minimum_temperature")
    max_state = hass.states.get("number.climate_react_test_ac_maximum_temperature")
    assert min_state is not None
    assert max_state is not None
    assert min_state.state == "22.0"
    assert max_state.state == "24.0"


async def test_select_rejects_unsupported_option(hass: HomeAssistant, climate) -> None:
    """A select exposes only the options the unit actually supports."""
    entry = make_entry(**{"min_temp_threshold": 22.0, "max_temp_threshold": 24.0})
    climate(state="off", current_temperature=23.0, fan_modes=["auto", "low"])
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    sel = "select.climate_react_test_ac_fan_high_temperature"
    state = hass.states.get(sel)
    assert state is not None
    assert set(state.attributes["options"]) == {"auto", "low"}

    # An unsupported option is refused rather than silently accepted.
    from homeassistant.exceptions import ServiceValidationError

    try:
        await hass.services.async_call("select", "select_option", {"entity_id": sel, "option": "turbo"}, blocking=True)
    except ServiceValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unsupported option was accepted")
    assert state is not None
    assert state.state != "turbo"


async def test_timer_number_roundtrip(hass: HomeAssistant, climate) -> None:
    """Setting the timer entity updates the controller."""
    entry = make_entry(**{"min_temp_threshold": 22.0, "max_temp_threshold": 24.0})
    climate(state="cool", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    await hass.async_block_till_done()

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.climate_react_test_ac_timer", "value": 30},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert controller.timer_minutes > 0
