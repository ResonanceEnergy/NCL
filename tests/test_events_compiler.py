"""Tests for runtime.calendar.events_compiler.

Verifies:
  - Per-source normalization shape conforms to schema
  - Source isolation: a failing puller does not break compile
  - Dedup-friendly id (sha256 of source|source_id|date)
  - Cache miss returns fresh + writes file, cache hit returns same
  - Stale cache is returned with stale: true and background refresh fires
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from runtime.calendar import events_compiler as ec


# ───────────────────────────── Fixtures ─────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Re-point every data path the compiler reads/writes to tmp_path."""
    data_root = tmp_path / "data"
    intel_root = tmp_path / "intelligence-scan"
    predictions = data_root / "predictions"
    journal_dir = data_root / "journal"
    council_dir = intel_root / "council-reports"
    signals_dir = intel_root / "signals"
    cache_dir = data_root / "calendar"
    for d in (predictions, journal_dir, council_dir, signals_dir, cache_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(ec, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(ec, "_DATA_ROOT", data_root)
    monkeypatch.setattr(ec, "_INTEL_ROOT", intel_root)
    monkeypatch.setattr(ec, "_PREDICTIONS_DIR", predictions)
    monkeypatch.setattr(ec, "_JOURNAL_FILE", journal_dir / "journal.jsonl")
    monkeypatch.setattr(ec, "_COUNCIL_REPORTS_DIR", council_dir)
    monkeypatch.setattr(ec, "_SCANNER_SIGNALS_DIR", signals_dir)
    monkeypatch.setattr(ec, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(ec, "_CACHE_FILE", cache_dir / "compiled_events_cache.jsonl")
    # Clear in-process cache between tests
    ec._mem_cache.clear()
    ec._refresh_tasks.clear()
    yield


def _write_prediction(dirpath: Path, name: str, target_date: str, confidence: float = 0.75):
    payload = {
        "topic": "AAPL earnings beat",
        "consensus": "Likely beat. $AAPL guidance crucial.",
        "confidence": confidence,
        "target_date": target_date,
        "timestamp": "2026-05-01T12:00:00Z",
    }
    (dirpath / f"pred-{name}.json").write_text(json.dumps(payload))


def _write_council(dirpath: Path, session: str, ts: str):
    payload = {
        "council_type": "x",
        "session_id": session,
        "timestamp": ts,
        "insights": [
            {
                "title": "BlackRock BTC ETF Inflow",
                "description": "Institutional rotation accelerating.",
                "actionable": True,
                "tags": ["BTC", "ETH", "institutional"],
            }
        ],
    }
    (dirpath / f"{session}.json").write_text(json.dumps(payload))


def _write_scanner(dirpath: Path, fname: str, sig: dict):
    line = json.dumps(sig)
    (dirpath / fname).write_text(line + "\n")


def _write_intel(dirpath: Path, name: str, ts: str):
    payload = {
        "title": "Weekly war room",
        "session_id": name,
        "timestamp": ts,
        "executive_summary": "Crypto bull cycle confirmed.",
    }
    (dirpath / f"WAR_ROOM_BRIEFING_{name}.json").write_text(json.dumps(payload))


def _write_journal(journal_file: Path, entries: list[dict]):
    with journal_file.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# ───────────────────────────── Tests ─────────────────────────────


def test_schema_keys():
    """_normalize must produce the contract dict."""
    out = ec._normalize(
        source="prediction",
        source_id="pred-1",
        event_date=date(2026, 5, 21),
        title="t",
        description="d",
        category="general",
        impact="high",
    )
    required = {
        "id", "date", "time", "datetime_utc", "title", "description",
        "source", "source_id", "category", "impact",
        "tickers", "entities", "url", "raw",
    }
    assert required.issubset(out.keys())
    assert out["date"] == "2026-05-21"
    assert out["impact"] == "high"
    assert isinstance(out["tickers"], list)


def test_event_id_is_stable_and_dedup_friendly():
    a = ec._make_event_id("prediction", "pred-x", "2026-05-21")
    b = ec._make_event_id("prediction", "pred-x", "2026-05-21")
    c = ec._make_event_id("prediction", "pred-y", "2026-05-21")
    assert a == b
    assert a != c


def test_extract_tickers_dollar_and_context():
    out = ec._extract_tickers("Watching $AAPL closely and TSLA stock today.")
    assert "AAPL" in out
    assert "TSLA" in out


@pytest.mark.asyncio
async def test_pull_predictions(tmp_path):
    _write_prediction(ec._PREDICTIONS_DIR, "20260521-001", "2026-05-23")
    _write_prediction(ec._PREDICTIONS_DIR, "20260521-002", "2030-01-01")  # out of range

    out = await ec._pull_predictions(date(2026, 5, 21), date(2026, 5, 28))
    assert len(out) == 1
    assert out[0]["source"] == "prediction"
    assert out[0]["date"] == "2026-05-23"
    assert out[0]["impact"] == "high"


@pytest.mark.asyncio
async def test_pull_council(tmp_path):
    _write_council(ec._COUNCIL_REPORTS_DIR, "sess-1", "2026-05-22T10:00:00Z")
    out = await ec._pull_council(date(2026, 5, 21), date(2026, 5, 28))
    assert len(out) == 1
    assert out[0]["source"] == "council"
    assert "BTC" in out[0]["tickers"]


@pytest.mark.asyncio
async def test_pull_scanner_filters_by_importance(tmp_path):
    today_ts = datetime.now(timezone.utc).isoformat()
    today = date.today()
    high_sig = {
        "signal_id": "sig-1",
        "title": "AAPL earnings tomorrow",
        "description": "Earnings release imminent",
        "importance_score": 92,
        "timestamp": today_ts,
        "category": "earnings",
        "convergence_tags": ["AAPL"],
    }
    low_sig = {
        "signal_id": "sig-2",
        "title": "noise",
        "description": "noise",
        "importance_score": 10,
        "timestamp": today_ts,
    }
    _write_scanner(ec._SCANNER_SIGNALS_DIR, f"signals-{today.isoformat()}.jsonl",
                   high_sig)
    with (ec._SCANNER_SIGNALS_DIR / f"signals-{today.isoformat()}.jsonl").open("a") as f:
        f.write(json.dumps(low_sig) + "\n")

    out = await ec._pull_scanner(today, today + timedelta(days=1))
    # high signal kept, low noise dropped
    sids = [e["source_id"] for e in out]
    assert "sig-1" in sids
    assert "sig-2" not in sids
    assert out[0]["impact"] == "critical"


@pytest.mark.asyncio
async def test_pull_portfolio_no_manager_no_key():
    """Without a PortfolioManager or Finnhub key, returns []."""
    out = await ec._pull_portfolio(date(2026, 5, 21), date(2026, 5, 28))
    assert out == []


@pytest.mark.asyncio
async def test_pull_intel(tmp_path):
    today = date.today()
    _write_intel(ec._COUNCIL_REPORTS_DIR, "wr-1", today.isoformat() + "T08:00:00Z")
    out = await ec._pull_intel(today, today + timedelta(days=1))
    assert len(out) == 1
    assert out[0]["source"] == "intel"


@pytest.mark.asyncio
async def test_pull_journal_due_date():
    _write_journal(ec._JOURNAL_FILE, [
        {
            "entry_id": "j1",
            "title": "Call broker about $TSLA",
            "content": "Re-balance",
            "due_date": "2026-05-23",
            "importance": 0.8,
            "tags": ["broker"],
        },
        {
            "entry_id": "j2",
            "title": "no due date",
            "content": "ignored",
        },
    ])
    out = await ec._pull_journal(date(2026, 5, 21), date(2026, 5, 28))
    assert len(out) == 1
    assert out[0]["source"] == "journal"
    assert out[0]["impact"] == "high"
    assert "TSLA" in out[0]["tickers"]


@pytest.mark.asyncio
async def test_compile_brain_events_isolates_failures(monkeypatch):
    """If one source raises, the rest must still return data."""
    async def good():
        return [ec._normalize(
            source="prediction", source_id="p", event_date=date.today(), title="t"
        )]

    async def boom():
        raise RuntimeError("simulated source failure")

    monkeypatch.setattr(ec, "_pull_predictions",
                        lambda s, e: good())
    monkeypatch.setattr(ec, "_pull_council",
                        lambda s, e: boom())
    monkeypatch.setattr(ec, "_pull_scanner",
                        lambda s, e: good())
    monkeypatch.setattr(ec, "_pull_portfolio",
                        lambda s, e: good())
    monkeypatch.setattr(ec, "_pull_intel",
                        lambda s, e: good())
    monkeypatch.setattr(ec, "_pull_journal",
                        lambda s, e: good())

    out = await ec.compile_brain_events(date.today(), date.today())
    # 5 good + 1 failed = 5 events
    assert len(out) == 5


@pytest.mark.asyncio
async def test_compile_unified_cache_hit_miss(monkeypatch):
    """First call writes cache. Second call returns same events without recomputing."""
    call_count = {"n": 0}

    async def fake_fresh(city_id, start, end):
        call_count["n"] += 1
        return [ec._normalize(
            source="prediction",
            source_id="p-1",
            event_date=start,
            title="held",
        )]

    monkeypatch.setattr(ec, "_compile_unified_fresh", fake_fresh)

    today = date.today()
    out1 = await ec.compile_unified_events("edmonton", today, today)
    assert len(out1) == 1
    assert call_count["n"] == 1
    assert ec._CACHE_FILE.is_file()

    # Second call within TTL -> cache hit, no recompute
    out2 = await ec.compile_unified_events("edmonton", today, today)
    assert len(out2) == 1
    assert call_count["n"] == 1
    assert out2[0]["id"] == out1[0]["id"]


@pytest.mark.asyncio
async def test_stale_cache_marks_and_refreshes(monkeypatch):
    """A stale entry is returned with stale=True and a background refresh fires."""
    today = date.today()
    key = ec._cache_key("edmonton", today, today)

    # Plant an OLD record directly
    old_event = ec._normalize(
        source="prediction", source_id="old", event_date=today, title="old"
    )
    ec._mem_cache[key] = (time.time() - (ec._CACHE_TTL_SECONDS + 60), [old_event])

    refreshed = {"n": 0}

    async def fake_fresh(city_id, start, end):
        refreshed["n"] += 1
        return [ec._normalize(
            source="prediction", source_id="new", event_date=start, title="new"
        )]

    monkeypatch.setattr(ec, "_compile_unified_fresh", fake_fresh)

    out = await ec.compile_unified_events("edmonton", today, today)
    # Stale data served immediately
    assert any(e.get("stale") for e in out)

    # Let the background task run
    await asyncio.sleep(0.05)
    # Background refresh should have fired
    assert refreshed["n"] >= 1


@pytest.mark.asyncio
async def test_get_cached_compile_returns_none_when_missing():
    out = await ec.get_cached_compile("edmonton", date.today(), date.today())
    assert out is None
