"""Phase 2 — Memory analytics tests.

Tests get_memory_stats across all tiers and via the MemoryAPI wrapper,
ensuring the analytics surface is correct for dashboard consumption.
"""

import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ncl_memory import MemoryIndex, MemoryManager, MemoryStorage, MemoryUnit


class TestMemoryStatsDetailed:
    """Test get_memory_stats with various data distributions."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.manager = MemoryManager.__new__(MemoryManager)
        self.manager.config = {"memory": {
            "storage_path": str(self.temp_dir),
            "consolidation_threshold_days": 7,
            "consolidation_min_importance": 0.7,
            "pruning_max_short_term": 10000,
            "pruning_max_long_term": 50000,
        }}
        self.manager.storage = MemoryStorage(str(self.temp_dir))
        self.manager.index = MemoryIndex()
        self.manager.consolidation_queue = []
        self.manager.learning_queue = []
        self.manager.running = False

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stats_empty(self):
        """Empty system returns all zeros."""
        stats = self.manager.get_memory_stats()
        assert stats["working_memory_count"] == 0
        assert stats["short_term_count"] == 0
        assert stats["long_term_count"] == 0
        assert stats["consolidation_queue_size"] == 0

    def test_stats_working_memory_only(self):
        """Only working memory populated."""
        for i in range(5):
            self.manager.storage.store_working_memory(MemoryUnit(f"wm-{i}", "working"))
        stats = self.manager.get_memory_stats()
        assert stats["working_memory_count"] == 5
        assert stats["short_term_count"] == 0
        assert stats["long_term_count"] == 0

    def test_stats_all_tiers_populated(self):
        """All three tiers have data."""
        for i in range(3):
            self.manager.storage.store_working_memory(MemoryUnit(f"wm-{i}", "working"))
        for i in range(7):
            self.manager.storage.store_short_term(MemoryUnit(f"st-{i}", "episodic"))
        for i in range(4):
            self.manager.storage.store_long_term(MemoryUnit(f"lt-{i}", "semantic"))

        stats = self.manager.get_memory_stats()
        assert stats["working_memory_count"] == 3
        assert stats["short_term_count"] == 7
        assert stats["long_term_count"] == 4

    def test_stats_after_consolidation(self):
        """Stats reflect tier changes after consolidation."""
        for i in range(5):
            m = MemoryUnit(f"consolidatable-{i}", "episodic")
            m.importance = 0.9
            m.timestamp = datetime.now() - timedelta(days=10)
            self.manager.storage.store_short_term(m)

        stats_before = self.manager.get_memory_stats()
        assert stats_before["short_term_count"] == 5
        assert stats_before["long_term_count"] == 0

        self.manager.consolidate_memories()

        stats_after = self.manager.get_memory_stats()
        assert stats_after["short_term_count"] == 0
        assert stats_after["long_term_count"] == 5

    def test_stats_after_pruning(self):
        """Stats reflect count reduction after pruning."""
        self.manager.config["memory"]["pruning_max_short_term"] = 5

        for i in range(10):
            m = MemoryUnit(f"prune-{i}", "episodic")
            m.importance = i * 0.1
            self.manager.storage.store_short_term(m)

        stats_before = self.manager.get_memory_stats()
        assert stats_before["short_term_count"] == 10

        self.manager.prune_memories()

        stats_after = self.manager.get_memory_stats()
        assert stats_after["short_term_count"] == 5

    def test_stats_consolidation_queue(self):
        """Queue size reflects pending consolidation items."""
        self.manager.consolidation_queue = list(range(15))
        stats = self.manager.get_memory_stats()
        assert stats["consolidation_queue_size"] == 15

    def test_stats_after_store_memory_routing(self):
        """Stats reflect correct routing after store_memory calls."""
        # Working memory
        self.manager.store_memory("wm item", memory_type="working")
        # Episodic (may route to short-term or long-term based on importance calc)
        self.manager.store_memory("episodic item", memory_type="episodic")

        stats = self.manager.get_memory_stats()
        assert stats["working_memory_count"] == 1
        # Episodic goes to either short-term or long-term
        assert stats["short_term_count"] + stats["long_term_count"] >= 1

    def test_stats_large_dataset(self):
        """Stats are correct with a larger dataset."""
        for i in range(100):
            self.manager.storage.store_short_term(MemoryUnit(f"large-{i}", "episodic"))

        stats = self.manager.get_memory_stats()
        assert stats["short_term_count"] == 100

    def test_get_db_count_missing_db(self):
        """_get_db_count returns 0 for nonexistent database."""
        count = self.manager._get_db_count(Path("/nonexistent/path.db"))
        assert count == 0


class TestMemoryStorageTierIntegrity:
    """Verify tier isolation — memories don't leak between tiers."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = MemoryStorage(str(self.temp_dir))

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_short_term_not_in_long_term(self):
        """Short-term memories are not retrievable from long-term."""
        m = MemoryUnit("st only", "episodic")
        self.storage.store_short_term(m)
        assert self.storage.retrieve_long_term(m.id) is None

    def test_long_term_not_in_short_term(self):
        """Long-term memories are not retrievable from short-term."""
        m = MemoryUnit("lt only", "semantic")
        self.storage.store_long_term(m)
        assert self.storage.retrieve_short_term(m.id) is None

    def test_working_memory_not_in_databases(self):
        """Working memory items are not in SQLite databases."""
        m = MemoryUnit("wm only", "working")
        self.storage.store_working_memory(m)
        assert self.storage.retrieve_short_term(m.id) is None
        assert self.storage.retrieve_long_term(m.id) is None

    def test_consolidation_removes_from_source(self):
        """After consolidation, memory is in long-term but NOT in short-term."""
        m = MemoryUnit("migrate me", "episodic")
        m.importance = 0.95
        m.timestamp = datetime.now() - timedelta(days=14)
        self.storage.store_short_term(m)

        self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)

        assert self.storage.retrieve_short_term(m.id) is None
        assert self.storage.retrieve_long_term(m.id) is not None


class TestMemoryAPIStats:
    """Test the MemoryAPI get_memory_stats wrapper."""

    def test_stats_when_enabled(self):
        """MemoryAPI.get_memory_stats includes 'enabled: True'."""
        try:
            from ncl_agency_runtime.runtime.memory_api import MemoryAPI
        except ImportError:
            return  # Skip if not importable

        temp_dir = tempfile.mkdtemp()
        try:
            api = MemoryAPI.__new__(MemoryAPI)
            mm = MemoryManager.__new__(MemoryManager)
            mm.config = {"memory": {"storage_path": temp_dir}}
            mm.storage = MemoryStorage(temp_dir)
            mm.index = MemoryIndex()
            mm.consolidation_queue = []
            mm.learning_queue = []
            mm.running = False
            api.memory_manager = mm
            api.storage_path = temp_dir

            stats = api.get_memory_stats()
            assert stats["enabled"] is True
            assert "working_memory_count" in stats
            assert "short_term_count" in stats
            assert "long_term_count" in stats
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
