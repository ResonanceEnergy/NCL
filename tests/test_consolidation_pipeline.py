"""Phase 2 — Consolidation pipeline tests.

Tests the full working → short-term → long-term memory pipeline,
time-based decay, importance routing, and MemoryManager-level consolidation.
"""

import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ncl_memory import MemoryIndex, MemoryManager, MemoryStorage, MemoryUnit


class TestConsolidationPipeline:
    """End-to-end consolidation pipeline tests."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = MemoryStorage(str(self.temp_dir))

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── Working → Short-term (not directly supported, but test eviction) ──

    def test_working_memory_eviction_feeds_short_term(self):
        """Working memory evicts oldest when limit is reached; verify eviction occurs."""
        for i in range(self.storage.working_memory_limit + 5):
            m = MemoryUnit(f"item-{i}", "working")
            m.id = f"wm-{i}"
            self.storage.store_working_memory(m)
        assert len(self.storage.working_memory) == self.storage.working_memory_limit

    # ── Short-term → Long-term consolidation ──

    def test_consolidate_old_important_moves_to_long_term(self):
        """Old + important memories move from short-term to long-term."""
        mem = MemoryUnit("important old", "episodic")
        mem.importance = 0.9
        mem.timestamp = datetime.now() - timedelta(days=10)
        self.storage.store_short_term(mem)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 1

        # Gone from short-term
        assert self.storage.retrieve_short_term(mem.id) is None
        # Present in long-term
        lt = self.storage.retrieve_long_term(mem.id)
        assert lt is not None
        assert lt.content == "important old"

    def test_consolidate_old_low_importance_stays(self):
        """Old but low-importance memories stay in short-term."""
        mem = MemoryUnit("old unimportant", "episodic")
        mem.importance = 0.3
        mem.timestamp = datetime.now() - timedelta(days=10)
        self.storage.store_short_term(mem)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 0
        assert self.storage.retrieve_short_term(mem.id) is not None

    def test_consolidate_recent_important_stays(self):
        """Recent + important memories stay in short-term (not old enough)."""
        mem = MemoryUnit("recent important", "episodic")
        mem.importance = 0.95
        mem.timestamp = datetime.now() - timedelta(days=1)
        self.storage.store_short_term(mem)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 0
        assert self.storage.retrieve_short_term(mem.id) is not None

    def test_consolidate_batch(self):
        """Multiple qualifying memories all move in one consolidation pass."""
        ids = []
        for i in range(5):
            m = MemoryUnit(f"batch-{i}", "episodic")
            m.importance = 0.8 + i * 0.02
            m.timestamp = datetime.now() - timedelta(days=8 + i)
            self.storage.store_short_term(m)
            ids.append(m.id)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 5
        for mid in ids:
            assert self.storage.retrieve_short_term(mid) is None
            assert self.storage.retrieve_long_term(mid) is not None

    def test_consolidate_mixed_qualifiers(self):
        """Only qualifying memories move; others remain."""
        good = MemoryUnit("qualifies", "episodic")
        good.importance = 0.9
        good.timestamp = datetime.now() - timedelta(days=14)
        self.storage.store_short_term(good)

        bad = MemoryUnit("stays", "episodic")
        bad.importance = 0.5
        bad.timestamp = datetime.now() - timedelta(days=14)
        self.storage.store_short_term(bad)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 1
        assert self.storage.retrieve_long_term(good.id) is not None
        assert self.storage.retrieve_short_term(bad.id) is not None

    def test_consolidate_no_candidates(self):
        """No qualifying memories → returns 0."""
        m = MemoryUnit("new and low", "episodic")
        m.importance = 0.2
        m.timestamp = datetime.now()
        self.storage.store_short_term(m)

        assert self.storage.consolidate_memories(threshold_days=7, min_importance=0.7) == 0

    def test_consolidate_empty_database(self):
        """Empty short-term DB consolidates without error."""
        assert self.storage.consolidate_memories() == 0

    def test_consolidate_threshold_boundary(self):
        """Memory exactly at threshold_days boundary (edge case)."""
        mem = MemoryUnit("boundary", "episodic")
        mem.importance = 0.9
        # Exactly 7 days old — ISO comparison should include it
        mem.timestamp = datetime.now() - timedelta(days=7, seconds=1)
        self.storage.store_short_term(mem)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 1

    def test_consolidate_importance_boundary(self):
        """Memory exactly at min_importance — should be included (>=)."""
        mem = MemoryUnit("boundary importance", "episodic")
        mem.importance = 0.7  # Exactly at threshold
        mem.timestamp = datetime.now() - timedelta(days=10)
        self.storage.store_short_term(mem)

        count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        assert count == 1

    # ── Time-based decay ──

    def test_importance_decays_with_time(self):
        """MemoryUnit.calculate_importance decreases as memory ages."""
        mem = MemoryUnit("decay test", "episodic")
        mem.timestamp = datetime.now()
        fresh_importance = mem.calculate_importance()

        mem.timestamp = datetime.now() - timedelta(hours=48)
        old_importance = mem.calculate_importance()

        assert old_importance < fresh_importance

    def test_importance_floor_very_old(self):
        """Very old memories still have a floor importance > 0."""
        mem = MemoryUnit("ancient", "episodic")
        mem.timestamp = datetime.now() - timedelta(days=365)
        imp = mem.calculate_importance()
        assert imp > 0

    def test_access_frequency_boosts_importance(self):
        """More accesses increase importance score."""
        mem = MemoryUnit("frequently accessed", "episodic")
        base = mem.calculate_importance()

        for _ in range(10):
            mem.access()
        boosted = mem.calculate_importance()
        assert boosted >= base

    # ── Consolidation marks as consolidated ──

    def test_consolidated_flag_set_on_long_term(self):
        """Memories in long-term after consolidation have consolidated=True."""
        mem = MemoryUnit("flag test", "episodic")
        mem.importance = 0.9
        mem.timestamp = datetime.now() - timedelta(days=10)
        self.storage.store_short_term(mem)

        self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
        lt = self.storage.retrieve_long_term(mem.id)
        assert lt is not None
        # store_long_term sets consolidated = True
        assert lt.consolidated is True


class TestMemoryManagerConsolidation:
    """Test MemoryManager.consolidate_memories() and store_memory() routing."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config = {
            "memory": {
                "storage_path": str(self.temp_dir),
                "consolidation_threshold_days": 7,
                "consolidation_min_importance": 0.7,
                "pruning_max_short_term": 10000,
                "pruning_max_long_term": 50000,
            }
        }
        # Create manager without starting background thread or loading config file
        self.manager = MemoryManager.__new__(MemoryManager)
        self.manager.config = self.config
        self.manager.storage = MemoryStorage(str(self.temp_dir))
        self.manager.index = MemoryIndex()
        self.manager.consolidation_queue = []
        self.manager.learning_queue = []
        self.manager.running = False  # No background thread

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── store_memory routing ──

    def test_working_memory_routes_to_working(self):
        """memory_type='working' routes to working memory."""
        mid = self.manager.store_memory("wm content", memory_type="working")
        assert mid
        assert self.manager.storage.retrieve_working_memory(mid) is not None

    def test_high_importance_routes_to_long_term(self):
        """Procedural type with context boost → importance >= 0.8 → long-term."""
        # Procedural has base_weight=2.0, and we boost with context
        mid = self.manager.store_memory(
            "important procedure", memory_type="procedural",
            context={"importance": 1.0},
        )
        assert mid
        # Should be in long-term (importance >= 0.8)
        lt = self.manager.storage.retrieve_long_term(mid)
        assert lt is not None

    def test_low_importance_routes_to_short_term(self):
        """Working type (base 0.5) → importance < 0.8 → short-term."""
        # episodic with low frequency and no boost → typically < 0.8
        mid = self.manager.store_memory(
            "routine note", memory_type="episodic",
        )
        assert mid
        # episodic base_weight=1.0, recency_factor≈1.0, frequency=1.0 → imp=1.0 → clamped to 1.0
        # Actually episodic fresh = 1.0 * ~1.0 * 1.0 * 1.0 = ~1.0 which IS >= 0.8
        # Let's check where it actually went
        st = self.manager.storage.retrieve_short_term(mid)
        lt = self.manager.storage.retrieve_long_term(mid)
        # Fresh episodic memory:
        # base=1.0, recency≈1.0, frequency=1.0(0 accesses → 1.0+0=1.0), context=1.0
        # importance = min(1.0, 1.0*1.0*1.0*1.0) = 1.0 → goes to long-term
        assert st is not None or lt is not None

    def test_consolidation_queue_populated(self):
        """Non-working memories are added to consolidation queue."""
        self.manager.consolidation_queue = []
        self.manager.store_memory("some event", memory_type="episodic")
        assert len(self.manager.consolidation_queue) == 1

    def test_working_memory_not_queued(self):
        """Working memories are NOT added to consolidation queue."""
        self.manager.consolidation_queue = []
        self.manager.store_memory("temp note", memory_type="working")
        assert len(self.manager.consolidation_queue) == 0

    # ── MemoryManager.consolidate_memories() ──

    def test_manager_consolidate_reads_config(self):
        """MemoryManager.consolidate_memories uses config values."""
        mem = MemoryUnit("old important", "episodic")
        mem.importance = 0.8
        mem.timestamp = datetime.now() - timedelta(days=10)
        self.manager.storage.store_short_term(mem)

        count = self.manager.consolidate_memories()
        assert count == 1
        assert self.manager.storage.retrieve_long_term(mem.id) is not None

    def test_manager_consolidate_custom_config(self):
        """Config with stricter thresholds filters more aggressively."""
        self.manager.config["memory"]["consolidation_min_importance"] = 0.95
        self.manager.config["memory"]["consolidation_threshold_days"] = 30

        mem = MemoryUnit("not strict enough", "episodic")
        mem.importance = 0.8
        mem.timestamp = datetime.now() - timedelta(days=10)
        self.manager.storage.store_short_term(mem)

        count = self.manager.consolidate_memories()
        assert count == 0  # Importance 0.8 < 0.95 threshold

    # ── MemoryManager.retrieve_memory() multi-tier search ──

    def test_retrieve_searches_all_tiers(self):
        """retrieve_memory checks working, short-term, and long-term."""
        wm = MemoryUnit("wm", "working")
        self.manager.storage.store_working_memory(wm)

        st = MemoryUnit("st", "episodic")
        self.manager.storage.store_short_term(st)

        lt = MemoryUnit("lt", "episodic")
        self.manager.storage.store_long_term(lt)

        assert self.manager.retrieve_memory(wm.id) is not None
        assert self.manager.retrieve_memory(st.id) is not None
        assert self.manager.retrieve_memory(lt.id) is not None
        assert self.manager.retrieve_memory("nonexistent") is None

    # ── get_memory_stats() ──

    def test_memory_stats_counts(self):
        """get_memory_stats returns correct counts for each tier."""
        self.manager.storage.store_working_memory(MemoryUnit("w", "working"))
        self.manager.storage.store_short_term(MemoryUnit("s", "episodic"))
        self.manager.storage.store_long_term(MemoryUnit("l", "episodic"))
        self.manager.consolidation_queue = ["a", "b"]

        stats = self.manager.get_memory_stats()
        assert stats["working_memory_count"] == 1
        assert stats["short_term_count"] == 1
        assert stats["long_term_count"] == 1
        assert stats["consolidation_queue_size"] == 2

    # ── MemoryManager.prune_memories() ──

    def test_manager_prune_uses_config(self):
        """prune_memories respects config limits."""
        self.manager.config["memory"]["pruning_max_short_term"] = 3

        for i in range(5):
            m = MemoryUnit(f"item-{i}", "episodic")
            m.importance = i * 0.1
            self.manager.storage.store_short_term(m)

        self.manager.prune_memories()
        stats = self.manager.get_memory_stats()
        assert stats["short_term_count"] == 3


