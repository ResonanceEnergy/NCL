#!/usr/bin/env python3
"""
Tests for tools/import_data.py — dedup, merge, dry-run, zip handling.
"""
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from import_data import import_data, load_existing_event_ids


class TestLoadExistingEventIds(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.event_dir = Path(self.tmpdir) / "event_log"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_dir(self):
        self.event_dir.mkdir(parents=True)
        ids = load_existing_event_ids(self.event_dir)
        self.assertEqual(ids, set())

    def test_nonexistent_dir(self):
        ids = load_existing_event_ids(Path(self.tmpdir) / "nope")
        self.assertEqual(ids, set())

    def test_loads_event_ids(self):
        self.event_dir.mkdir(parents=True)
        events = [json.dumps({"event_id": f"e-{i}"}) for i in range(3)]
        (self.event_dir / "day.ndjson").write_text("\n".join(events))
        ids = load_existing_event_ids(self.event_dir)
        self.assertEqual(ids, {"e-0", "e-1", "e-2"})

    def test_skips_malformed_json(self):
        self.event_dir.mkdir(parents=True)
        (self.event_dir / "day.ndjson").write_text('{"event_id":"ok"}\nNOT JSON\n')
        ids = load_existing_event_ids(self.event_dir)
        self.assertEqual(ids, {"ok"})


class TestImportData(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ncl_root = Path(self.tmpdir) / "NCL"
        self.ncl_root.mkdir(parents=True)
        self.archive_path = Path(self.tmpdir) / "test_import.zip"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_archive(self, events=None, memory_files=None, manifest=None):
        with zipfile.ZipFile(self.archive_path, "w") as zf:
            if manifest:
                zf.writestr("manifest.json", json.dumps(manifest))
            if events:
                for name, content in events.items():
                    zf.writestr(f"events/{name}", content)
            if memory_files:
                for name, content in memory_files.items():
                    zf.writestr(f"memory/{name}", content)

    def test_import_nonexistent_archive(self):
        result = import_data(Path("/tmp/nofile.zip"), self.ncl_root)
        self.assertIsNone(result)

    def test_import_events(self):
        events_content = json.dumps({"event_id": "e1", "data": "test"}) + "\n"
        self._create_archive(events={"2025-01-01.ndjson": events_content})
        stats = import_data(self.archive_path, self.ncl_root)
        self.assertEqual(stats["events_imported"], 1)
        self.assertEqual(stats["events_skipped"], 0)

    def test_import_dedup(self):
        # Pre-populate existing event
        event_dir = self.ncl_root / "data" / "event_log"
        event_dir.mkdir(parents=True)
        (event_dir / "2025-01-01.ndjson").write_text(json.dumps({"event_id": "e1"}) + "\n")

        # Archive with same event_id
        events_content = json.dumps({"event_id": "e1"}) + "\n" + json.dumps({"event_id": "e2"}) + "\n"
        self._create_archive(events={"2025-01-01.ndjson": events_content})
        stats = import_data(self.archive_path, self.ncl_root)
        self.assertEqual(stats["events_imported"], 1)
        self.assertEqual(stats["events_skipped"], 1)

    def test_dry_run(self):
        events_content = json.dumps({"event_id": "e1"}) + "\n"
        self._create_archive(events={"day.ndjson": events_content})
        stats = import_data(self.archive_path, self.ncl_root, dry_run=True)
        self.assertEqual(stats["events_imported"], 1)
        # Verify nothing was actually written
        event_dir = self.ncl_root / "data" / "event_log"
        self.assertFalse(event_dir.exists())

    def test_import_memory_files(self):
        self._create_archive(memory_files={"index.json": '{"test": true}'})
        stats = import_data(self.archive_path, self.ncl_root)
        self.assertEqual(stats["memory_files"], 1)
        target = self.ncl_root / "memory" / "index.json"
        self.assertTrue(target.exists())

    def test_skip_events_flag(self):
        events_content = json.dumps({"event_id": "e1"}) + "\n"
        self._create_archive(events={"day.ndjson": events_content})
        stats = import_data(self.archive_path, self.ncl_root, import_events=False)
        self.assertEqual(stats["events_imported"], 0)

    def test_manifest_read(self):
        self._create_archive(manifest={
            "export_version": "1.0",
            "exported_at": "2025-01-01T00:00:00",
            "ncl_version": "3.0",
            "anonymized": True,
        })
        stats = import_data(self.archive_path, self.ncl_root)
        self.assertIsNotNone(stats)


if __name__ == "__main__":
    unittest.main()
