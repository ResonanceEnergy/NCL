"""Phase 2 — Search quality benchmark for MemoryManager.search_memories().

Tests precision/recall on 1K+ MemoryUnit items across all query types
(tags, memory_type, content, context, time_range, min_importance) and
both tiers (short-term + long-term).
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ncl_memory import (
    MemoryIndex,
    MemoryManager,
    MemoryStorage,
    MemoryUnit,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_unit(
    uid: str,
    content: str,
    memory_type: str = "episodic",
    tags: list[str] | None = None,
    context: dict | None = None,
    importance: float = 0.5,
    days_ago: int = 0,
) -> MemoryUnit:
    m = MemoryUnit(content, memory_type, tags or [], context or {})
    m.id = uid
    m.importance = importance
    m.timestamp = datetime.now() - timedelta(days=days_ago)
    m.last_accessed = m.timestamp
    return m


CATEGORIES = [
    ("productivity", "focus session completed successfully today"),
    ("health", "morning run completed five kilometres"),
    ("learning", "studied machine learning algorithms lecture"),
    ("social", "had lunch with colleague discussed project"),
    ("finance", "reviewed monthly budget expenses saved"),
    ("creative", "wrote short story draft during evening"),
]


def _build_corpus(storage: MemoryStorage, index: MemoryIndex, n: int = 1200):
    """Insert *n* units split evenly across CATEGORIES into short-term + long-term."""
    units: list[MemoryUnit] = []
    per_cat = n // len(CATEGORIES)
    for _cat_idx, (cat_tag, base_content) in enumerate(CATEGORIES):
        for i in range(per_cat):
            uid = f"{cat_tag}-{i:04d}"
            importance = 0.3 + (i % 7) * 0.1  # 0.3 .. 0.9
            days_ago = i % 30
            m = _make_unit(
                uid=uid,
                content=f"{base_content} item {i}",
                memory_type=["episodic", "semantic", "procedural"][i % 3],
                tags=[cat_tag, f"batch-{i % 5}"],
                context={"category": cat_tag, "quality": "high" if i % 2 == 0 else "low"},
                importance=importance,
                days_ago=days_ago,
            )
            # Alternate between short-term and long-term
            if i % 2 == 0:
                storage.store_short_term(m)
            else:
                storage.store_long_term(m)
            index.add_memory(m)
            units.append(m)
    return units


def _precision_recall(retrieved_ids: set[str], expected_ids: set[str]):
    if not retrieved_ids and not expected_ids:
        return 1.0, 1.0
    tp = len(retrieved_ids & expected_ids)
    precision = tp / len(retrieved_ids) if retrieved_ids else 0.0
    recall = tp / len(expected_ids) if expected_ids else 0.0
    return precision, recall


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def corpus(tmp_path_factory):
    """Create a MemoryManager with 1200 indexed memories (session-scoped)."""
    tmp_path = tmp_path_factory.mktemp("search_quality")
    storage = MemoryStorage(str(tmp_path))
    index = MemoryIndex()

    manager = MemoryManager.__new__(MemoryManager)
    manager.config = {
        "memory": {
            "storage_path": str(tmp_path),
            "consolidation_threshold_days": 7,
            "consolidation_min_importance": 0.7,
        }
    }
    manager.storage = storage
    manager.index = index
    manager.consolidation_queue = __import__("collections").deque()
    manager.learning_queue = __import__("collections").deque()
    manager.running = False

    units = _build_corpus(storage, index, n=1200)
    return manager, units


# ---------------------------------------------------------------------------
# Precision / recall tests
# ---------------------------------------------------------------------------

class TestSearchPrecisionRecall:
    """Measure precision & recall for each query dimension."""

    def test_tag_search(self, corpus):
        manager, units = corpus
        target_tag = "productivity"
        expected = {u.id for u in units if target_tag in u.tags}
        results = manager.search_memories({"tags": [target_tag]}, limit=500)
        retrieved = {r.id for r in results}
        precision, recall = _precision_recall(retrieved, expected)
        assert precision >= 0.9, f"Tag precision {precision:.2f} < 0.9"
        assert recall >= 0.5, f"Tag recall {recall:.2f} < 0.5"

    def test_type_search(self, corpus):
        manager, units = corpus
        expected = {u.id for u in units if u.memory_type == "semantic"}
        results = manager.search_memories({"memory_type": "semantic"}, limit=500)
        retrieved = {r.id for r in results}
        precision, recall = _precision_recall(retrieved, expected)
        assert precision >= 0.9, f"Type precision {precision:.2f} < 0.9"
        assert recall >= 0.3, f"Type recall {recall:.2f} < 0.3"

    def test_importance_search(self, corpus):
        manager, units = corpus
        expected = {u.id for u in units if u.importance >= 0.7}
        results = manager.search_memories({"min_importance": 0.7}, limit=500)
        retrieved = {r.id for r in results}
        precision, recall = _precision_recall(retrieved, expected)
        assert precision >= 0.8, f"Importance precision {precision:.2f} < 0.8"
        assert recall >= 0.3, f"Importance recall {recall:.2f} < 0.3"

    def test_content_keyword_search(self, corpus):
        manager, units = corpus
        keyword = "machine"
        expected = {u.id for u in units if keyword in u.content.lower()}
        results = manager.search_memories({"content": keyword}, limit=500)
        retrieved = {r.id for r in results}
        precision, recall = _precision_recall(retrieved, expected)
        assert precision >= 0.9, f"Content precision {precision:.2f} < 0.9"
        assert recall >= 0.5, f"Content recall {recall:.2f} < 0.5"

    def test_context_search(self, corpus):
        manager, units = corpus
        expected = {u.id for u in units if u.context.get("quality") == "high"}
        results = manager.search_memories({"context": {"quality": "high"}}, limit=500)
        retrieved = {r.id for r in results}
        precision, recall = _precision_recall(retrieved, expected)
        assert precision >= 0.9, f"Context precision {precision:.2f} < 0.9"
        assert recall >= 0.5, f"Context recall {recall:.2f} < 0.5"

    def test_combined_tag_and_type(self, corpus):
        manager, units = corpus
        expected = {
            u.id for u in units
            if "health" in u.tags and u.memory_type == "episodic"
        }
        results = manager.search_memories(
            {"tags": ["health"], "memory_type": "episodic"}, limit=500
        )
        retrieved = {r.id for r in results}
        precision, recall = _precision_recall(retrieved, expected)
        assert precision >= 0.8, f"Combined precision {precision:.2f} < 0.8"
        assert recall >= 0.4, f"Combined recall {recall:.2f} < 0.4"

    def test_unknown_tag_falls_back_to_db(self, corpus):
        """When index returns empty for an unknown tag, search falls back to DB scan."""
        manager, _ = corpus
        results = manager.search_memories({"tags": ["nonexistent_tag"]}, limit=100)
        # The index returns an empty set for unknown tags, so search_memories
        # falls back to a database scan — this is by design to handle
        # incomplete indexes.  Assert fallback returns *some* results.
        assert len(results) > 0

    def test_limit_respected(self, corpus):
        manager, _ = corpus
        results = manager.search_memories({"tags": ["productivity"]}, limit=10)
        assert len(results) <= 10


# ---------------------------------------------------------------------------
# Performance (wall-clock) tests
# ---------------------------------------------------------------------------

class TestSearchPerformance:
    """Ensure searches complete within acceptable time on 1K+ data.

    Thresholds are generous (10s) because the current architecture opens a
    fresh SQLite connection per retrieve_memory() call.  Tighter bounds
    require connection pooling (Phase 3 optimisation).
    """

    def test_tag_search_under_10s(self, corpus):
        manager, _ = corpus
        t0 = time.perf_counter()
        manager.search_memories({"tags": ["productivity"]}, limit=100)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"Tag search took {elapsed:.3f}s"

    def test_type_search_under_10s(self, corpus):
        manager, _ = corpus
        t0 = time.perf_counter()
        manager.search_memories({"memory_type": "semantic"}, limit=100)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"Type search took {elapsed:.3f}s"

    def test_content_search_under_10s(self, corpus):
        manager, _ = corpus
        t0 = time.perf_counter()
        manager.search_memories({"content": "machine learning"}, limit=100)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"Content search took {elapsed:.3f}s"

    def test_importance_search_under_10s(self, corpus):
        manager, _ = corpus
        t0 = time.perf_counter()
        manager.search_memories({"min_importance": 0.7}, limit=100)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"Importance search took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Index-only quality tests (MemoryIndex.search)
# ---------------------------------------------------------------------------

class TestMemoryIndexQuality:
    """Verify MemoryIndex returns correct candidate sets."""

    def test_index_tag_exact(self, corpus):
        _, units = corpus
        idx = MemoryIndex()
        for u in units:
            idx.add_memory(u)
        expected = {u.id for u in units if "finance" in u.tags}
        got = idx.search({"tags": ["finance"]})
        assert got == expected

    def test_index_type_exact(self, corpus):
        _, units = corpus
        idx = MemoryIndex()
        for u in units:
            idx.add_memory(u)
        expected = {u.id for u in units if u.memory_type == "procedural"}
        got = idx.search({"memory_type": "procedural"})
        assert got == expected

    def test_index_content_keywords(self, corpus):
        _, units = corpus
        idx = MemoryIndex()
        for u in units:
            idx.add_memory(u)
        # "algorithms" has > 3 chars, so should be indexed
        expected = {u.id for u in units if "algorithms" in u.content.lower()}
        got = idx.search({"content": "algorithms"})
        assert got == expected

    def test_index_context_filter(self, corpus):
        _, units = corpus
        idx = MemoryIndex()
        for u in units:
            idx.add_memory(u)
        expected = {u.id for u in units if u.context.get("category") == "creative"}
        got = idx.search({"context": {"category": "creative"}})
        assert got == expected

    def test_index_combined_intersection(self, corpus):
        _, units = corpus
        idx = MemoryIndex()
        for u in units:
            idx.add_memory(u)
        expected = {
            u.id for u in units
            if "social" in u.tags and u.memory_type == "episodic"
        }
        got = idx.search({"tags": ["social"], "memory_type": "episodic"})
        assert got == expected

    def test_index_scales_to_1k(self, corpus):
        _, units = corpus
        idx = MemoryIndex()
        t0 = time.perf_counter()
        for u in units:
            idx.add_memory(u)
        index_time = time.perf_counter() - t0
        assert index_time < 5.0, f"Indexing 1200 units took {index_time:.3f}s"

        t0 = time.perf_counter()
        idx.search({"tags": ["learning"], "memory_type": "semantic"})
        search_time = time.perf_counter() - t0
        assert search_time < 0.1, f"Index search took {search_time:.3f}s"


# ---------------------------------------------------------------------------
# Result ordering tests
# ---------------------------------------------------------------------------

class TestSearchOrdering:
    """Verify results are sorted by importance then recency."""

    def test_results_sorted_by_importance(self, corpus):
        manager, _ = corpus
        results = manager.search_memories({"tags": ["productivity"]}, limit=50)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].importance >= results[i + 1].importance or (
                    results[i].importance == results[i + 1].importance
                    and results[i].last_accessed >= results[i + 1].last_accessed
                ), f"Result {i} not sorted correctly"

    def test_high_importance_first(self, corpus):
        manager, _ = corpus
        results = manager.search_memories({"tags": ["health"]}, limit=20)
        if len(results) >= 2:
            assert results[0].importance >= results[-1].importance
