"""The mode allowlists are a deliberate guard, not a hardware limitation.

Cooling a cold room, or heating a hot one, is a configuration mistake. The
selects therefore offer only modes that make sense for their band, even when
the unit supports more. These tests exist so the allowlist is not mistaken for a
bug and "fixed" by exposing the unit's full mode list.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from tests.conftest import make_entry, setup_controller

MIN = "min_temp_threshold"
MAX = "max_temp_threshold"

FULL_HVAC_MODES = ["off", "cool", "heat", "fan_only", "dry", "heat_cool"]


async def test_low_band_offers_only_sensible_modes(hass: HomeAssistant, climate) -> None:
    """Below the low threshold: heat, fan_only, off, none."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, hvac_modes=FULL_HVAC_MODES)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    options = hass.states.get("select.climate_react_test_ac_mode_low_temperature").attributes["options"]
    assert set(options) == {"heat", "fan_only", "off", "none"}
    # Modes that make no sense when cold are withheld, though supported.
    for nonsensical in ("cool", "dry", "heat_cool"):
        assert nonsensical not in options


async def test_high_band_offers_only_sensible_modes(hass: HomeAssistant, climate) -> None:
    """Above the high threshold: cool, fan_only, off, none."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, hvac_modes=FULL_HVAC_MODES)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    options = hass.states.get("select.climate_react_test_ac_mode_high_temperature").attributes["options"]
    assert set(options) == {"cool", "fan_only", "off", "none"}
    for nonsensical in ("heat", "dry", "heat_cool"):
        assert nonsensical not in options


async def test_allowlist_still_respects_hardware_capability(hass: HomeAssistant, climate) -> None:
    """The allowlist narrows hardware support; it never widens it.

    A unit without fan_only must not be offered it even though the allowlist
    permits it.
    """
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, hvac_modes=["off", "cool", "heat"])
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    options = hass.states.get("select.climate_react_test_ac_mode_low_temperature").attributes["options"]
    assert set(options) == {"heat", "off", "none"}
    assert "fan_only" not in options


async def test_heat_cannot_be_selected_for_the_high_band(hass: HomeAssistant, climate) -> None:
    """Selecting heat for a hot room is refused."""
    from homeassistant.exceptions import ServiceValidationError

    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=23.0, hvac_modes=FULL_HVAC_MODES)
    await setup_controller(hass, entry)
    await hass.async_block_till_done()

    sel = "select.climate_react_test_ac_mode_high_temperature"
    try:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": sel, "option": "heat"}, blocking=True
        )
    except ServiceValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("heat was accepted for the high band")
    assert hass.states.get(sel).state != "heat"
