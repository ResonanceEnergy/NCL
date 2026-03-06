"""Phase 2 — Concurrency stress tests.

Stress-test SQLite under concurrent read/write from multiple threads.
Simulates relay server + mission runner concurrent access patterns.
"""

import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ncl_memory import MemoryIndex, MemoryManager, MemoryStorage, MemoryUnit


class TestConcurrentSQLiteAccess:
    """Stress-test MemoryStorage under concurrent thread access."""

    def setup_method(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = MemoryStorage(str(self.temp_dir))

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_short_term_writes(self):
        """Multiple threads writing to short-term DB simultaneously."""
        errors = []
        count_per_thread = 50
        num_threads = 8

        def writer(thread_id):
            try:
                for i in range(count_per_thread):
                    m = MemoryUnit(f"thread-{thread_id}-item-{i}", "episodic")
                    m.id = f"t{thread_id}-{i}"
                    self.storage.store_short_term(m)
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Write errors: {errors}"

        # Verify all records are present
        total = 0
        for t_id in range(num_threads):
            for i in range(count_per_thread):
                m = self.storage.retrieve_short_term(f"t{t_id}-{i}")
                if m is not None:
                    total += 1

        assert total == num_threads * count_per_thread

    def test_concurrent_long_term_writes(self):
        """Multiple threads writing to long-term DB simultaneously."""
        errors = []
        count_per_thread = 30
        num_threads = 4

        def writer(thread_id):
            try:
                for i in range(count_per_thread):
                    m = MemoryUnit(f"lt-{thread_id}-{i}", "semantic")
                    m.id = f"lt{thread_id}-{i}"
                    self.storage.store_long_term(m)
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Long-term write errors: {errors}"

        for t_id in range(num_threads):
            for i in range(count_per_thread):
                assert self.storage.retrieve_long_term(f"lt{t_id}-{i}") is not None

    def test_concurrent_read_write(self):
        """Readers and writers running simultaneously on short-term DB."""
        # Pre-populate some data
        for i in range(100):
            m = MemoryUnit(f"base-{i}", "episodic")
            m.id = f"base-{i}"
            self.storage.store_short_term(m)

        errors = []
        read_counts = []

        def writer(thread_id):
            try:
                for i in range(50):
                    m = MemoryUnit(f"new-{thread_id}-{i}", "episodic")
                    m.id = f"new-{thread_id}-{i}"
                    self.storage.store_short_term(m)
            except Exception as e:
                errors.append(("writer", thread_id, e))

        def reader(thread_id):
            try:
                found = 0
                for i in range(100):
                    m = self.storage.retrieve_short_term(f"base-{i}")
                    if m is not None:
                        found += 1
                read_counts.append(found)
            except Exception as e:
                errors.append(("reader", thread_id, e))

        threads = []
        for t in range(4):
            threads.append(threading.Thread(target=writer, args=(t,)))
        for t in range(4):
            threads.append(threading.Thread(target=reader, args=(t,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Read/write errors: {errors}"
        # All readers should have found all 100 base items
        assert all(c == 100 for c in read_counts), f"Read counts: {read_counts}"

    def test_concurrent_search(self):
        """Concurrent search operations while writing."""
        # Pre-populate
        for i in range(50):
            m = MemoryUnit(f"search-target-{i}", "episodic")
            m.importance = 0.5 + (i % 5) * 0.1
            self.storage.store_short_term(m)

        errors = []
        search_results = []

        def searcher(thread_id):
            try:
                results = self.storage.search_short_term(
                    {"memory_type": "episodic", "min_importance": 0.7}, limit=20
                )
                search_results.append(len(results))
            except Exception as e:
                errors.append(("search", thread_id, e))

        def writer(thread_id):
            try:
                for i in range(20):
                    m = MemoryUnit(f"concurrent-{thread_id}-{i}", "episodic")
                    m.importance = 0.9
                    self.storage.store_short_term(m)
            except Exception as e:
                errors.append(("write", thread_id, e))

        threads = []
        for t in range(3):
            threads.append(threading.Thread(target=writer, args=(t,)))
        for t in range(3):
            threads.append(threading.Thread(target=searcher, args=(t,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent search errors: {errors}"
        # Each searcher should have found some results
        assert all(c > 0 for c in search_results), f"Search results: {search_results}"

    def test_concurrent_consolidation_and_writes(self):
        """Consolidation running while new writes happen."""
        # Add old important memories for consolidation
        for i in range(20):
            m = MemoryUnit(f"old-{i}", "episodic")
            m.importance = 0.9
            m.timestamp = datetime.now() - timedelta(days=10)
            m.id = f"old-{i}"
            self.storage.store_short_term(m)

        errors = []

        def consolidator():
            try:
                count = self.storage.consolidate_memories(threshold_days=7, min_importance=0.7)
                assert count > 0
            except Exception as e:
                errors.append(("consolidator", e))

        def writer():
            try:
                for i in range(30):
                    m = MemoryUnit(f"fresh-{i}", "episodic")
                    m.id = f"fresh-{i}"
                    self.storage.store_short_term(m)
            except Exception as e:
                errors.append(("writer", e))

        threads = [
            threading.Thread(target=consolidator),
            threading.Thread(target=writer),
            threading.Thread(target=writer),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Consolidation+write errors: {errors}"

        # Verify consolidated items are in long-term
        lt_count = 0
        for i in range(20):
            if self.storage.retrieve_long_term(f"old-{i}") is not None:
                lt_count += 1
        assert lt_count == 20

    def test_concurrent_prune(self):
        """Pruning while writing doesn't corrupt data."""
        # Fill short-term beyond limit
        for i in range(100):
            m = MemoryUnit(f"prune-{i}", "episodic")
            m.importance = i * 0.01
            self.storage.store_short_term(m)

        errors = []

        def pruner():
            try:
                self.storage.prune_memories(max_short_term=50)
            except Exception as e:
                errors.append(("pruner", e))

        def writer():
            try:
                for i in range(50):
                    m = MemoryUnit(f"while-prune-{i}", "episodic")
                    m.importance = 0.99
                    self.storage.store_short_term(m)
            except Exception as e:
                errors.append(("writer", e))

        threads = [
            threading.Thread(target=pruner),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Prune errors: {errors}"


class TestConcurrentMemoryManager:
    """Test MemoryManager under concurrent usage (without background thread)."""

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

    def test_concurrent_store_memory(self):
        """Multiple threads calling store_memory simultaneously."""
        errors = []
        stored_ids = []
        lock = threading.Lock()

        def store_batch(thread_id):
            try:
                for i in range(20):
                    mid = self.manager.store_memory(
                        f"content-{thread_id}-{i}",
                        memory_type="episodic",
                        tags=[f"thread-{thread_id}"],
                    )
                    with lock:
                        stored_ids.append(mid)
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=store_batch, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Store errors: {errors}"
        assert len(stored_ids) == 80

    def test_concurrent_store_and_retrieve(self):
        """Store and retrieve interleaved from multiple threads."""
        # Pre-populate
        known_ids = []
        for i in range(20):
            mid = self.manager.store_memory(f"seed-{i}", memory_type="working")
            known_ids.append(mid)

        errors = []

        def retriever():
            try:
                for mid in known_ids:
                    m = self.manager.retrieve_memory(mid)
                    assert m is not None, f"Missing {mid}"
            except Exception as e:
                errors.append(("retriever", e))

        def storer():
            try:
                for i in range(20):
                    self.manager.store_memory(f"concurrent-{i}", memory_type="episodic")
            except Exception as e:
                errors.append(("storer", e))

        threads = [
            threading.Thread(target=retriever),
            threading.Thread(target=retriever),
            threading.Thread(target=storer),
            threading.Thread(target=storer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Store+retrieve errors: {errors}"

    def test_concurrent_search_and_consolidate(self):
        """Search and consolidation running concurrently."""
        # Populate with old important memories
        for i in range(30):
            m = MemoryUnit(f"old-important-{i}", "episodic", tags=["batch"])
            m.importance = 0.9
            m.timestamp = datetime.now() - timedelta(days=10)
            self.manager.storage.store_short_term(m)
            self.manager.index.add_memory(m)

        errors = []

        def searcher():
            try:
                results = self.manager.search_memories({"memory_type": "episodic"}, limit=50)
                # Should find some results (some may be mid-consolidation)
                assert isinstance(results, list)
            except Exception as e:
                errors.append(("search", e))

        def consolidator():
            try:
                self.manager.consolidate_memories()
            except Exception as e:
                errors.append(("consolidate", e))

        threads = [
            threading.Thread(target=searcher),
            threading.Thread(target=searcher),
            threading.Thread(target=consolidator),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Search+consolidate errors: {errors}"
