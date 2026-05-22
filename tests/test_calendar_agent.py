"""
Tests for runtime.calendar.calendar_agent.

Goals:
  - scan_cycle handles entirely-missing dependency modules gracefully
  - scan_cycle integrates a full set of stubs and produces a valid summary
  - cache short-circuits on second compile_events / get_sun_state calls
  - TODO regeneration is skipped when events are unchanged and cache fresh
  - TODO regeneration runs when events change
  - get_status reports the expected keys
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Reset the singleton between tests so state doesn't leak
from runtime.calendar import calendar_agent as ca_mod
from runtime.calendar.calendar_agent import (
    CalendarAgent,
    DEFAULT_CITIES,
    DEFAULT_WINDOWS,
    TODO_CACHE_MIN_AGE_S,
    get_calendar_agent,
    reset_calendar_agent_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_calendar_agent_for_tests()
    yield
    reset_calendar_agent_for_tests()


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


# ── Helpers to build a fully-stubbed module set ───────────────────────


def _make_stub_modules(event_ids: list[str] | None = None) -> dict[str, Any]:
    """Build a dict of fake dependency modules with the expected interfaces."""
    if event_ids is None:
        event_ids = ["evt-1", "evt-2"]

    events = [{"id": eid, "title": f"Event {eid}", "date": "2026-05-22"} for eid in event_ids]

    # Solar
    solar = MagicMock()

    async def _get_full_solar_state(city_id):
        return {"city_id": city_id, "available": True, "sun_score": 0.7}
    solar.get_full_solar_state = _get_full_solar_state

    async def _snapshot_to_disk(city_id):
        return True
    solar.snapshot_to_disk = _snapshot_to_disk

    # Events compiler
    events_compiler = MagicMock()

    async def _compile_unified_events(city_id, window_days):
        return list(events)
    events_compiler.compile_unified_events = _compile_unified_events

    # Todo generator — record call counts so we can assert cost guard
    todo_gen = MagicMock()
    todo_gen.call_count = 0

    async def _generate_todos_for_window(city_id, window_days, events):
        todo_gen.call_count += 1
        return [{"id": f"todo-{i}", "text": f"Do {i}"} for i in range(len(events))]
    todo_gen.generate_todos_for_window = _generate_todos_for_window

    # Correlator — passes events through with a correlation tag
    correlator = MagicMock()

    async def _attach_correlations(events, moon, sun, city_id, window_days):
        return [{**e, "_correlated": True} for e in events]
    correlator.attach_correlations = _attach_correlations

    # Cities pref
    cities_pref = MagicMock()

    async def _get_default_city():
        return "edmonton"
    cities_pref.get_default_city = _get_default_city

    async def _get_all_active_cities():
        return ["edmonton"]
    cities_pref.get_all_active_cities = _get_all_active_cities

    # Lunar (sync, like the real module)
    lunar = MagicMock()
    lunar.get_moon_phase = MagicMock(return_value={"phase_name": "Waxing Gibbous"})
    lunar.get_cycle_context = MagicMock(return_value={"cycle_half": "waxing"})

    return {
        "solar": solar,
        "events_compiler": events_compiler,
        "todo_generator": todo_gen,
        "correlator": correlator,
        "cities_pref": cities_pref,
        "lunar": lunar,
    }


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_cycle_with_all_modules_missing(tmp_data_dir):
    """Agent must not crash when every dependency module is absent."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    # Force everything missing
    agent._modules = {k: None for k in agent._modules}
    agent._modules_loaded = []

    summary = await agent.scan_cycle()

    assert summary["cities_scanned"] == 1  # falls back to default
    assert summary["cities"] == DEFAULT_CITIES
    assert summary["duration_s"] >= 0
    # All event/todo counts should be zero because no modules can produce them
    for city in summary["cities"]:
        for window in DEFAULT_WINDOWS:
            assert summary["events_per_city"][city][window] == 0
            assert summary["todos_per_city"][city][window] == 0
    # State file was persisted
    assert (tmp_data_dir / "calendar" / "agent_state.json").exists()


@pytest.mark.asyncio
async def test_scan_cycle_with_partial_modules(tmp_data_dir):
    """Only some modules present — others must degrade gracefully."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    # Remove the todo generator and correlator
    agent._modules = {
        "solar": stubs["solar"],
        "events_compiler": stubs["events_compiler"],
        "todo_generator": None,
        "correlator": None,
        "cities_pref": stubs["cities_pref"],
        "lunar": stubs["lunar"],
    }
    agent._modules_loaded = ["solar", "events_compiler", "cities_pref", "lunar"]

    summary = await agent.scan_cycle()

    assert summary["cities_scanned"] == 1
    assert summary["events_per_city"]["edmonton"][7] == 2
    assert summary["events_per_city"]["edmonton"][30] == 2
    # Todos absent because todo_generator is None
    assert summary["todos_per_city"]["edmonton"][7] == 0
    assert summary["todos_per_city"]["edmonton"][30] == 0


@pytest.mark.asyncio
async def test_scan_cycle_with_all_modules(tmp_data_dir):
    """Full happy path — every subsystem present."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    summary = await agent.scan_cycle()

    assert summary["cities_scanned"] == 1
    assert summary["events_per_city"]["edmonton"][7] == 2
    assert summary["todos_per_city"]["edmonton"][7] == 2
    assert summary["cycle_count"] == 1
    assert summary["last_scan_at"] is not None


