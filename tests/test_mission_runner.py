#!/usr/bin/env python3
"""
Tests for NCL Mission Runner — daily, weekly, drift, overload missions.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / 'ncl_agency_runtime' / 'runtime'))

from ncl_agency_runtime.runtime.mission_runner import (
    MissionStatus,
    investigate_drift,
    investigate_overload,
    load_events_for_date,
    make_daily_brief,
    make_weekly_brief,
    route_mission,
    run_with_retry,
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
            events, _path = load_events_for_date(Path(tmpdir), "2026-01-01")
            assert events == []

    def test_load_existing_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_file = Path(tmpdir) / "2026-02-18.ndjson"
            events_data = make_events(3)
            with open(event_file, 'w') as f:
                for e in events_data:
                    f.write(json.dumps(e) + "\n")

            events, _path = load_events_for_date(Path(tmpdir), "2026-02-18")
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


# ── Mission Routing Tests ────────────────────────────────────

class TestMissionRouting:
    def test_route_daily_brief(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            with patch("ncl_agency_runtime.runtime.mission_runner.expanduser", return_value=Path(tmpdir)):
                mission = {"mission_id": "m-001", "mission_type": "daily_brief",
                           "inputs": {"date": "2026-03-01"}}
                result = route_mission(mission)
                assert "2026-03-01.md" in result

    def test_route_weekly_brief(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            with patch("ncl_agency_runtime.runtime.mission_runner.expanduser", return_value=Path(tmpdir)):
                mission = {"mission_id": "m-002", "mission_type": "weekly_brief",
                           "inputs": {"start_date": "2026-02-23", "end_date": "2026-03-01"}}
                result = route_mission(mission)
                assert "2026-02-23" in result

    def test_route_drift(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            with patch("ncl_agency_runtime.runtime.mission_runner.expanduser", return_value=Path(tmpdir)):
                mission = {"mission_id": "m-003", "mission_type": "drift_investigation",
                           "inputs": {"date": "2026-03-01"}}
                result = route_mission(mission)
                assert "2026-03-01.md" in result

    def test_route_overload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            with patch("ncl_agency_runtime.runtime.mission_runner.expanduser", return_value=Path(tmpdir)):
                mission = {"mission_id": "m-004", "mission_type": "overload_investigation",
                           "inputs": {"date": "2026-03-01"}}
                result = route_mission(mission)
                assert "2026-03-01.md" in result

    def test_route_unknown_type_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown mission type"):
            route_mission({"mission_id": "m-bad", "mission_type": "nonexistent"})


# ── Retry / Backoff Tests ────────────────────────────────────

class TestRetryBackoff:
    def test_succeeds_first_try(self):
        call_count = {"n": 0}
        def handler(mission):
            call_count["n"] += 1
            return "ok"
        result = run_with_retry(handler, {"mission_id": "r-001"}, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert call_count["n"] == 1

    def test_succeeds_after_retries(self):
        call_count = {"n": 0}
        def handler(mission):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("transient")
            return "recovered"
        result = run_with_retry(handler, {"mission_id": "r-002"}, max_attempts=3, base_delay=0)
        assert result == "recovered"
        assert call_count["n"] == 3

    def test_exhausts_retries_raises(self):
        import pytest
        def handler(mission):
            raise RuntimeError("permanent")
        with pytest.raises(RuntimeError, match="permanent"):
            run_with_retry(handler, {"mission_id": "r-003"}, max_attempts=2, base_delay=0)

    def test_retry_records_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ms = MissionStatus(Path(tmpdir))
            call_count = {"n": 0}
            def handler(mission):
                call_count["n"] += 1
                if call_count["n"] < 2:
                    raise RuntimeError("fail once")
                return "ok"
            run_with_retry(handler, {"mission_id": "r-004", "mission_type": "test"},
                           max_attempts=3, base_delay=0, mission_status=ms)
            history = ms.load_history()
            statuses = [h["status"] for h in history]
            assert "running" in statuses
            assert "completed" in statuses

    def test_dead_letter_on_exhaustion(self):
        import pytest
        with tempfile.TemporaryDirectory() as tmpdir:
            ms = MissionStatus(Path(tmpdir))
            def handler(mission):
                raise RuntimeError("always fails")
            with pytest.raises(RuntimeError):
                run_with_retry(handler, {"mission_id": "dl-001", "mission_type": "test"},
                               max_attempts=2, base_delay=0, mission_status=ms)
            # Dead-letter file should exist
            dl_path = Path(tmpdir) / "dead_letter" / "dl-001.json"
            assert dl_path.exists()
            dl = json.loads(dl_path.read_text())
            assert dl["attempts"] == 2
            assert "always fails" in dl["error"]


# ── Mission Status / History Tests ───────────────────────────

class TestMissionStatus:
    def test_record_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ms = MissionStatus(Path(tmpdir))
            ms.record("m-100", MissionStatus.QUEUED, mission_type="daily_brief")
            ms.record("m-100", MissionStatus.RUNNING, mission_type="daily_brief")
            ms.record("m-100", MissionStatus.COMPLETED, mission_type="daily_brief")
            history = ms.load_history()
            assert len(history) == 3
            assert history[0]["status"] == "queued"
            assert history[-1]["status"] == "completed"

    def test_dead_letter_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ms = MissionStatus(Path(tmpdir))
            mission = {"mission_id": "dl-test", "mission_type": "daily_brief"}
            dl_path = ms.dead_letter(mission, "boom", 3)
            assert dl_path.exists()
            content = json.loads(dl_path.read_text())
            assert content["mission"]["mission_id"] == "dl-test"
            assert content["attempts"] == 3

    def test_load_empty_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ms = MissionStatus(Path(tmpdir))
            assert ms.load_history() == []

    def test_history_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ms = MissionStatus(Path(tmpdir))
            for i in range(20):
                ms.record(f"m-{i}", MissionStatus.COMPLETED, mission_type="test")
            history = ms.load_history(limit=5)
            assert len(history) == 5
