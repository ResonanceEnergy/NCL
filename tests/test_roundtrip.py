"""Phase 2 — Import / export round-trip tests.

Export all data → wipe → import → verify identical state.
Tests the full lifecycle through export_data() and import_data().
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.export import anonymize_event, export_data
from tools.import_data import import_data, load_existing_event_ids


class TestExportImportRoundtrip:
    """Full round-trip: populate → export → wipe → import → verify."""

    def setup_method(self):
        self.root = Path(tempfile.mkdtemp())
        self.archive = self.root / "export.zip"

    def teardown_method(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _populate_ncl_tree(self, root: Path, event_count: int = 5):
        """Create a realistic NCL directory tree with events, memory, audit, reports."""
        event_dir = root / "data" / "event_log"
        event_dir.mkdir(parents=True)
        memory_dir = root / "memory"
        memory_dir.mkdir(parents=True)
        audit_dir = root / "audit"
        audit_dir.mkdir(parents=True)
        report_dir = root / "dist" / "reports"
        report_dir.mkdir(parents=True)

        # Write NDJSON events
        lines = []
        for i in range(event_count):
            evt = {
                "event_id": f"evt-{i:04d}",
                "event_type": "test.event",
                "occurred_at": f"2025-06-{15 + i % 10:02d}T10:00:00",
                "payload": {"index": i, "note": f"event number {i}"},
                "source": {"device": "test"},
                "privacy": {"level": "P3"},
            }
            lines.append(json.dumps(evt))
        (event_dir / "2025-06-15.ndjson").write_text("\n".join(lines), encoding="utf-8")

        # Write memory file
        mem_data = {"short_term": [{"id": "m1", "content": "test memory"}]}
        (memory_dir / "memories.json").write_text(json.dumps(mem_data), encoding="utf-8")

        # Write audit file
        audit = {"action": "import", "timestamp": "2025-06-15T12:00:00"}
        (audit_dir / "audit_001.json").write_text(json.dumps(audit), encoding="utf-8")

        # Write report
        (report_dir / "weekly.md").write_text("# Weekly Report\nAll good.", encoding="utf-8")

    def test_full_roundtrip_no_anonymize(self):
        """Export → wipe → import → verify identical event content."""
        src = self.root / "src_ncl"
        self._populate_ncl_tree(src, event_count=3)

        # Export
        manifest = export_data(src, self.archive, anonymize=False)
        assert manifest["contents"]["events"] == 3
        assert manifest["contents"]["memory_files"] == 1
        assert manifest["contents"]["audit"] == 1
        assert manifest["contents"]["reports"] == 1

        # Wipe source
        shutil.rmtree(src)
        assert not src.exists()

        # Import into fresh root
        dst = self.root / "dst_ncl"
        stats = import_data(self.archive, dst)
        assert stats is not None
        assert stats["events_imported"] == 3
        assert stats["memory_files"] == 1
        assert stats["audit_files"] == 1
        assert stats["reports"] == 1

        # Verify event content
        ndjson = dst / "data" / "event_log" / "2025-06-15.ndjson"
        assert ndjson.exists()
        events = [json.loads(line) for line in ndjson.read_text(encoding="utf-8").strip().split("\n")]
        assert len(events) == 3
        assert events[0]["event_id"] == "evt-0000"

        # Verify memory file content
        mem_file = dst / "memory" / "memories.json"
        assert mem_file.exists()
        mem_data = json.loads(mem_file.read_text(encoding="utf-8"))
        assert mem_data["short_term"][0]["id"] == "m1"

        # Verify audit
        audit_file = dst / "audit" / "audit_001.json"
        assert audit_file.exists()

        # Verify report
        report_file = dst / "dist" / "reports" / "weekly.md"
        assert report_file.exists()
        assert "Weekly Report" in report_file.read_text(encoding="utf-8")

    def test_roundtrip_with_anonymization(self):
        """Anonymized export still imports correctly (PII replaced, not lost)."""
        src = self.root / "src_anon"
        self._populate_ncl_tree(src, event_count=2)

        # Add PII to event
        event_dir = src / "data" / "event_log"
        pii_event = {
            "event_id": "pii-001",
            "event_type": "contact.created",
            "payload": {"name": "John Doe", "email": "john@example.com", "note": "safe"},
            "source": {"device": "iphone", "ip_address": "192.168.1.1"},
            "privacy": {"level": "P3"},
        }
        with open(event_dir / "2025-06-20.ndjson", "w", encoding="utf-8") as f:
            f.write(json.dumps(pii_event) + "\n")

        # Export with anonymization
        manifest = export_data(src, self.archive, anonymize=True)
        assert manifest["anonymized"] is True

        # Import
        dst = self.root / "dst_anon"
        stats = import_data(self.archive, dst)
        assert stats is not None

        # Verify PII fields are redacted
        ndjson = dst / "data" / "event_log" / "2025-06-20.ndjson"
        imported_events = [json.loads(ln) for ln in ndjson.read_text(encoding="utf-8").strip().split("\n")]
        pii_evt = imported_events[0]
        assert pii_evt["payload"]["name"].startswith("[REDACTED-")
        assert pii_evt["payload"]["email"].startswith("[REDACTED-")
        # IP should be stripped from source
        assert "ip_address" not in pii_evt.get("source", {})
        # Non-PII field preserved
        assert pii_evt["payload"]["note"] == "safe"

    def test_roundtrip_dedup_on_reimport(self):
        """Re-importing the same archive skips duplicate events."""
        src = self.root / "src_dedup"
        self._populate_ncl_tree(src, event_count=4)

        export_data(src, self.archive, anonymize=False)

        # First import
        dst = self.root / "dst_dedup"
        stats1 = import_data(self.archive, dst)
        assert stats1["events_imported"] == 4

        # Second import — should skip all
        stats2 = import_data(self.archive, dst)
        assert stats2["events_imported"] == 0
        assert stats2["events_skipped"] == 4

    def test_roundtrip_date_range_filter(self):
        """Export with date range filters events correctly."""
        src = self.root / "src_range"
        event_dir = src / "data" / "event_log"
        event_dir.mkdir(parents=True)
        (src / "memory").mkdir(parents=True)

        # Create events across multiple days
        for day in ["2025-06-10", "2025-06-15", "2025-06-20"]:
            evt = {"event_id": f"evt-{day}", "event_type": "daily", "payload": {}}
            (event_dir / f"{day}.ndjson").write_text(json.dumps(evt), encoding="utf-8")

        manifest = export_data(
            src, self.archive,
            include_memory=False, include_audit=False, include_reports=False,
            anonymize=False, date_from="2025-06-12", date_to="2025-06-18",
        )
        # Only 2025-06-15 should be in range
        assert manifest["contents"]["events"] == 1

        dst = self.root / "dst_range"
        stats = import_data(self.archive, dst)
        assert stats["events_imported"] == 1

    def test_roundtrip_events_only(self):
        """Selective export: events only, no memory/audit/reports."""
        src = self.root / "src_events_only"
        self._populate_ncl_tree(src)

        manifest = export_data(
            src, self.archive,
            include_events=True, include_memory=False,
            include_audit=False, include_reports=False,
            anonymize=False,
        )
        assert manifest["contents"]["events"] == 5
        assert "memory_files" not in manifest["contents"]
        assert "audit" not in manifest["contents"]
        assert "reports" not in manifest["contents"]

    def test_roundtrip_empty_dirs(self):
        """Export from empty NCL root produces valid archive with zero counts."""
        src = self.root / "src_empty"
        src.mkdir()

        manifest = export_data(src, self.archive, anonymize=False)
        assert manifest["contents"]["events"] == 0

        dst = self.root / "dst_empty"
        stats = import_data(self.archive, dst)
        assert stats["events_imported"] == 0

    def test_reimport_preserves_order(self):
        """Events imported maintain original order."""
        src = self.root / "src_order"
        event_dir = src / "data" / "event_log"
        event_dir.mkdir(parents=True)

        lines = []
        for i in range(10):
            lines.append(json.dumps({"event_id": f"ord-{i:03d}", "event_type": "seq", "payload": {"seq": i}}))
        (event_dir / "2025-06-15.ndjson").write_text("\n".join(lines), encoding="utf-8")

        export_data(src, self.archive, anonymize=False,
                    include_memory=False, include_audit=False, include_reports=False)

        dst = self.root / "dst_order"
        import_data(self.archive, dst)

        ndjson = dst / "data" / "event_log" / "2025-06-15.ndjson"
        events = [json.loads(line) for line in ndjson.read_text(encoding="utf-8").strip().split("\n")]
        for i, evt in enumerate(events):
            assert evt["payload"]["seq"] == i


class TestAnonymizeEvent:
    """Test anonymize_event independently."""

    def test_p0_redacts_entire_payload(self):
        """P0 sensitivity strips payload entirely."""
        evt = {"payload": {"name": "John"}, "privacy": {"level": "P0"}}
        clean = anonymize_event(evt)
        assert clean["payload"]["redacted"] is True

    def test_p1_redacts_entire_payload(self):
        """P1 sensitivity strips payload entirely."""
        evt = {"payload": {"data": "secret"}, "privacy": {"level": "P1"}}
        clean = anonymize_event(evt)
        assert clean["payload"]["redacted"] is True

    def test_p3_scrubs_pii_fields(self):
        """P3 event scrubs known PII fields but keeps others."""
        evt = {
            "payload": {"name": "Jane", "email": "j@e.com", "note": "ok"},
            "privacy": {"level": "P3"},
        }
        clean = anonymize_event(evt)
        assert clean["payload"]["name"].startswith("[REDACTED-")
        assert clean["payload"]["email"].startswith("[REDACTED-")
        assert clean["payload"]["note"] == "ok"

    def test_source_ip_removed(self):
        """Source IP fields are stripped."""
        evt = {"source": {"device": "iphone", "ip_address": "10.0.0.1", "ip": "10.0.0.1"}, "privacy": {"level": "P3"}}
        clean = anonymize_event(evt)
        assert "ip_address" not in clean["source"]
        assert "ip" not in clean["source"]
        assert clean["source"]["device"] == "iphone"

    def test_no_privacy_defaults_to_scrub(self):
        """Events without privacy field default to P3 behavior."""
        evt = {"payload": {"name": "Bob"}}
        clean = anonymize_event(evt)
        assert clean["payload"]["name"].startswith("[REDACTED-")


class TestLoadExistingEventIdsRoundtrip:
    """Test load_existing_event_ids with exported data."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ids_from_imported_data(self):
        """IDs loaded after import match original exported IDs."""
        event_dir = self.temp_dir / "events"
        event_dir.mkdir()

        original_ids = set()
        lines = []
        for i in range(20):
            eid = f"round-{i:04d}"
            original_ids.add(eid)
            lines.append(json.dumps({"event_id": eid, "event_type": "test"}))

        (event_dir / "2025-06-15.ndjson").write_text("\n".join(lines), encoding="utf-8")

        loaded = load_existing_event_ids(event_dir)
        assert loaded == original_ids
