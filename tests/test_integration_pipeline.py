#!/usr/bin/env python3
"""
Integration test — Full NCL event pipeline.
Event JSON → schema validation → NDJSON write → mission pickup → report.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib_ncl import append_ndjson, day_file, ensure_dirs, validate_minimal  # noqa: E402


def _make_valid_event(event_type="ncl.screentime.total", event_id="evt-int-001"):
    """Create a minimal valid NCL event."""
    return {
        "schema_version": "ncl.event.v1",
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-03-10T14:00:00+00:00",
        "source": {"device": "iPhone", "origin": "shortcut"},
        "privacy": {"level": "P1"},
        "payload": {"date": "2026-03-10", "total_seconds": 3600},
    }


class TestFullPipeline:
    """End-to-end: validate → write NDJSON → read back → build brief."""

    def test_validate_write_read_roundtrip(self):
        event = _make_valid_event()

        # Step 1: Validate
        ok, reason = validate_minimal(event)
        assert ok, f"Validation failed: {reason}"

        # Step 2: Write to day-file NDJSON
        with tempfile.TemporaryDirectory() as tmpdir:
            event_dir = Path(tmpdir) / "data" / "event_log"
            ensure_dirs(event_dir)

            target = day_file(event_dir, event["occurred_at"])
            append_ndjson(target, event)

            # Step 3: Read back and verify
            lines = target.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1
            loaded = json.loads(lines[0])
            assert loaded["event_id"] == "evt-int-001"
            assert loaded["payload"]["total_seconds"] == 3600

    def test_multiple_events_same_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_dir = Path(tmpdir) / "data" / "event_log"
            ensure_dirs(event_dir)

            for i in range(5):
                evt = _make_valid_event(event_id=f"evt-multi-{i:03d}")
                ok, _ = validate_minimal(evt)
                assert ok
                target = day_file(event_dir, evt["occurred_at"])
                append_ndjson(target, evt)

            lines = target.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 5
            ids = {json.loads(line)["event_id"] for line in lines}
            assert len(ids) == 5

    def test_invalid_event_rejected(self):
        bad_event = {"event_type": "test", "payload": {}}
        ok, reason = validate_minimal(bad_event)
        assert not ok
        assert "missing" in reason

    def test_bad_schema_version_rejected(self):
        event = _make_valid_event()
        event["schema_version"] = "wrong"
        ok, reason = validate_minimal(event)
        assert not ok
        assert "bad_schema_version" in reason

    def test_bad_privacy_rejected(self):
        event = _make_valid_event()
        event["privacy"] = {"level": "INVALID"}
        ok, reason = validate_minimal(event)
        assert not ok
        assert "bad_privacy" in reason

    def test_day_file_groups_by_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_dir = Path(tmpdir)
            f1 = day_file(event_dir, "2026-03-10T10:00:00+00:00")
            f2 = day_file(event_dir, "2026-03-11T10:00:00+00:00")
            f3 = day_file(event_dir, "2026-03-10T22:00:00+00:00")
            assert f1.name == "2026-03-10.ndjson"
            assert f2.name == "2026-03-11.ndjson"
            assert f1 == f3  # Same day

    def test_mission_brief_from_events(self):
        """Simulate mission_runner building a brief from stored events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            event_dir = Path(tmpdir)
            events = []
            for i in range(3):
                evt = _make_valid_event(event_id=f"evt-brief-{i}")
                evt["occurred_at"] = f"2026-03-10T{10+i}:00:00+00:00"
                events.append(evt)
                target = day_file(event_dir, evt["occurred_at"])
                append_ndjson(target, evt)

            # Read events for the day (simulating mission_runner)
            ndjson_file = event_dir / "2026-03-10.ndjson"
            loaded_events = []
            for line in ndjson_file.read_text(encoding="utf-8").strip().split("\n"):
                loaded_events.append(json.loads(line))

            assert len(loaded_events) == 3

            # Simulate brief generation
            brief = {
                "date": "2026-03-10",
                "event_count": len(loaded_events),
                "event_types": list({e["event_type"] for e in loaded_events}),
                "summary": f"Processed {len(loaded_events)} events for 2026-03-10",
            }
            assert brief["event_count"] == 3
            assert "ncl.screentime.total" in brief["event_types"]
