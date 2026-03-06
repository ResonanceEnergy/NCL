"""Performance benchmarks for the NCL memory system.

Run with:  python -m pytest tests/test_benchmarks.py --benchmark-only
"""
import pytest

from ncl_memory import MemoryStorage, MemoryUnit


@pytest.fixture()
def storage(tmp_path):
    return MemoryStorage(str(tmp_path / "mem"))


def _make_unit(uid="m-1", content="benchmark test content", importance=0.5):
    unit = MemoryUnit(content=content, memory_type="episodic", tags=["test", "bench"])
    unit.id = uid
    unit.importance = importance
    return unit


class TestMemoryBenchmarks:
    """Benchmark core memory operations."""

    def test_store_short_term(self, benchmark, storage):
        """Benchmark storing a single memory unit."""
        counter = {"i": 0}

        def do_store():
            counter["i"] += 1
            storage.store_short_term(_make_unit(uid=f"bench-{counter['i']}"))

        benchmark(do_store)

    def test_retrieve_short_term(self, benchmark, storage):
        """Benchmark retrieving a memory unit by ID."""
        storage.store_short_term(_make_unit(uid="target"))

        benchmark(storage.retrieve_short_term, "target")

    def test_search_short_term(self, benchmark, storage):
        """Benchmark searching memories."""
        for i in range(100):
            storage.store_short_term(_make_unit(uid=f"s-{i}", importance=i / 100))

        benchmark(storage.search_short_term, {"min_importance": 0.5}, 50)

    def test_store_and_retrieve_roundtrip(self, benchmark, storage):
        """Benchmark store + retrieve cycle."""
        counter = {"i": 0}

        def roundtrip():
            counter["i"] += 1
            uid = f"rt-{counter['i']}"
            storage.store_short_term(_make_unit(uid=uid))
            storage.retrieve_short_term(uid)

        benchmark(roundtrip)

    def test_consolidate_memories(self, benchmark, storage):
        """Benchmark consolidation with qualifying memories."""
        from datetime import datetime, timedelta
        for i in range(50):
            unit = _make_unit(uid=f"c-{i}", importance=0.9)
            unit.timestamp = datetime.now() - timedelta(days=30)
            storage.store_short_term(unit)

        def consolidate():
            # Re-populate for each round since consolidation removes them
            storage.consolidate_memories(threshold_days=7, min_importance=0.5)

        benchmark.pedantic(consolidate, iterations=1, rounds=1)

    def test_prune_memories(self, benchmark, storage):
        """Benchmark pruning with oversized store."""
        for i in range(200):
            storage.store_short_term(_make_unit(uid=f"p-{i}", importance=i / 200))

        benchmark.pedantic(
            storage.prune_memories,
            kwargs={"max_short_term": 50, "max_long_term": 50},
            iterations=1,
            rounds=1,
        )


class TestValidationBenchmarks:
    """Benchmark event validation."""

    def test_validate_minimal(self, benchmark):
        from ncl_agency_runtime.runtime.lib_ncl import validate_minimal

        event = {
            "schema_version": "ncl.event.v1",
            "event_id": "bench-001",
            "event_type": "ncl.test.ping",
            "occurred_at": "2026-01-15T10:00:00",
            "source": {"device": "iPhone", "origin": "shortcut"},
            "privacy": {"level": "P3"},
            "payload": {"msg": "benchmark"},
        }
        benchmark(validate_minimal, event)

    def test_day_file(self, benchmark, tmp_path):
        from ncl_agency_runtime.runtime.lib_ncl import day_file

        benchmark(day_file, tmp_path, "2026-01-15T10:00:00")

    def test_append_ndjson(self, benchmark, tmp_path):
        from ncl_agency_runtime.runtime.lib_ncl import append_ndjson

        p = tmp_path / "bench.ndjson"
        benchmark(append_ndjson, p, {"event_id": "bench", "data": "test"})
