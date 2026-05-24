"""Tests for runtime.memory.budget_tracker — the context-token telemetry."""

from __future__ import annotations

import json

import pytest

from runtime.memory import budget_tracker as bt
from runtime.memory.budget_tracker import (
    DEFAULT_BUDGETS,
    MemoryBudgetTracker,
    estimate_tokens,
    run_budget_cycle,
)


@pytest.fixture
def fresh_tracker(tmp_path, monkeypatch):
    """A clean tracker pointed at an isolated ledger and an isolated singleton."""
    # Reset module-level singleton so each test gets its own state.
    monkeypatch.setattr(bt, "_tracker_instance", None)
    ledger = tmp_path / "budget_ledger.jsonl"
    tracker = MemoryBudgetTracker(ledger_path=ledger)
    return tracker


@pytest.mark.asyncio
async def test_record_appends_jsonl_and_updates_summary(fresh_tracker):
    """record() writes one JSONL row and bumps the in-memory summary."""
    t = fresh_tracker
    await t.record("chat_injection", 1234, source="chat:s1")
    await t.record("chat_injection", 2000, source="chat:s2")
    await t.record("council_context", 5000, source="council:tsla")

    # JSONL ledger has 3 rows
    lines = [ln for ln in t.ledger_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3
    rows = [json.loads(ln) for ln in lines]
    assert all("timestamp" in r and "category" in r for r in rows)

    summary = await t.get_daily_summary()
    by_cat = summary["by_category"]
    assert by_cat["chat_injection"]["tokens_in"] == 3234
    assert by_cat["chat_injection"]["calls"] == 2
    assert by_cat["council_context"]["tokens_in"] == 5000
    assert by_cat["council_context"]["calls"] == 1
    assert summary["total_tokens"] == 3234 + 5000


@pytest.mark.asyncio
async def test_check_budget_blocks_when_per_category_cap_exceeded(fresh_tracker):
    """check_budget() returns (False, reason) once per-category cap is breached."""
    t = fresh_tracker
    # Set a tiny cap so we can drive the test deterministically.
    t._budgets["chat_injection"] = 10_000

    allowed, reason = await t.check_budget("chat_injection", 5_000)
    assert allowed is True, reason

    # Fill it past the cap.
    await t.record("chat_injection", 9_500, source="test")
    allowed, reason = await t.check_budget("chat_injection", 1_000)
    assert allowed is False
    assert "cap exceeded" in reason


@pytest.mark.asyncio
async def test_check_budget_blocks_on_platform_cap(fresh_tracker, monkeypatch):
    """Platform-wide cap trips even if per-category caps are fine."""
    t = fresh_tracker
    t._platform_cap = 5_000
    # Make sure per-cat caps are very generous so only the platform cap can trip.
    for cat in list(t._budgets):
        t._budgets[cat] = 1_000_000
    await t.record("chat_injection", 3_000, source="t")
    await t.record("retrieval_rerank", 1_500, source="t")
    allowed, reason = await t.check_budget("council_context", 1_000)
    assert allowed is False
    assert "platform" in reason


@pytest.mark.asyncio
async def test_rollover_resets_totals(fresh_tracker):
    """Faking a date change clears the in-memory summary."""
    t = fresh_tracker
    await t.record("chat_injection", 1_000, source="t")
    summary = await t.get_daily_summary()
    assert summary["by_category"]["chat_injection"]["tokens_in"] == 1_000

    # Force a stale current_date so the next get_daily_summary() rolls over.
    t._current_date = "1999-01-01"
    summary2 = await t.get_daily_summary()
    # Today's bucket is fresh after rollover.
    assert summary2["by_category"].get("chat_injection", {"tokens_in": 0})["tokens_in"] == 0


@pytest.mark.asyncio
async def test_history_aggregates_by_date(fresh_tracker):
    """get_history() rolls up JSONL rows into per-day summaries."""
    t = fresh_tracker
    await t.record("chat_injection", 100, source="t")
    await t.record("council_context", 200, source="t")
    # Inject an older-day row directly into the ledger so we exercise the
    # cross-day rollup path without freezing time.
    with open(t.ledger_path, "a") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": "2020-01-01T00:00:00+00:00",
                    "date": "2020-01-01",
                    "category": "chat_injection",
                    "tokens_in": 999,
                    "tokens_out": 0,
                    "source": "old",
                    "metadata": {},
                }
            )
            + "\n"
        )

    # 7-day window excludes 2020-01-01.
    recent = await t.get_history(days=7)
    assert len(recent) == 1
    assert recent[0]["total_tokens"] == 300

    # 9999-day window captures the old row too.
    full = await t.get_history(days=9999)
    dates = sorted(d["date"] for d in full)
    assert "2020-01-01" in dates
    old = next(d for d in full if d["date"] == "2020-01-01")
    assert old["by_category"]["chat_injection"]["tokens_in"] == 999


@pytest.mark.asyncio
async def test_env_override_replaces_default_cap(tmp_path, monkeypatch):
    """NCL_MEMORY_BUDGET_<CATEGORY> overrides DEFAULT_BUDGETS at construction."""
    monkeypatch.setenv("NCL_MEMORY_BUDGET_CHAT_INJECTION", "777777")
    monkeypatch.setattr(bt, "_tracker_instance", None)
    t = MemoryBudgetTracker(ledger_path=tmp_path / "ledger.jsonl")
    assert t._budgets["chat_injection"] == 777777
    # Other defaults untouched.
    assert t._budgets["council_context"] == DEFAULT_BUDGETS["council_context"]


@pytest.mark.asyncio
async def test_estimate_tokens_chars_over_four():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 12) == 3
    # Very short input still floors to 1 token (estimator never returns 0
    # for non-empty input) — guards against silently dropping tiny calls.
    assert estimate_tokens("hi") == 1


@pytest.mark.asyncio
async def test_run_budget_cycle_persists_snapshot_and_updates_stats(
    fresh_tracker, monkeypatch, tmp_path
):
    """run_budget_cycle() must persist budget_summary.json and update stats."""
    # Wire the singleton to our isolated tracker.
    monkeypatch.setattr(bt, "_tracker_instance", fresh_tracker)
    fresh_tracker._initialized = True

    await fresh_tracker.record("chat_injection", 4_242, source="t")

    stats: dict = {}
    summary = await run_budget_cycle(stats=stats)

    assert summary["by_category"]["chat_injection"]["tokens_in"] == 4_242
    assert (fresh_tracker.summary_path).exists()
    persisted = json.loads(fresh_tracker.summary_path.read_text())
    assert persisted["total_tokens"] == 4_242
    assert "last_memory_budget_check" in stats
    assert stats["last_memory_budget_total_tokens"] == 4_242
