"""Negative / edge-case tests for lib_ncl helpers (validate_minimal, day_file, append_ndjson)."""

import json

import pytest

from ncl_agency_runtime.runtime.lib_ncl import append_ndjson, day_file, validate_minimal

# ---------------------------------------------------------------------------
#  validate_minimal — boundary / malicious inputs
# ---------------------------------------------------------------------------

def _valid_event(**overrides):
    """Return a minimal valid event dict, with optional overrides."""
    base = {
        "schema_version": "ncl.event.v1",
        "event_id": "e-001",
        "event_type": "ncl.test.ping",
        "occurred_at": "2026-01-15T10:00:00",
        "source": {"device": "iPhone", "origin": "shortcut"},
        "privacy": {"level": "P3"},
        "payload": {"msg": "hello"},
    }
    base.update(overrides)
    return base


class TestValidateMinimalNegative:
    """Edge-case inputs for validate_minimal."""

    # --- required key variants ---
    @pytest.mark.parametrize("key", [
        "schema_version", "event_id", "event_type",
        "occurred_at", "source", "privacy", "payload",
    ])
    def test_missing_required_field(self, key):
        evt = _valid_event()
        del evt[key]
        ok, reason = validate_minimal(evt)
        assert not ok
        assert f"missing:{key}" == reason

    # --- null / None in required fields ---
    def test_null_schema_version(self):
        ok, reason = validate_minimal(_valid_event(schema_version=None))
        assert not ok
        assert reason == "bad_schema_version"

    def test_null_source(self):
        ok, reason = validate_minimal(_valid_event(source=None))
        assert not ok
        assert reason == "bad_source"

    def test_null_privacy(self):
        ok, reason = validate_minimal(_valid_event(privacy=None))
        assert not ok
        assert reason == "bad_privacy"

    def test_null_payload(self):
        ok, reason = validate_minimal(_valid_event(payload=None))
        assert not ok
        assert reason == "bad_payload"

    # --- wrong types ---
    def test_source_is_string(self):
        ok, reason = validate_minimal(_valid_event(source="iPhone"))
        assert not ok
        assert reason == "bad_source"

    def test_privacy_is_string(self):
        ok, reason = validate_minimal(_valid_event(privacy="P3"))
        assert not ok
        assert reason == "bad_privacy"

    def test_payload_is_list(self):
        ok, reason = validate_minimal(_valid_event(payload=[1, 2, 3]))
        assert not ok
        assert reason == "bad_payload"

    # --- partial source / privacy ---
    def test_source_missing_device(self):
        ok, reason = validate_minimal(_valid_event(source={"origin": "shortcut"}))
        assert not ok
        assert reason == "bad_source"

    def test_source_missing_origin(self):
        ok, reason = validate_minimal(_valid_event(source={"device": "iPhone"}))
        assert not ok
        assert reason == "bad_source"

    def test_privacy_missing_level(self):
        ok, reason = validate_minimal(_valid_event(privacy={"retention": "7d"}))
        assert not ok
        assert reason == "bad_privacy"

    def test_privacy_invalid_level(self):
        ok, reason = validate_minimal(_valid_event(privacy={"level": "P4"}))
        assert not ok
        assert reason == "bad_privacy"

    def test_privacy_level_lowercase(self):
        ok, reason = validate_minimal(_valid_event(privacy={"level": "p0"}))
        assert not ok
        assert reason == "bad_privacy"

    # --- valid edge cases (should pass) ---
    def test_extra_fields_accepted(self):
        ok, _reason = validate_minimal(_valid_event(extra="stuff"))
        assert ok

    def test_empty_payload_dict(self):
        ok, _reason = validate_minimal(_valid_event(payload={}))
        assert ok


# ---------------------------------------------------------------------------
#  day_file — edge-case dates
# ---------------------------------------------------------------------------

class TestDayFileNegative:
    """Edge-case inputs for day_file."""

    def test_malformed_iso(self, tmp_path):
        # Should fallback to today
        result = day_file(tmp_path, "not-a-date")
        assert result.suffix == ".ndjson"
        assert result.parent == tmp_path

    def test_very_old_date(self, tmp_path):
        result = day_file(tmp_path, "1960-01-01T00:00:00")
        assert "1960-01-01" in result.name

    def test_far_future_date(self, tmp_path):
        result = day_file(tmp_path, "9999-12-31T23:59:59")
        assert "9999-12-31" in result.name

    def test_timezone_aware(self, tmp_path):
        result = day_file(tmp_path, "2026-06-15T12:00:00+05:30")
        assert result.suffix == ".ndjson"

    def test_empty_string(self, tmp_path):
        result = day_file(tmp_path, "")
        assert result.suffix == ".ndjson"


# ---------------------------------------------------------------------------
#  append_ndjson — edge cases
# ---------------------------------------------------------------------------

class TestAppendNdjsonNegative:
    """Edge-case content for append_ndjson."""

    def test_unicode_emoji(self, tmp_path):
        p = tmp_path / "test.ndjson"
        append_ndjson(p, {"msg": "hello 🌍🔥"})
        line = p.read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert obj["msg"] == "hello 🌍🔥"

    def test_special_characters(self, tmp_path):
        p = tmp_path / "test.ndjson"
        append_ndjson(p, {"data": 'quote"backslash\\newline\ntab\t'})
        line = p.read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert "quote" in obj["data"]

    def test_empty_dict(self, tmp_path):
        p = tmp_path / "test.ndjson"
        append_ndjson(p, {})
        line = p.read_text(encoding="utf-8").strip()
        assert json.loads(line) == {}

    def test_nested_deep_structure(self, tmp_path):
        p = tmp_path / "test.ndjson"
        nested = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        append_ndjson(p, nested)
        line = p.read_text(encoding="utf-8").strip()
        assert json.loads(line) == nested

    def test_multiple_appends(self, tmp_path):
        p = tmp_path / "test.ndjson"
        for i in range(5):
            append_ndjson(p, {"i": i})
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5
