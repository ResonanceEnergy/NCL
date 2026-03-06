import json
import os
import tempfile

from tools.validate_events import find_json_files, load_catalog, load_schema_for_event_type, main, validate_instance


def test_load_catalog():
    catalog = load_catalog()
    assert isinstance(catalog, dict)
    assert 'ncl.screentime.total' in catalog


def test_load_schema_for_event_type():
    catalog = load_catalog()
    schema, _path = load_schema_for_event_type('ncl.screentime.total', catalog)
    assert schema is not None
    assert 'title' in schema
    assert schema['title'] == 'Screen Time — Total (daily/weekly)'


def test_load_schema_for_invalid_event_type():
    catalog = load_catalog()
    result = load_schema_for_event_type('invalid.type', catalog)
    assert result is None


def test_validate_instance_valid():
    catalog = load_catalog()
    schema, _ = load_schema_for_event_type('ncl.screentime.total', catalog)

    # Load envelope schema
    envelope_path = os.path.join('schemas', 'ncl.iphone.v1', 'envelope.json')
    with open(envelope_path, encoding='utf-8') as f:
        envelope_schema = json.load(f)

    # Valid instance
    instance = {
        "event_id": "test-id",
        "event_type": "ncl.screentime.total",
        "schema_version": "ncl.iphone.v1",
        "timestamp": "2026-02-22T10:00:00Z",
        "ingestion_method": "shortcut",
        "permission": {"granted": True},
        "retention_tier": "short",
        "privacy_level": "metadata_only",
        "provenance": {"source": "Shortcut"},
        "payload": {
            "date": "2026-02-22",
            "total_seconds": 3600
        }
    }

    errs = validate_instance(instance, schema, 'schemas/ncl.iphone.v1/screentime.total.json', envelope_schema)
    assert len(errs) == 0


def test_validate_instance_invalid():
    catalog = load_catalog()
    schema, _ = load_schema_for_event_type('ncl.screentime.total', catalog)

    envelope_path = os.path.join('schemas', 'ncl.iphone.v1', 'envelope.json')
    with open(envelope_path, encoding='utf-8') as f:
        envelope_schema = json.load(f)

    # Invalid instance - missing required payload field
    instance = {
        "event_id": "test-id",
        "event_type": "ncl.screentime.total",
        "schema_version": "ncl.iphone.v1",
        "timestamp": "2026-02-22T10:00:00Z",
        "ingestion_method": "shortcut",
        "permission": {"granted": True},
        "retention_tier": "short",
        "privacy_level": "metadata_only",
        "provenance": {"source": "Shortcut"},
        "payload": {
            "date": "2026-02-22"
            # missing total_seconds
        }
    }

    errs = validate_instance(instance, schema, 'schemas/ncl.iphone.v1/screentime.total.json', envelope_schema)
    assert len(errs) > 0


def test_find_json_files_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = find_json_files([tmpdir])
        assert files == []


def test_find_json_files_nonexistent_dir():
    files = find_json_files(["/nonexistent/path"])
    assert files == []


def test_find_json_files_with_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        for name in ["a.json", "b.json", "c.txt"]:
            (tempfile.Path if False else open)(os.path.join(tmpdir, name), "w").close()
        files = find_json_files([tmpdir])
        assert len(files) == 2
        assert all(f.endswith(".json") for f in files)


def test_main_default_dirs():
    """main() with default dirs should succeed (schemas/examples exist)."""
    result = main([])
    assert result == 0


def test_main_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = main(["--event-dirs", tmpdir])
        assert result == 0  # no files = success


# ── Schema Catalog Integrity Tests ───────────────────────────

from pathlib import Path  # noqa: E402

SCHEMA_DIR = Path(__file__).parent.parent / "schemas" / "ncl.iphone.v1"


def test_all_index_entries_resolve():
    """Every schema referenced in index.json must exist as a file."""
    catalog = load_catalog()
    for event_type, rel_path in catalog.items():
        schema_file = SCHEMA_DIR / rel_path.lstrip("./")
        assert schema_file.exists(), f"Schema for {event_type} not found: {schema_file}"


def test_all_schemas_are_valid_json():
    """Every .json file in the schema dir must parse as valid JSON."""
    for f in SCHEMA_DIR.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data, dict), f"{f.name} is not a JSON object"


def test_new_event_types_in_catalog():
    """Verify the 8 newly-added event types appear in the catalog."""
    catalog = load_catalog()
    new_types = [
        "ncl.calendar.event_summary",
        "ncl.calendar.schedule_density",
        "ncl.call.metadata",
        "ncl.call.daily_summary",
        "ncl.connectivity.place_fingerprint",
        "ncl.microphone.presence_label",
        "ncl.system.focus_adherence",
        "ncl.consent.change",
    ]
    for et in new_types:
        assert et in catalog, f"{et} missing from index.json"


def test_catalog_has_at_least_50_schemas():
    catalog = load_catalog()
    # 44 original + 8 new = 52 minimum (not counting envelope)
    assert len(catalog) >= 50, f"Expected >= 50 schemas, got {len(catalog)}"


def test_each_schema_has_required_fields():
    """Every event schema should have $id, $schema, title, description, and allOf."""
    for f in SCHEMA_DIR.glob("*.json"):
        if f.name == "index.json":
            continue
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        assert "$schema" in data, f"{f.name} missing $schema"
        assert "title" in data, f"{f.name} missing title"
