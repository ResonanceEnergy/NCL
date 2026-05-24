"""
Tests for the v2 calendar endpoints added for the iOS Calendar tab rebuild.

Covers:
- /calendar/sun
- /calendar/events/compiled
- /calendar/todos
- /calendar/dashboard
- /calendar/city/select (POST)
- /calendar/city/current
- /calendar/refresh (POST)

We mock `get_calendar_agent()` and the `cities_pref` module via sys.modules
injection so the test does not depend on those swarm-sibling modules existing.

Run:
    pytest tests/test_calendar_routes_new.py -v
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.calendar import calendar_routes as cr_module
from runtime.calendar.calendar_routes import calendar_router


VALID_TOKEN = "calendar-test-token-001"


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(calendar_router)
    return a


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_header():
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


@pytest.fixture(autouse=True)
def patch_strike_token(monkeypatch):
    """Bypass the runtime.api.routes import path for STRIKE_TOKEN."""
    monkeypatch.setattr(cr_module, "_get_strike_token", lambda: VALID_TOKEN)
    yield


@pytest.fixture
def mock_agent(monkeypatch):
    """Patch the lazy calendar_agent loader to return a controllable mock."""
    agent = MagicMock()
    agent.get_sun_state = AsyncMock(
        return_value={
            "sun_times": {"sunrise": "2026-05-21T05:30:00Z", "sunset": "2026-05-21T21:45:00Z"},
            "space_weather": {"kp": 3.0},
            "sunspot": {"number": 120},
            "aurora": {"visible": False},
            "cme_alerts": [],
            "schumann": {"hz": 7.83},
            "seasonal_marker": "late_spring",
            "solar_energy_mode": "active",
            "fetched_at": "2026-05-21T12:00:00Z",
        }
    )
    agent.get_compiled_events = AsyncMock(
        side_effect=lambda city_id, window: {
            "events": [{"id": f"e1-{window}", "title": f"event-{window}d"}],
            "correlations": [{"left": "e1", "right": "e2"}],
            "count": 1,
            "generated_at": "2026-05-21T12:00:00Z",
            "stale": False,
        }
    )
    agent.get_todos = AsyncMock(
        side_effect=lambda city_id, window: {
            "todos": [{"id": f"t1-{window}", "action": f"do something ({window}d)"}],
            "count": 1,
            "generated_at": "2026-05-21T12:00:00Z",
            "stale": False,
        }
    )
    agent.scan_cycle = AsyncMock(
        return_value={"status": "ok", "scanned": 42, "ts": "2026-05-21T12:00:00Z"}
    )
    agent.get_status = MagicMock(
        return_value={"available": True, "last_scan": "2026-05-21T11:50:00Z"}
    )

    monkeypatch.setattr(cr_module, "_get_calendar_agent_or_none", lambda: agent)
    return agent


@pytest.fixture
def mock_agent_missing(monkeypatch):
    """Simulate calendar_agent module not yet built."""
    monkeypatch.setattr(cr_module, "_get_calendar_agent_or_none", lambda: None)


@pytest.fixture
def mock_cities_pref(monkeypatch):
    """Inject a fake cities_pref module via the loader patch."""
    fake = types.SimpleNamespace()
    fake._city = "edmonton"

    def set_preferred_city(city_id):
        fake._city = city_id
        return True

    def get_default_city():
        return fake._city

    def get_city_meta(city_id):
        return {"id": city_id, "name": city_id.title(), "country": "TestLand"}

    fake.set_preferred_city = set_preferred_city
    fake.get_default_city = get_default_city
    fake.get_city_meta = get_city_meta

    monkeypatch.setattr(cr_module, "_get_cities_pref_or_none", lambda: fake)
    return fake


@pytest.fixture
def mock_cities_pref_missing(monkeypatch):
    monkeypatch.setattr(cr_module, "_get_cities_pref_or_none", lambda: None)


# ── /calendar/sun ─────────────────────────────────────────────────────────


def test_sun_returns_documented_schema(client, mock_agent, auth_header):
    r = client.get("/calendar/sun?city_id=edmonton", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    for key in (
        "sun_times",
        "space_weather",
        "sunspot",
        "aurora",
        "cme_alerts",
        "schumann",
        "seasonal_marker",
        "solar_energy_mode",
        "fetched_at",
    ):
        assert key in body, f"missing field {key}"
    mock_agent.get_sun_state.assert_awaited_once_with("edmonton")


def test_sun_requires_auth(client, mock_agent):
    r = client.get("/calendar/sun")
    assert r.status_code == 401


def test_sun_wrong_token_is_403(client, mock_agent):
    r = client.get("/calendar/sun", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403


def test_sun_returns_503_when_agent_missing(client, mock_agent_missing, auth_header):
    r = client.get("/calendar/sun", headers=auth_header)
    assert r.status_code == 503
    assert "error" in r.json()


def test_sun_handles_internal_exception(client, monkeypatch, auth_header):
    agent = MagicMock()
    agent.get_sun_state = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(cr_module, "_get_calendar_agent_or_none", lambda: agent)
    r = client.get("/calendar/sun", headers=auth_header)
    assert r.status_code == 500
    assert "sun fetch failed" in r.json()["error"]


# ── /calendar/events/compiled ────────────────────────────────────────────


def test_events_compiled_window_7(client, mock_agent, auth_header):
    r = client.get("/calendar/events/compiled?city_id=edmonton&window=7", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["city_id"] == "edmonton"
    assert body["window_days"] == 7
    assert isinstance(body["events"], list)
    assert isinstance(body["correlations"], list)
    assert body["count"] == 1
    assert "generated_at" in body
    assert body["stale"] is False


def test_events_compiled_window_30(client, mock_agent, auth_header):
    r = client.get("/calendar/events/compiled?window=30", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["window_days"] == 30


def test_events_compiled_invalid_window_400(client, mock_agent, auth_header):
    r = client.get("/calendar/events/compiled?window=14", headers=auth_header)
    assert r.status_code == 400


def test_events_compiled_requires_auth(client, mock_agent):
    r = client.get("/calendar/events/compiled")
    assert r.status_code == 401


def test_events_compiled_503_when_agent_missing(client, mock_agent_missing, auth_header):
    r = client.get("/calendar/events/compiled", headers=auth_header)
    assert r.status_code == 503


# ── /calendar/todos ──────────────────────────────────────────────────────


def test_todos_window_7(client, mock_agent, auth_header):
    r = client.get("/calendar/todos?window=7", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["window_days"] == 7
    assert isinstance(body["todos"], list)
    assert body["count"] == 1
    assert "generated_at" in body
    assert body["stale"] is False


def test_todos_window_30(client, mock_agent, auth_header):
    r = client.get("/calendar/todos?window=30", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["window_days"] == 30


def test_todos_invalid_window_400(client, mock_agent, auth_header):
    r = client.get("/calendar/todos?window=999", headers=auth_header)
    assert r.status_code == 400


def test_todos_requires_auth(client, mock_agent):
    r = client.get("/calendar/todos")
    assert r.status_code == 401


# ── /calendar/dashboard ──────────────────────────────────────────────────


def test_dashboard_returns_full_payload(client, mock_agent, mock_cities_pref, auth_header):
    r = client.get("/calendar/dashboard?city_id=edmonton", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    for key in (
        "city",
        "moon",
        "sun",
        "events_7d",
        "events_30d",
        "todos_7d",
        "todos_30d",
        "agent_status",
        "generated_at",
    ):
        assert key in body, f"missing field {key}"
    assert body["city"]["id"] == "edmonton"
    assert "events" in body["events_7d"] and "count" in body["events_7d"]
    assert "events" in body["events_30d"] and "count" in body["events_30d"]
    assert "todos" in body["todos_7d"] and "count" in body["todos_7d"]
    assert "todos" in body["todos_30d"] and "count" in body["todos_30d"]


def test_dashboard_requires_auth(client, mock_agent, mock_cities_pref):
    r = client.get("/calendar/dashboard")
    assert r.status_code == 401


def test_dashboard_degrades_when_agent_missing(
    client, mock_agent_missing, mock_cities_pref, auth_header
):
    r = client.get("/calendar/dashboard", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["agent_status"]["available"] is False
    assert body["events_7d"]["count"] == 0
    assert body["todos_30d"]["count"] == 0


def test_dashboard_partial_failure_still_returns(
    client, monkeypatch, mock_cities_pref, auth_header
):
    """A single sub-call failure should not nuke the whole response."""
    agent = MagicMock()
    agent.get_sun_state = AsyncMock(side_effect=RuntimeError("sun down"))
    agent.get_compiled_events = AsyncMock(return_value={"events": [], "count": 0})
    agent.get_todos = AsyncMock(return_value={"todos": [], "count": 0})
    agent.get_status = MagicMock(return_value={"available": True})
    monkeypatch.setattr(cr_module, "_get_calendar_agent_or_none", lambda: agent)
    r = client.get("/calendar/dashboard", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert "events_7d" in body
    # sun was the fallback dict
    assert isinstance(body["sun"], dict)


# ── /calendar/city/select (POST) ─────────────────────────────────────────


def test_city_select_sets_default(client, mock_cities_pref, auth_header):
    r = client.post("/calendar/city/select", json={"city_id": "calgary"}, headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "set"
    assert body["city_id"] == "calgary"
    assert body["city_meta"]["name"] == "Calgary"
    assert mock_cities_pref.get_default_city() == "calgary"


def test_city_select_requires_auth(client, mock_cities_pref):
    r = client.post("/calendar/city/select", json={"city_id": "calgary"})
    assert r.status_code == 401


def test_city_select_missing_city_id_400(client, mock_cities_pref, auth_header):
    r = client.post("/calendar/city/select", json={}, headers=auth_header)
    assert r.status_code == 400


def test_city_select_503_when_pref_missing(client, mock_cities_pref_missing, auth_header):
    r = client.post("/calendar/city/select", json={"city_id": "calgary"}, headers=auth_header)
    assert r.status_code == 503


# ── /calendar/city/current ───────────────────────────────────────────────


def test_city_current_returns_default(client, mock_cities_pref, auth_header):
    r = client.get("/calendar/city/current", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["city_id"] == "edmonton"
    assert body["city_meta"]["name"] == "Edmonton"
    assert "generated_at" in body


def test_city_current_requires_auth(client, mock_cities_pref):
    r = client.get("/calendar/city/current")
    assert r.status_code == 401


def test_city_current_503_when_pref_missing(client, mock_cities_pref_missing, auth_header):
    r = client.get("/calendar/city/current", headers=auth_header)
    assert r.status_code == 503


# ── /calendar/refresh (POST) ─────────────────────────────────────────────


def test_refresh_runs_scan_cycle(client, mock_agent, auth_header):
    r = client.post("/calendar/refresh", json={}, headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["scanned"] == 42
    assert "generated_at" in body
    mock_agent.scan_cycle.assert_awaited()


def test_refresh_passes_city_id_when_provided(client, mock_agent, auth_header):
    r = client.post("/calendar/refresh", json={"city_id": "calgary"}, headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body.get("city_id") == "calgary"


def test_refresh_works_with_empty_body(client, mock_agent, auth_header):
    # No JSON body at all
    r = client.post("/calendar/refresh", headers=auth_header)
    assert r.status_code == 200


def test_refresh_requires_auth(client, mock_agent):
    r = client.post("/calendar/refresh", json={})
    assert r.status_code == 401


def test_refresh_503_when_agent_missing(client, mock_agent_missing, auth_header):
    r = client.post("/calendar/refresh", json={}, headers=auth_header)
    assert r.status_code == 503


def test_refresh_handles_scan_cycle_exception(client, monkeypatch, auth_header):
    agent = MagicMock()
    agent.scan_cycle = AsyncMock(side_effect=RuntimeError("scan exploded"))
    monkeypatch.setattr(cr_module, "_get_calendar_agent_or_none", lambda: agent)
    r = client.post("/calendar/refresh", json={}, headers=auth_header)
    assert r.status_code == 500
    assert "refresh failed" in r.json()["error"]


# ── Route registration smoke ─────────────────────────────────────────────


def test_all_new_routes_registered():
    paths = {(r.path, frozenset(r.methods)) for r in calendar_router.routes}
    expected = [
        ("/calendar/sun", "GET"),
        ("/calendar/events/compiled", "GET"),
        ("/calendar/todos", "GET"),
        ("/calendar/dashboard", "GET"),
        ("/calendar/city/select", "POST"),
        ("/calendar/city/current", "GET"),
        ("/calendar/refresh", "POST"),
    ]
    for path, method in expected:
        assert any(
            p == path and method in methods for p, methods in paths
        ), f"Missing route: {method} {path}"
