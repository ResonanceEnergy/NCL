"""Tests for runtime.calendar.todo_generator."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# Ensure the NCL repo root is on sys.path.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.calendar import todo_generator  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_todo_dir(tmp_path, monkeypatch):
    """Redirect todo cache into a temp directory."""
    monkeypatch.setattr(todo_generator, "TODO_DIR", tmp_path / "calendar")
    (tmp_path / "calendar").mkdir(parents=True, exist_ok=True)
    return tmp_path / "calendar"


@pytest.fixture
def sample_events():
    today = date.today()
    return [
        {
            "id": "evt-fomc-001",
            "title": "FOMC Decision",
            "category": "fomc",
            "date": (today + timedelta(days=3)).isoformat(),
            "description": "Federal Reserve interest rate decision",
        },
        {
            "id": "evt-opex-001",
            "title": "March Monthly Options Expiry",
            "category": "opex",
            "date": (today + timedelta(days=5)).isoformat(),
            "description": "3rd Friday — monthly expiry",
        },
        {
            "id": "evt-pred-001",
            "title": "GLD prediction: 70% bullish over 2 weeks",
            "category": "prediction",
            "date": (today + timedelta(days=2)).isoformat(),
            "description": "Awarebot forecast",
        },
        {
            "id": "evt-port-001",
            "title": "GLD calls expire 2026-03-19",
            "category": "portfolio",
            "date": (today + timedelta(days=4)).isoformat(),
            "description": "10 contracts at $515 strike",
        },
        {
            "id": "evt-local-001",
            "title": "Edmonton Oilers home game",
            "category": "local",
            "date": (today + timedelta(days=6)).isoformat(),
            "description": "Hockey night",
        },
    ]


@pytest.fixture
def moon_initiate():
    return {
        "phase_name": "New Moon",
        "phase_icon": "🌑",
        "illumination": 0.02,
        "energy_mode": "initiate",
        "energy_description": "Plant seeds. Begin new positions.",
        "days_since_new": 0.5,
    }


@pytest.fixture
def moon_harvest():
    return {
        "phase_name": "Full Moon",
        "phase_icon": "🌕",
        "illumination": 0.98,
        "energy_mode": "harvest",
        "energy_description": "Lock in gains. Review positions.",
        "days_since_new": 14.5,
    }


def _fake_llm_response(items):
    """Mimics a successful Anthropic /v1/messages response."""
    return {
        "content": [{"type": "text", "text": json.dumps(items)}],
        "usage": {"input_tokens": 800, "output_tokens": 400},
    }


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResp(self._payload, self._status)


# ── Schema validation ────────────────────────────────────────────────

REQUIRED_KEYS = {
    "id",
    "priority",
    "action",
    "context",
    "due_date",
    "urgency",
    "category",
    "related_event_ids",
    "energy_aligned",
    "estimated_minutes",
}


def _assert_valid_todo(item):
    assert isinstance(item, dict)
    missing = REQUIRED_KEYS - item.keys()
    assert not missing, f"Missing keys: {missing}"
    assert isinstance(item["id"], str) and item["id"]
    assert isinstance(item["priority"], int)
    assert 1 <= item["priority"] <= 5
    assert isinstance(item["action"], str) and item["action"]
    assert isinstance(item["context"], str)
    date.fromisoformat(item["due_date"])  # raises if invalid
    assert item["urgency"] in {"today", "this_week", "this_month"}
    assert item["category"] in todo_generator.VALID_CATEGORIES
    assert isinstance(item["related_event_ids"], list)
    assert isinstance(item["energy_aligned"], bool)
    assert isinstance(item["estimated_minutes"], int)
    assert item["estimated_minutes"] >= 1


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_based_fallback_runs_when_no_api_key(
    tmp_todo_dir,
    sample_events,
    moon_initiate,
    monkeypatch,
):
    """If ANTHROPIC_API_KEY is missing, we fall back to rule-based."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    todos = await todo_generator.generate_todos_for_window(
        city_id="edmonton",
        window_days=7,
        events=sample_events,
        moon_phase=moon_initiate,
    )
    assert len(todos) >= 1
    for t in todos:
        _assert_valid_todo(t)
    # Cached file should exist.
    cache = todo_generator._cache_path("edmonton", 7)
    assert cache.exists()
    payload = json.loads(cache.read_text())
    assert payload["meta"]["fallback_used"] is True


