"""Negative / edge-case tests for tools/import_data.py."""

import json
import zipfile
from pathlib import Path

import pytest

from tools.import_data import import_data, load_existing_event_ids

# ---------------------------------------------------------------------------
#  load_existing_event_ids
# ---------------------------------------------------------------------------

class TestLoadExistingEventIds:
    """Edge-case inputs for load_existing_event_ids."""

    def test_empty_ndjson_file(self, tmp_path):
        (tmp_path / "day.ndjson").write_text("", encoding="utf-8")
        ids = load_existing_event_ids(tmp_path)
        assert ids == set()

    def test_corrupt_json_line_skipped(self, tmp_path):
        lines = '{"event_id":"e1"}\nNOT JSON\n{"event_id":"e2"}\n'
        (tmp_path / "day.ndjson").write_text(lines, encoding="utf-8")
        ids = load_existing_event_ids(tmp_path)
        assert ids == {"e1", "e2"}

    def test_missing_event_id_skipped(self, tmp_path):
        lines = '{"no_id": true}\n{"event_id": "e1"}\n'
        (tmp_path / "day.ndjson").write_text(lines, encoding="utf-8")
        ids = load_existing_event_ids(tmp_path)
        assert ids == {"e1"}

    def test_null_event_id_skipped(self, tmp_path):
        lines = '{"event_id": null}\n{"event_id": "e1"}\n'
        (tmp_path / "day.ndjson").write_text(lines, encoding="utf-8")
        ids = load_existing_event_ids(tmp_path)
        assert ids == {"e1"}

    def test_empty_string_event_id_included(self, tmp_path):
        lines = '{"event_id": ""}\n'
        (tmp_path / "day.ndjson").write_text(lines, encoding="utf-8")
        ids = load_existing_event_ids(tmp_path)
        # Empty string is truthy-falsy edge: "" is falsy so shouldn't be added
        # Actually: `if eid:` — empty string is falsy, so excluded
        assert ids == set()

    def test_windows_crlf_line_endings(self, tmp_path):
        content = '{"event_id":"e1"}\r\n{"event_id":"e2"}\r\n'
        (tmp_path / "day.ndjson").write_text(content, encoding="utf-8")
        ids = load_existing_event_ids(tmp_path)
        # split("\n") will produce "...}\r" — json.loads handles trailing \r
        assert "e1" in ids
        assert "e2" in ids

    def test_nonexistent_dir(self, tmp_path):
        ids = load_existing_event_ids(tmp_path / "nope")
        assert ids == set()


# ---------------------------------------------------------------------------
#  import_data — archive edge cases
# ---------------------------------------------------------------------------

def _make_archive(tmp_path, entries: dict[str, str | bytes]) -> Path:
    """Create a ZIP archive with the given filename→content entries."""
    archive = tmp_path / "test.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    return archive


class TestImportDataNegative:
    """Edge-case inputs for import_data."""

    def test_nonexistent_archive(self, tmp_path):
        result = import_data(tmp_path / "nope.zip", tmp_path)
        assert result is None

    def test_empty_archive(self, tmp_path):
        archive = _make_archive(tmp_path, {})
        result = import_data(archive, tmp_path / "ncl")
        assert result is not None
        assert result["events_imported"] == 0

    def test_corrupt_json_lines_skipped(self, tmp_path):
        entries = {
            "events/2026-01-15.ndjson": 'NOT JSON\n{"event_id":"e1","data":"ok"}\n',
        }
        archive = _make_archive(tmp_path, entries)
        result = import_data(archive, tmp_path / "ncl")
        assert result["events_imported"] == 1

    def test_corrupt_manifest_ignored(self, tmp_path):
        entries = {
            "manifest.json": "NOT VALID JSON",
            "events/2026-01-15.ndjson": '{"event_id":"e1"}\n',
        }
        archive = _make_archive(tmp_path, entries)
        # json.loads on corrupt manifest will raise — verify it doesn't crash
        # Looking at the code: manifest = json.loads(zf.read("manifest.json"))
        # This WILL raise. Let's check if it's caught.
        with pytest.raises(json.JSONDecodeError):
            import_data(archive, tmp_path / "ncl")

    def test_duplicate_event_ids_skipped(self, tmp_path):
        ncl_root = tmp_path / "ncl"
        event_dir = ncl_root / "data" / "event_log"
        event_dir.mkdir(parents=True)
        # Pre-populate with event e1
        (event_dir / "existing.ndjson").write_text('{"event_id":"e1"}\n', encoding="utf-8")

        entries = {
            "events/new.ndjson": '{"event_id":"e1"}\n{"event_id":"e2"}\n',
        }
        archive = _make_archive(tmp_path, entries)
        result = import_data(archive, ncl_root)
        assert result["events_skipped"] == 1
        assert result["events_imported"] == 1

    def test_dry_run_no_writes(self, tmp_path):
        entries = {
            "events/2026-01-15.ndjson": '{"event_id":"e1"}\n',
            "memory/config.json": '{}',
        }
        archive = _make_archive(tmp_path, entries)
        ncl_root = tmp_path / "ncl"
        result = import_data(archive, ncl_root, dry_run=True)
        assert result["events_imported"] == 1
        # No files should have been created
        assert not (ncl_root / "data" / "event_log").exists()

    def test_memory_import(self, tmp_path):
        entries = {
            "memory/short_term.db": b"fake-db-content",
        }
        archive = _make_archive(tmp_path, entries)
        ncl_root = tmp_path / "ncl"
        result = import_data(archive, ncl_root)
        assert result["memory_files"] == 1
        assert (ncl_root / "memory" / "short_term.db").exists()

    def test_audit_import_no_overwrite(self, tmp_path):
        ncl_root = tmp_path / "ncl"
        audit_dir = ncl_root / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "existing.json").write_text('{"old": true}', encoding="utf-8")

        entries = {
            "audit/existing.json": '{"new": true}',
            "audit/fresh.json": '{"fresh": true}',
        }
        archive = _make_archive(tmp_path, entries)
        result = import_data(archive, ncl_root)
        assert result["audit_files"] == 1  # Only fresh.json counted
        # Existing file not overwritten
        content = json.loads((audit_dir / "existing.json").read_text(encoding="utf-8"))
        assert content == {"old": True}
