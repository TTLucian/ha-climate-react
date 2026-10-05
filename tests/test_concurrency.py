"""Concurrency, locking, reload and shutdown behaviour.

The lock hierarchy is documented in the controller but was never exercised.
These tests are the evidence: inspection of a locking scheme is not proof, and
the two worst bugs found during the audit (the dead-band self-disable and the
offline self-disable) both looked correct on inspection.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from tests.conftest import make_entry, setup_controller

MIN = "min_temp_threshold"
MAX = "max_temp_threshold"


async def test_setup_and_shutdown_cleanly_repeatedly(hass: HomeAssistant, climate) -> None:
    """Repeated setup/unload leaves the entry unloadable and re-settable."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    entry.add_to_hass(hass)

    for _ in range(3):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    # Still settable afterwards.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_reload_preserves_enabled_state(hass: HomeAssistant, climate) -> None:
    """A reload must not silently drop or invent an enabled state."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    reloaded = hass.data["climate_react"][entry.entry_id]["coordinator"]
    assert reloaded.enabled is True


async def test_concurrent_temperature_events_are_safe(hass: HomeAssistant, climate) -> None:
    """Many rapid threshold evaluations must not corrupt state or raise."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    async def fire(temp: float) -> None:
        await controller._async_handle_temperature_threshold(temp)

    with patch.object(controller, "_async_safe_service_call", return_value=True):
        await asyncio.wait_for(
            asyncio.gather(*(fire(25.0 + i * 0.01) for i in range(50))),
            timeout=30,
        )
    await hass.async_block_till_done()
    assert controller.enabled is True


async def test_concurrent_option_writes_and_state_changes_do_not_deadlock(hass: HomeAssistant, climate) -> None:
    """Config writes take _config_lock while state changes take _state_lock.

    Both are reachable from the event loop at once, so this exercises the
    documented ordering rather than trusting it.
    """
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()

    async def write(i: int) -> None:
        await controller.async_update_option("fan_high_temp", ["auto", "low", "high"][i % 3])

    async def touch() -> None:
        climate(state="off", current_temperature=25.0 + 0.01)

    with patch.object(controller, "_async_safe_service_call", return_value=True):
        await asyncio.wait_for(
            asyncio.gather(*(write(i) for i in range(10)), *(touch() for _ in range(10))),
            timeout=30,
        )


async def test_concurrent_enable_disable_pairs(hass: HomeAssistant, climate) -> None:
    """Enable/disable races must leave a consistent, persisted state."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)

    with patch.object(controller, "_async_safe_service_call", return_value=True):
        await asyncio.wait_for(asyncio.gather(controller.async_enable(), controller.async_enable()), timeout=30)
        await hass.async_block_till_done()
        assert controller.enabled is True

        await asyncio.wait_for(asyncio.gather(controller.async_disable(), controller.async_disable()), timeout=30)
        await hass.async_block_till_done()

    assert controller.enabled is False
    # And that state is what got persisted.
    assert entry.options.get("enabled") is False


async def test_shutdown_cancels_pending_debounce(hass: HomeAssistant, climate) -> None:
    """Shutdown during a pending debounce must not leave the handle armed."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="off", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    await controller._debounce_temperature_threshold(25.0)
    assert controller._debounce_temp_timer is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert controller._debounce_temp_timer is None


async def test_timer_and_shutdown_race(hass: HomeAssistant, climate) -> None:
    """Unloading while a timer is running must complete rather than hang."""
    entry = make_entry(**{MIN: 22.0, MAX: 24.0})
    climate(state="cool", current_temperature=25.0)
    controller = await setup_controller(hass, entry)
    await controller.async_enable()
    await controller.async_set_timer(60)

    assert await asyncio.wait_for(hass.config_entries.async_unload(entry.entry_id), timeout=30)
    await hass.async_block_till_done()