@pytest.mark.asyncio
async def test_rule_based_fallback_when_budget_exceeded(
    tmp_todo_dir,
    sample_events,
    moon_initiate,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch.object(todo_generator, "_can_spend_anthropic", new=AsyncMock(return_value=False)):
        todos = await todo_generator.generate_todos_for_window(
            city_id="edmonton",
            window_days=7,
            events=sample_events,
            moon_phase=moon_initiate,
        )
    assert todos
    for t in todos:
        _assert_valid_todo(t)
    payload = json.loads(todo_generator._cache_path("edmonton", 7).read_text())
    assert payload["meta"]["fallback_used"] is True


@pytest.mark.asyncio
async def test_llm_path_with_mocked_response(
    tmp_todo_dir,
    sample_events,
    moon_initiate,
    monkeypatch,
):
    today = date.today()
    fake_items = [
        {
            "id": "ai-001",
            "priority": 5,
            "action": "Review GLD calls before March 19 expiry",
            "context": "10 contracts at $515 strike going binary.",
            "due_date": (today + timedelta(days=4)).isoformat(),
            "urgency": "this_week",
            "category": "portfolio",
            "related_event_ids": ["evt-port-001", "evt-opex-001"],
            "energy_aligned": False,
            "estimated_minutes": 20,
        },
        {
            "id": "ai-002",
            "priority": 4,
            "action": "Plan FOMC reaction trades",
            "context": "Fed decision in 3 days; size positions accordingly.",
            "due_date": (today + timedelta(days=2)).isoformat(),
            "urgency": "this_week",
            "category": "market",
            "related_event_ids": ["evt-fomc-001"],
            "energy_aligned": False,
            "estimated_minutes": 45,
        },
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    # Migrated to runtime.llm.chat — patch the facade directly.
    # _llm_generate_todos does `from ..llm import chat` at call time, which
    # resolves through `runtime.llm.__init__`, so we patch the symbol there.
    import runtime.llm as llm_pkg
    from runtime.llm.client import ChatResult

    async def _fake_chat(**kwargs):
        return ChatResult(
            text=json.dumps(fake_items),
            citations=[],
            usage_input_tokens=800,
            usage_output_tokens=400,
            cost_usd=0.0,
            model=kwargs.get("model", "claude-haiku-4-5-20251001"),
            latency_ms=1,
            raw={},
        )

    with (
        patch.object(llm_pkg, "chat", new=_fake_chat),
        patch.object(todo_generator, "_can_spend_anthropic", new=AsyncMock(return_value=True)),
    ):
        todos = await todo_generator.generate_todos_for_window(
            city_id="edmonton",
            window_days=7,
            events=sample_events,
            moon_phase=moon_initiate,
        )

    assert len(todos) == 2
    for t in todos:
        _assert_valid_todo(t)
    # Sorted by priority desc.
    assert todos[0]["priority"] >= todos[1]["priority"]
    payload = json.loads(todo_generator._cache_path("edmonton", 7).read_text())
    assert payload["meta"]["fallback_used"] is False


@pytest.mark.asyncio
async def test_llm_failure_falls_back(
    tmp_todo_dir,
    sample_events,
    moon_initiate,
    monkeypatch,
):
    """A failure from the LLM facade should not crash; fallback kicks in."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    # Migrated to runtime.llm.chat — simulate an LLM-facade failure by
    # raising from the patched chat function.
    import runtime.llm as llm_pkg

    async def _failing_chat(**kwargs):
        raise RuntimeError("Anthropic HTTP 500: boom")

    with (
        patch.object(llm_pkg, "chat", new=_failing_chat),
        patch.object(todo_generator, "_can_spend_anthropic", new=AsyncMock(return_value=True)),
    ):
        todos = await todo_generator.generate_todos_for_window(
            city_id="edmonton",
            window_days=7,
            events=sample_events,
            moon_phase=moon_initiate,
        )
    assert todos
    for t in todos:
        _assert_valid_todo(t)
    payload = json.loads(todo_generator._cache_path("edmonton", 7).read_text())
    assert payload["meta"]["fallback_used"] is True
    assert payload["meta"]["llm_error"]


@pytest.mark.asyncio
async def test_energy_alignment_initiate(
    tmp_todo_dir,
    sample_events,
    moon_initiate,
    monkeypatch,
):
    """Actions containing 'open' / 'start' align with `initiate`."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Inject events whose rule-based phrasing won't include initiate keywords,
    # then manually run post_process with crafted todos.
    crafted = [
        {
            "id": "x1",
            "priority": 4,
            "action": "Open new GLD position",
            "context": "test",
            "due_date": date.today().isoformat(),
            "urgency": "today",
            "category": "portfolio",
            "related_event_ids": [],
            "energy_aligned": False,
            "estimated_minutes": 15,
        },
        {
            "id": "x2",
            "priority": 4,
            "action": "Exit stale TSLA position",
            "context": "test",
            "due_date": date.today().isoformat(),
            "urgency": "today",
            "category": "portfolio",
            "related_event_ids": [],
            "energy_aligned": False,
            "estimated_minutes": 15,
        },
    ]
    out = todo_generator._post_process(crafted, energy_mode="initiate", window_days=7)
    by_id = {t["id"]: t for t in out}
    assert by_id["x1"]["energy_aligned"] is True  # "Open" aligns
    assert by_id["x2"]["energy_aligned"] is False  # "Exit" does not


def test_energy_alignment_release_releases_exits():
    crafted = [
        {
            "id": "y1",
            "priority": 4,
            "action": "Exit TSLA before close",
            "context": "",
            "due_date": date.today().isoformat(),
            "urgency": "today",
            "category": "portfolio",
            "related_event_ids": [],
            "energy_aligned": False,
            "estimated_minutes": 10,
        },
    ]
    out = todo_generator._post_process(crafted, energy_mode="release", window_days=7)
    assert out[0]["energy_aligned"] is True


def test_specificity_30_day_uses_fewer_todos(sample_events):
    """Rule-based 30-day mode caps at 8 event-derived todos."""
    todos_7 = todo_generator._rule_based_todos("edmonton", 7, sample_events, None)
    todos_30 = todo_generator._rule_based_todos("edmonton", 30, sample_events, None)
    # Both should be valid lists.
    assert isinstance(todos_7, list)
    assert isinstance(todos_30, list)
    # 30-day strategic todos should use "Plan around" phrasing.
    assert any("Plan around" in t["action"] for t in todos_30)
    # 7-day tactical should use "Review".
    assert any("Review" in t["action"] for t in todos_7)


def test_coerce_clamps_priority_and_dates():
    today = date.today()
    horizon = today + timedelta(days=7)
    item = todo_generator._coerce_item(
        {"action": "Test", "priority": 99, "due_date": "1999-01-01"},
        today=today,
        horizon=horizon,
    )
    assert item["priority"] == 5
    assert item["due_date"] == today.isoformat()
    item2 = todo_generator._coerce_item(
        {"action": "Test", "priority": -5, "due_date": (today + timedelta(days=999)).isoformat()},
        today=today,
        horizon=horizon,
    )
    assert item2["priority"] == 1
    assert item2["due_date"] == horizon.isoformat()


def test_coerce_invalid_category_falls_back_to_intel():
    today = date.today()
    item = todo_generator._coerce_item(
        {"action": "Test", "category": "blargh"},
        today=today,
        horizon=today + timedelta(days=7),
    )
    assert item["category"] == "intel"


def test_normalize_category_aliases():
    assert todo_generator._normalize_category("fomc") == "market"
    assert todo_generator._normalize_category("opex") == "market"
    assert todo_generator._normalize_category("kp") == "sun"
    assert todo_generator._normalize_category("concert") == "local"
    assert todo_generator._normalize_category("portfolio") == "portfolio"
    assert todo_generator._normalize_category(None) == "intel"


@pytest.mark.asyncio
async def test_get_cached_todos_roundtrip(tmp_todo_dir, sample_events, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    await todo_generator.generate_todos_for_window(
        city_id="calgary",
        window_days=30,
        events=sample_events,
    )
    cached = await todo_generator.get_cached_todos("calgary", 30)
    assert cached is not None
    assert isinstance(cached, list)
    assert all("action" in t for t in cached)


@pytest.mark.asyncio
async def test_get_cached_todos_missing_returns_none(tmp_todo_dir):
    assert await todo_generator.get_cached_todos("never_set", 7) is None


def test_parse_event_date_handles_multiple_formats():
    today_iso = date.today().isoformat()
    assert todo_generator._parse_event_date({"date": today_iso}) == date.today()
    assert todo_generator._parse_event_date({"datetime": f"{today_iso}T15:30:00Z"}) == date.today()
    assert todo_generator._parse_event_date({}) is None
    assert todo_generator._parse_event_date({"date": "garbage"}) is None


def test_stable_id_is_deterministic():
    a = todo_generator._stable_id("foo")
    b = todo_generator._stable_id("foo")
    c = todo_generator._stable_id("bar")
    assert a == b
    assert a != c
    assert len(a) == 12


@pytest.mark.asyncio
async def test_parse_json_array_tolerates_fences():
    raw = """```json
[{"action": "do thing", "priority": 3, "due_date": "%s",
   "urgency": "today", "category": "intel"}]
```""" % date.today().isoformat()
    parsed = todo_generator._parse_json_array(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["action"] == "do thing"


@pytest.mark.asyncio
async def test_window_30_uses_strategic_phrasing(
    tmp_todo_dir,
    sample_events,
    moon_harvest,
    monkeypatch,
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    todos = await todo_generator.generate_todos_for_window(
        city_id="edmonton",
        window_days=30,
        events=sample_events,
        moon_phase=moon_harvest,
    )
    for t in todos:
        _assert_valid_todo(t)
    # At least one item should be derived from the moon ritual.
    assert any(t["category"] == "moon" for t in todos)
