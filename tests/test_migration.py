#!/usr/bin/env python3
"""tests/test_migration.py — Verify memory DB schema stability and migration paths."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── MemoryUnit round-trip ──────────────────────────────────────

def test_memory_unit_round_trip():
    """MemoryUnit.to_dict → from_dict preserves all fields."""
    from ncl_memory import MemoryUnit

    original = MemoryUnit(
        content="test migration",
        memory_type="semantic",
        tags=["migration", "test"],
        context={"source": "ci"},
    )
    original.importance = 0.85
    original.access_count = 3
    original.consolidated = True

    data = original.to_dict()
    restored = MemoryUnit.from_dict(data)

    assert restored.id == original.id
    assert restored.content == original.content
    assert restored.memory_type == original.memory_type
    assert restored.tags == original.tags
    assert restored.context == original.context
    assert restored.importance == pytest.approx(original.importance, abs=0.01)
    assert restored.access_count == original.access_count
    assert restored.consolidated is True
    assert restored.source == "system"


def test_memory_unit_from_dict_missing_keys():
    """from_dict raises ValueError when required keys are missing."""
    from ncl_memory import MemoryUnit

    with pytest.raises(ValueError, match="missing keys"):
        MemoryUnit.from_dict({"content": "hello"})


def test_memory_unit_from_dict_type_coercion():
    """from_dict coerces types safely (str, int, float, bool)."""
    from ncl_memory import MemoryUnit

    data = {
        "id": 12345,  # int, should become str
        "content": "test",
        "memory_type": "episodic",
        "tags": "not_a_list",  # wrong type, should fallback to []
        "context": "not_a_dict",  # wrong type, should fallback to {}
        "timestamp": "2025-01-01T00:00:00",
        "access_count": "5",  # str, should become int 5
        "last_accessed": "2025-01-01T00:00:00",
        "importance": "0.9",  # str, should become float
        "consolidated": 1,  # truthy int
        "source": None,
    }
    unit = MemoryUnit.from_dict(data)
    assert isinstance(unit.id, str)
    assert unit.tags == []
    assert unit.context == {}
    assert unit.access_count == 5
    assert unit.importance == pytest.approx(0.9)
    assert unit.consolidated is True


# ── SQLite schema creation ──────────────────────────────────────

def test_memory_storage_creates_tables():
    """MemoryStorage initialises the expected SQLite tables."""
    from ncl_memory import MemoryStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = MemoryStorage(tmpdir)
        # Check short-term DB has 'memories' table
        conn = sqlite3.connect(str(storage.short_term_db))
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor}
        finally:
            conn.close()
        assert "memories" in tables

        # Check long-term DB has 'memories' table
        conn = sqlite3.connect(str(storage.long_term_db))
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor}
        finally:
            conn.close()
        assert "memories" in tables


def test_memory_storage_store_and_retrieve():
    """Store and retrieve a MemoryUnit through SQLite."""
    from ncl_memory import MemoryStorage, MemoryUnit

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = MemoryStorage(tmpdir)
        mem = MemoryUnit(content="stored item", memory_type="episodic", tags=["t1"])

        storage.store_short_term(mem)

        # Query directly
        conn = sqlite3.connect(str(storage.short_term_db))
        try:
            cursor = conn.execute("SELECT data FROM memories WHERE id = ?", (mem.id,))
            row = cursor.fetchone()
        finally:
            conn.close()
        assert row is not None
        data = json.loads(row[0])
        assert data["content"] == "stored item"
        assert data["tags"] == ["t1"]


def test_memory_storage_idempotent_init():
    """Calling _init_databases twice does not corrupt existing data."""
    from ncl_memory import MemoryStorage, MemoryUnit

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = MemoryStorage(tmpdir)
        mem = MemoryUnit(content="persist", memory_type="semantic")
        storage.store_short_term(mem)

        # Re-initialise
        storage._init_databases()

        conn = sqlite3.connect(str(storage.short_term_db))
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM memories")
            count = cursor.fetchone()[0]
        finally:
            conn.close()
        assert count >= 1


# ── Config defaults ────────────────────────────────────────────

def test_memory_manager_config_fallback():
    """MemoryManager uses sensible defaults when config file is absent."""
    from ncl_memory import MemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, "nonexistent.json")
        with patch.dict(os.environ, {}, clear=False):
            mm = MemoryManager(config_path=cfg_path)
        cfg = mm.config
        assert "memory" in cfg
        assert cfg["memory"]["working_memory_limit"] == 1000
        mm.shutdown()