@pytest.mark.asyncio
async def test_compile_events_cache_hit(tmp_data_dir):
    """Second compile_events call within TTL should not re-invoke the compiler."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    call_count = {"n": 0}
    orig = stubs["events_compiler"].compile_unified_events

    async def _counted(city_id, window_days):
        call_count["n"] += 1
        return await orig(city_id, window_days)
    stubs["events_compiler"].compile_unified_events = _counted

    a = await agent.compile_events("edmonton", 7)
    b = await agent.compile_events("edmonton", 7)
    assert a == b
    assert call_count["n"] == 1  # second call hit cache


@pytest.mark.asyncio
async def test_sun_state_cache_hit(tmp_data_dir):
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    call_count = {"n": 0}

    async def _counted(city_id):
        call_count["n"] += 1
        return {"city_id": city_id, "available": True}
    stubs["solar"].get_full_solar_state = _counted

    a = await agent.get_sun_state("edmonton")
    b = await agent.get_sun_state("edmonton")
    assert a == b
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_todo_regen_skipped_when_events_unchanged(tmp_data_dir):
    """
    Cost guard: a second scan_cycle with the same events and < 30 min
    since the previous run must NOT call the TODO generator.
    """
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    await agent.scan_cycle()
    first_count = stubs["todo_generator"].call_count
    assert first_count >= 2  # one per window (7, 30)

    await agent.scan_cycle()
    second_count = stubs["todo_generator"].call_count
    assert second_count == first_count, (
        f"TODO generator should be skipped on unchanged events; "
        f"calls={second_count}, expected {first_count}"
    )


@pytest.mark.asyncio
async def test_todo_regen_runs_when_events_change(tmp_data_dir):
    """If event ids change between cycles, the TODO generator must rerun."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules(event_ids=["a", "b"])
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    await agent.scan_cycle()
    first_count = stubs["todo_generator"].call_count

    # Swap the compiler to return different events
    new_events = [{"id": "x", "title": "x", "date": "2026-05-22"}]

    async def _new_compile(city_id, window_days):
        return list(new_events)
    stubs["events_compiler"].compile_unified_events = _new_compile

    await agent.scan_cycle()
    second_count = stubs["todo_generator"].call_count
    assert second_count > first_count, "TODO generator should rerun when events change"


@pytest.mark.asyncio
async def test_todo_regen_runs_when_cache_aged(tmp_data_dir):
    """If the cache is older than TODO_CACHE_MIN_AGE_S, regenerate even on unchanged events."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    await agent.scan_cycle()
    first_count = stubs["todo_generator"].call_count

    # Age out the cache by rewriting timestamps
    for key in list(agent._todos_cache.keys()):
        agent._todos_cache[key]["ts"] = time.time() - (TODO_CACHE_MIN_AGE_S + 60)

    await agent.scan_cycle()
    second_count = stubs["todo_generator"].call_count
    assert second_count > first_count


@pytest.mark.asyncio
async def test_get_status_shape(tmp_data_dir):
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    status = await agent.get_status()
    for key in (
        "last_scan_at",
        "cycle_count",
        "errors_since_start",
        "cities_active",
        "modules_loaded",
        "scan_interval_s",
    ):
        assert key in status

    assert "edmonton" in status["cities_active"]
    assert status["cycle_count"] == 0  # no scan_cycle yet


@pytest.mark.asyncio
async def test_run_loop_honors_stop_flag(tmp_data_dir):
    """run() must exit when _stop is set."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()
    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    # Start the loop, signal stop very quickly, ensure it returns
    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.1)
    agent.stop()

    # Cancel to avoid waiting for the full first sleep (5s startup defer)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_singleton_accessor():
    a = get_calendar_agent()
    b = get_calendar_agent()
    assert a is b
    reset_calendar_agent_for_tests()
    c = get_calendar_agent()
    assert c is not a


@pytest.mark.asyncio
async def test_scan_cycle_records_errors(tmp_data_dir):
    """If a module raises, scan_cycle must record it but not crash."""
    agent = CalendarAgent(data_dir=str(tmp_data_dir))
    stubs = _make_stub_modules()

    async def _boom(city_id, window_days):
        raise RuntimeError("compiler exploded")
    stubs["events_compiler"].compile_unified_events = _boom

    agent._modules = stubs
    agent._modules_loaded = list(stubs.keys())

    summary = await agent.scan_cycle()
    # Should have captured an error per (city, window)
    assert len(summary["errors"]) >= 2
    assert agent._errors_since_start >= 2