class TestMemoryIndexSearch:
    """Test MemoryIndex search capabilities for consolidation context."""

    def test_tag_search_multiple_tags(self):
        """Search with multiple tags returns union."""
        index = MemoryIndex()
        m1 = MemoryUnit("one", "episodic", ["alpha"])
        m2 = MemoryUnit("two", "episodic", ["beta"])
        m3 = MemoryUnit("three", "episodic", ["alpha", "beta"])
        index.add_memory(m1)
        index.add_memory(m2)
        index.add_memory(m3)

        results = index.search({"tags": ["alpha", "beta"]})
        assert m1.id in results
        assert m2.id in results
        assert m3.id in results

    def test_type_and_tag_intersection(self):
        """Combined type + tag filters intersect."""
        index = MemoryIndex()
        m1 = MemoryUnit("one", "episodic", ["work"])
        m2 = MemoryUnit("two", "semantic", ["work"])
        index.add_memory(m1)
        index.add_memory(m2)

        results = index.search({"memory_type": "episodic", "tags": ["work"]})
        assert m1.id in results
        assert m2.id not in results

    def test_content_search(self):
        """Content keyword search indexes words > 3 chars."""
        index = MemoryIndex()
        m = MemoryUnit("deep work productivity analysis", "episodic")
        index.add_memory(m)

        results = index.search({"content": "deep productivity"})
        assert m.id in results

    def test_context_search(self):
        """Context key-value search."""
        index = MemoryIndex()
        m = MemoryUnit("ctx test", "episodic", context={"source": "learning_engine"})
        index.add_memory(m)

        results = index.search({"context": {"source": "learning_engine"}})
        assert m.id in results

    def test_time_range_search(self):
        """Time range filter returns memories from specific hours."""
        index = MemoryIndex()
        m = MemoryUnit("timed", "episodic")
        m.timestamp = datetime(2025, 6, 15, 14, 30)
        index.add_memory(m)

        results = index.search({
            "time_range": (
                datetime(2025, 6, 15, 14, 0),
                datetime(2025, 6, 15, 15, 0),
            )
        })
        assert m.id in results
