"""Negative / edge-case tests for tools/validate_events.py."""

import json
from unittest.mock import patch

from tools.validate_events import find_json_files, load_schema_for_event_type, main, validate_instance

# ---------------------------------------------------------------------------
#  find_json_files edge cases
# ---------------------------------------------------------------------------

class TestFindJsonFilesNegative:
    """Edge-case directory inputs."""

    def test_mixed_valid_and_invalid_dirs(self, tmp_path):
        d = tmp_path / "valid"
        d.mkdir()
        (d / "a.json").write_text("{}", encoding="utf-8")
        result = find_json_files([str(d), str(tmp_path / "nope")])
        assert len(result) == 1

    def test_non_json_files_excluded(self, tmp_path):
        (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
        (tmp_path / "b.ndjson").write_text("{}", encoding="utf-8")
        (tmp_path / "c.json").write_text("{}", encoding="utf-8")
        result = find_json_files([str(tmp_path)])
        assert len(result) == 1
        assert result[0].endswith("c.json")

    def test_empty_list(self):
        assert find_json_files([]) == []


# ---------------------------------------------------------------------------
#  load_schema_for_event_type edge cases
# ---------------------------------------------------------------------------

class TestLoadSchemaEdgeCases:
    """Edge-case event types."""

    def test_unknown_event_type(self):
        catalog = {"ncl.known": "some.json"}
        result = load_schema_for_event_type("ncl.unknown", catalog)
        assert result is None

    def test_empty_catalog(self):
        result = load_schema_for_event_type("anything", {})
        assert result is None


# ---------------------------------------------------------------------------
#  validate_instance edge cases
# ---------------------------------------------------------------------------

class TestValidateInstanceNegative:
    """Edge-case instance data."""

    def test_empty_dict_against_schema(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["event_type"],
            "properties": {"event_type": {"type": "string"}},
        }
        envelope = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": "urn:ncl:envelope", "type": "object"}
        errs = validate_instance({}, schema, "test.json", envelope)
        assert len(errs) > 0

    def test_valid_instance_no_errors(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        envelope = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": "urn:ncl:envelope:v1", "type": "object"}
        errs = validate_instance({"name": "test"}, schema, "test.json", envelope)
        assert len(errs) == 0

    def test_wrong_type_in_field(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        envelope = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": "urn:ncl:envelope:v2", "type": "object"}
        errs = validate_instance({"count": "not_int"}, schema, "test.json", envelope)
        assert len(errs) > 0


# ---------------------------------------------------------------------------
#  main() edge cases
# ---------------------------------------------------------------------------

class TestMainNegative:
    """Edge-case main() scenarios."""

    def test_main_with_corrupt_json_file(self, tmp_path):
        (tmp_path / "bad.json").write_text("NOT JSON", encoding="utf-8")
        with patch("tools.validate_events.load_catalog", return_value={}), \
             patch("tools.validate_events.ENVELOPE_PATH", str(tmp_path / "envelope.json")):
            # Create a fake envelope
            (tmp_path / "envelope.json").write_text('{"$id": "urn:x", "type": "object"}', encoding="utf-8")
            result = main(["--event-dirs", str(tmp_path)])
        assert result == 1

    def test_main_with_missing_event_type(self, tmp_path):
        (tmp_path / "no_type.json").write_text('{"data": 1}', encoding="utf-8")
        with patch("tools.validate_events.load_catalog", return_value={}), \
             patch("tools.validate_events.ENVELOPE_PATH", str(tmp_path / "envelope.json")):
            (tmp_path / "envelope.json").write_text('{"$id": "urn:x", "type": "object"}', encoding="utf-8")
            result = main(["--event-dirs", str(tmp_path)])
        assert result == 1

    def test_main_with_unknown_event_type(self, tmp_path):
        (tmp_path / "unknown.json").write_text('{"event_type": "ncl.nonexistent"}', encoding="utf-8")
        with patch("tools.validate_events.load_catalog", return_value={}), \
             patch("tools.validate_events.ENVELOPE_PATH", str(tmp_path / "envelope.json")):
            (tmp_path / "envelope.json").write_text('{"$id": "urn:x", "type": "object"}', encoding="utf-8")
            result = main(["--event-dirs", str(tmp_path)])
        assert result == 1

    def test_main_empty_dirs(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        envelope_dir = tmp_path / "meta"
        envelope_dir.mkdir()
        (envelope_dir / "envelope.json").write_text('{"$id": "urn:x", "type": "object"}', encoding="utf-8")
        with patch("tools.validate_events.load_catalog", return_value={}), \
             patch("tools.validate_events.ENVELOPE_PATH", str(envelope_dir / "envelope.json")):
            result = main(["--event-dirs", str(events_dir)])
        assert result == 0

    def test_main_with_array_of_events(self, tmp_path):
        events = [{"event_type": "ncl.a"}, {"event_type": "ncl.b"}]
        (tmp_path / "multi.json").write_text(json.dumps(events), encoding="utf-8")
        with patch("tools.validate_events.load_catalog", return_value={}), \
             patch("tools.validate_events.ENVELOPE_PATH", str(tmp_path / "envelope.json")):
            (tmp_path / "envelope.json").write_text('{"$id": "urn:x", "type": "object"}', encoding="utf-8")
            result = main(["--event-dirs", str(tmp_path)])
        assert result == 1  # Unknown event types
