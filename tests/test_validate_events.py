import json
import os
import tempfile
import pytest
from tools.validate_events import load_catalog, load_schema_for_event_type, validate_instance


def test_load_catalog():
    catalog = load_catalog()
    assert isinstance(catalog, dict)
    assert 'ncl.screentime.total' in catalog


def test_load_schema_for_event_type():
    catalog = load_catalog()
    schema, path = load_schema_for_event_type('ncl.screentime.total', catalog)
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
    with open(envelope_path, 'r', encoding='utf-8') as f:
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
    with open(envelope_path, 'r', encoding='utf-8') as f:
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