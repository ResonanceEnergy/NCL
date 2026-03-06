"""Negative / edge-case tests for ncl_memory.py (MemoryUnit, MemoryStorage)."""

import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

from ncl_memory import MemoryStorage, MemoryUnit

# ---------------------------------------------------------------------------
#  MemoryUnit.from_dict — missing / malformed data
# ---------------------------------------------------------------------------

def _valid_unit_dict(**overrides):
    base = {
        "id": "mem-001",
        "content": "test content",
        "memory_type": "episodic",
        "timestamp": "2026-01-15T10:00:00",
    }
    base.update(overrides)
    return base


class TestMemoryUnitFromDictNegative:
    """Edge-case inputs for MemoryUnit.from_dict."""

    def test_missing_id(self):
        d = _valid_unit_dict()
        del d["id"]
        with pytest.raises(ValueError, match="id"):
            MemoryUnit.from_dict(d)

    def test_missing_content(self):
        d = _valid_unit_dict()
        del d["content"]
        with pytest.raises(ValueError, match="content"):
            MemoryUnit.from_dict(d)

    def test_missing_memory_type(self):
        d = _valid_unit_dict()
        del d["memory_type"]
        with pytest.raises(ValueError, match="memory_type"):
            MemoryUnit.from_dict(d)

    def test_missing_timestamp(self):
        d = _valid_unit_dict()
        del d["timestamp"]
        with pytest.raises(ValueError, match="timestamp"):
            MemoryUnit.from_dict(d)

    def test_invalid_timestamp_format(self):
        with pytest.raises(ValueError):
            MemoryUnit.from_dict(_valid_unit_dict(timestamp="not-a-date"))

    def test_invalid_last_accessed_format(self):
        with pytest.raises(ValueError):
            MemoryUnit.from_dict(_valid_unit_dict(last_accessed="2026-13-45T99:99:99"))

    def test_null_content(self):
        # content=None is accepted (not type-checked by from_dict)
        unit = MemoryUnit.from_dict(_valid_unit_dict(content=None))
        assert unit.content is None

    def test_extreme_importance_high(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(importance=99.9))
        assert unit.importance == 99.9  # No clamping in current impl

    def test_negative_importance(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(importance=-5.0))
        assert unit.importance == -5.0  # No clamping in current impl

    def test_nan_importance(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(importance=float("nan")))
        import math
        assert math.isnan(unit.importance)

    def test_access_count_non_numeric(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(access_count="abc"))
        assert unit.access_count == 0  # Falls through to except

    def test_importance_non_numeric(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(importance="very_high"))
        assert unit.importance == 1.0  # Falls through to except default

    def test_tags_as_dict(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(tags={"a": 1}))
        assert unit.tags == []

    def test_context_as_list(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(context=[1, 2, 3]))
        assert unit.context == {}

    def test_id_coerced_to_string(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(id=12345))
        assert unit.id == "12345"

    def test_source_none(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(source=None))
        assert unit.source == "system"

    def test_consolidated_truthy(self):
        unit = MemoryUnit.from_dict(_valid_unit_dict(consolidated="yes"))
        assert unit.consolidated is True

    def test_empty_dict_raises(self):
        with pytest.raises(ValueError):
            MemoryUnit.from_dict({})


# ---------------------------------------------------------------------------
#  MemoryStorage — store / retrieve edge cases
# ---------------------------------------------------------------------------

@pytest.fixture()
def storage(tmp_path):
    return MemoryStorage(str(tmp_path / "mem"))


def _make_unit(uid="m-1", content="test", importance=0.5):
    unit = MemoryUnit(content=content, memory_type="episodic")
    unit.id = uid
    unit.importance = importance
    return unit


