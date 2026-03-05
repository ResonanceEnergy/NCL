#!/usr/bin/env python3
"""
Tests for NCL Mission Runner — daily, weekly, drift, overload missions.
"""
import json
import sys
import pytest
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / 'ncl_agency_runtime' / 'runtime'))

from ncl_agency_runtime.runtime.mission_runner import (
    make_daily_brief, make_weekly_brief,
    investigate_drift, investigate_overload,
    load_events_for_date
)


# ── Fixtures ─────────────────────────────────────────────────

def make_events(n=10, event_type="ncl.test.event"):
    """Generate n sample events."""
    return [
        {
            "event_id": f"evt-{i}",
            "event_type": event_type if i % 3 != 0 else "ncl.other.event",
            "occurred_at": f"2026-02-18T{10 + i % 12:02d}:00:00Z",
            "source": {"device": "mac"},
            "payload": {"index": i}
        }
        for i in range(n)
    ]


# ── Daily Brief Tests ────────────────────────────────────────

class TestDailyBrief:
    def test_generates_markdown(self):
        events = make_events(5)
        brief = make_daily_brief(events, "2026-02-18")
        assert "# NCL Daily Brief" in brief
        assert "2026-02-18" in brief

    def test_shows_event_count(self):
        events = make_events(15)
        brief = make_daily_brief(events, "2026-02-18")
        assert "**15**" in brief

    def test_shows_top_types(self):
        events = make_events(10)
        brief = make_daily_brief(events, "2026-02-18")
        assert "ncl.test.event" in brief

    def test_empty_events(self):
        brief = make_daily_brief([], "2026-02-18")
        assert "**0**" in brief
        assert "# NCL Daily Brief" in brief


# ── Weekly Brief Tests ───────────────────────────────────────

class TestWeeklyBrief:
    def test_generates_weekly_markdown(self):
        events = make_events(20)
        brief = make_weekly_brief(events, "2026-02-12", "2026-02-18")
        assert "# NCL Weekly Brief" in brief
        assert "2026-02-12" in brief
        assert "2026-02-18" in brief

    def test_weekly_shows_daily_average(self):
        events = make_events(14)
        brief = make_weekly_brief(events, "2026-02-12", "2026-02-18")
        assert "Daily average" in brief

    def test_empty_week(self):
        brief = make_weekly_brief([], "2026-02-12", "2026-02-18")
        assert "**0**" in brief


# ── Drift Investigation Tests ────────────────────────────────

class TestDriftInvestigation:
    def test_drift_no_baseline(self):
        events = make_events(10)
        report = investigate_drift(events, "2026-02-18")
        assert "# NCL Drift Report" in report
        # No baseline → no drift detected
        assert "No Significant Drift" in report

    def test_drift_with_baseline(self):
        events = make_events(10, "ncl.focus.switch")
        # Create baseline file with very different averages
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"ncl.focus.switch": 2.0, "ncl.other.event": 1.0}, f)
            baseline_path = f.name

        report = investigate_drift(events, "2026-02-18", baseline_path)
        assert "Anomalies Detected" in report or "Drift Report" in report

        Path(baseline_path).unlink()

    def test_drift_empty_events(self):
        report = investigate_drift([], "2026-02-18")
        assert "**0**" in report


# ── Overload Investigation Tests ─────────────────────────────

class TestOverloadInvestigation:
    def test_overload_below_threshold(self):
        events = make_events(5)
        report = investigate_overload(events, "2026-02-18", threshold=100)
        assert "No Overload Detected" in report

    def test_overload_above_threshold(self):
        events = make_events(200)
        report = investigate_overload(events, "2026-02-18", threshold=100)
        assert "Overload Signals" in report

    def test_high_context_switching(self):
        events = [
            {"event_id": f"evt-{i}", "event_type": f"type_{i}",
             "occurred_at": "2026-02-18T10:00:00Z"}
            for i in range(20)  # 20 distinct types
        ]
        report = investigate_overload(events, "2026-02-18", threshold=1000)
        assert "context-switching" in report

    def test_overload_hourly_distribution(self):
        events = make_events(50)
        report = investigate_overload(events, "2026-02-18")
        assert "Hourly Distribution" in report


# ── Event Loading Tests ──────────────────────────────────────

class TestLoadEvents:
    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            events, path = load_events_for_date(Path(tmpdir), "2026-01-01")
            assert events == []

    def test_load_existing_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_file = Path(tmpdir) / "2026-02-18.ndjson"
            events_data = make_events(3)
            with open(event_file, 'w') as f:
                for e in events_data:
                    f.write(json.dumps(e) + "\n")

            events, path = load_events_for_date(Path(tmpdir), "2026-02-18")
            assert len(events) == 3
            assert events[0]["event_id"] == "evt-0"


# ── Mission Queue File Tests ─────────────────────────────────

class TestMissionQueueFiles:
    def test_daily_brief_mission_exists(self):
        p = Path(__file__).parent.parent / "ncl_agency_runtime" / "missions" / "queue" / "daily_brief_today.json"
        assert p.exists()
        m = json.loads(p.read_text())
        assert m["mission_type"] == "daily_brief"

    def test_weekly_brief_mission_exists(self):
        p = Path(__file__).parent.parent / "ncl_agency_runtime" / "missions" / "queue" / "weekly_brief.json"
        assert p.exists()
        m = json.loads(p.read_text())
        assert m["mission_type"] == "weekly_brief"

    def test_drift_mission_exists(self):
        p = Path(__file__).parent.parent / "ncl_agency_runtime" / "missions" / "queue" / "drift_investigation.json"
        assert p.exists()
        m = json.loads(p.read_text())
        assert m["mission_type"] == "drift_investigation"

    def test_overload_mission_exists(self):
        p = Path(__file__).parent.parent / "ncl_agency_runtime" / "missions" / "queue" / "overload_investigation.json"
        assert p.exists()
        m = json.loads(p.read_text())
        assert m["mission_type"] == "overload_investigation"