class TestMemoryStorageNegative:
    """Edge-case tests for MemoryStorage."""

    def test_store_and_retrieve_special_chars(self, storage):
        unit = _make_unit(content='quote"backslash\\null\x00tab\t')
        storage.store_short_term(unit)
        retrieved = storage.retrieve_short_term(unit.id)
        assert retrieved is not None
        assert "quote" in retrieved.content

    def test_store_unicode_emoji(self, storage):
        unit = _make_unit(content="hello 🌍🔥 world")
        storage.store_short_term(unit)
        retrieved = storage.retrieve_short_term(unit.id)
        assert "🌍" in retrieved.content

    def test_retrieve_nonexistent(self, storage):
        assert storage.retrieve_short_term("nonexistent-id") is None
        assert storage.retrieve_long_term("nonexistent-id") is None

    def test_retrieve_working_nonexistent(self, storage):
        assert storage.retrieve_working_memory("nonexistent-id") is None

    def test_working_memory_eviction(self, storage):
        storage.working_memory_limit = 3
        for i in range(5):
            storage.store_working_memory(_make_unit(uid=f"m-{i}"))
        # Only last 3 should remain
        assert len(storage.working_memory) == 3
        assert storage.retrieve_working_memory("m-0") is None
        assert storage.retrieve_working_memory("m-1") is None
        assert storage.retrieve_working_memory("m-4") is not None

    def test_store_duplicate_id_replaces(self, storage):
        storage.store_short_term(_make_unit(uid="dup", content="first"))
        storage.store_short_term(_make_unit(uid="dup", content="second"))
        retrieved = storage.retrieve_short_term("dup")
        assert retrieved.content == "second"

    def test_search_with_unknown_field_ignored(self, storage):
        storage.store_short_term(_make_unit())
        results = storage.search_short_term({"nonexistent_field": "val"})
        assert len(results) >= 1  # Unknown fields ignored, returns all

    def test_search_with_memory_type_exact(self, storage):
        storage.store_short_term(_make_unit())
        # Wildcard should NOT match (parameterised query, not LIKE)
        results = storage.search_short_term({"memory_type": "epi%"})
        assert len(results) == 0

    def test_search_limit_zero(self, storage):
        storage.store_short_term(_make_unit())
        results = storage.search_short_term({}, limit=0)
        assert len(results) == 0

    def test_consolidate_with_no_qualifying(self, storage):
        unit = _make_unit(importance=0.1)
        storage.store_short_term(unit)
        count = storage.consolidate_memories(threshold_days=0, min_importance=0.9)
        assert count == 0

    def test_consolidate_moves_to_long_term(self, storage):
        unit = _make_unit(importance=0.9)
        # Backdate the timestamp so it qualifies for consolidation
        unit.timestamp = datetime.now() - timedelta(days=30)
        storage.store_short_term(unit)
        count = storage.consolidate_memories(threshold_days=7, min_importance=0.5)
        assert count == 1
        # Verify it's now in long-term and removed from short-term
        assert storage.retrieve_short_term(unit.id) is None
        assert storage.retrieve_long_term(unit.id) is not None

    def test_prune_no_action_when_under_limit(self, storage):
        storage.store_short_term(_make_unit())
        storage.prune_memories(max_short_term=100, max_long_term=100)
        # Should still be there
        assert storage.retrieve_short_term("m-1") is not None

    def test_prune_removes_least_important(self, storage):
        for i in range(5):
            storage.store_short_term(_make_unit(uid=f"m-{i}", importance=i * 0.1))
        storage.prune_memories(max_short_term=2, max_long_term=100)
        results = storage.search_short_term({})
        assert len(results) == 2
        # Should keep highest importance ones
        importances = [r.importance for r in results]
        assert min(importances) >= 0.3

    def test_prune_long_term(self, storage):
        for i in range(5):
            unit = _make_unit(uid=f"lt-{i}", importance=i * 0.1)
            storage.store_long_term(unit)
        storage.prune_memories(max_short_term=100, max_long_term=2)
        conn = sqlite3.connect(str(storage.long_term_db))
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()
        assert count == 2


# ---------------------------------------------------------------------------
#  Concurrent SQLite writes
# ---------------------------------------------------------------------------

class TestConcurrentWrites:
    """Test that concurrent writes don't corrupt the database."""

    def test_concurrent_short_term_writes(self, storage):
        errors = []

        def writer(start_id, count):
            try:
                for i in range(count):
                    storage.store_short_term(_make_unit(uid=f"thread-{start_id}-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t, 20)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No exceptions
        assert len(errors) == 0

        # All records should be present
        conn = sqlite3.connect(str(storage.short_term_db))
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()
        assert count == 80  # 4 threads x 20 writes


# ---------------------------------------------------------------------------
#  RateLimiter edge cases
# ---------------------------------------------------------------------------

from ncl_agency_runtime.runtime.relay_server import RateLimiter  # noqa: E402


class TestRateLimiterNegative:
    """Edge-case inputs for RateLimiter."""

    def test_zero_limit_blocks_first_call(self):
        rl = RateLimiter(events_per_minute=0)
        assert rl.allow_event("1.2.3.4") is False

    def test_limit_one_allows_first_blocks_second(self):
        rl = RateLimiter(events_per_minute=1)
        assert rl.allow_event("1.2.3.4") is True
        assert rl.allow_event("1.2.3.4") is False

    def test_different_ips_independent(self):
        rl = RateLimiter(events_per_minute=1)
        assert rl.allow_event("1.1.1.1") is True
        assert rl.allow_event("2.2.2.2") is True
        assert rl.allow_event("1.1.1.1") is False

    def test_api_limit_separate_from_event(self):
        rl = RateLimiter(events_per_minute=1, api_calls_per_minute=1)
        assert rl.allow_event("1.1.1.1") is True
        assert rl.allow_api("1.1.1.1") is True
        assert rl.allow_event("1.1.1.1") is False
        assert rl.allow_api("1.1.1.1") is False
