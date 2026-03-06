#!/usr/bin/env python3
"""
Tests for NCL Memory System
"""

import shutil

# Add parent directory to path for imports
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

from ncl_agency_runtime.runtime.learning_engine import LearningEngine
from ncl_agency_runtime.runtime.memory_api import MemoryAPI
from ncl_memory import MemoryIndex, MemoryStorage, MemoryUnit


class TestMemoryUnit:
    """Test MemoryUnit functionality"""

    def test_memory_unit_creation(self):
        """Test creating a memory unit"""
        content = {"event": "test", "data": "value"}
        memory = MemoryUnit(content, "episodic", ["test"], {"importance": 0.8})

        assert memory.content == content
        assert memory.memory_type == "episodic"
        assert "test" in memory.tags
        assert memory.context["importance"] == 0.8
        assert memory.importance == 1.0  # Default
        assert not memory.consolidated

    def test_memory_unit_serialization(self):
        """Test memory unit JSON serialization"""
        memory = MemoryUnit("test content", "semantic", ["tag1", "tag2"])
        data = memory.to_dict()

        # Deserialize
        restored = MemoryUnit.from_dict(data)

        assert restored.content == memory.content
        assert restored.memory_type == memory.memory_type
        assert restored.tags == memory.tags

    def test_importance_calculation(self):
        """Test importance calculation"""
        # Create old memory
        memory = MemoryUnit("old content", "episodic")
        memory.timestamp = datetime.now() - timedelta(days=10)

        # Calculate importance
        importance = memory.calculate_importance()
        assert 0.0 <= importance <= 1.0


class TestMemoryStorage:
    """Test MemoryStorage functionality"""

    def setup_method(self):
        """Setup temporary storage for testing"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = MemoryStorage(str(self.temp_dir))

    def teardown_method(self):
        """Clean up temporary storage"""
        shutil.rmtree(self.temp_dir)

    def test_storage_initialization(self):
        """Test storage initialization creates databases"""
        assert (self.temp_dir / "short_term.db").exists()
        assert (self.temp_dir / "long_term.db").exists()

    def test_working_memory_storage(self):
        """Test working memory storage"""
        memory = MemoryUnit("test content", "working")

        # Store
        self.storage.store_working_memory(memory)
        assert len(self.storage.working_memory) == 1

        # Retrieve
        retrieved = self.storage.retrieve_working_memory(memory.id)
        assert retrieved.content == memory.content

    def test_short_term_storage(self):
        """Test short-term storage"""
        memory = MemoryUnit("test content", "episodic")

        # Store
        self.storage.store_short_term(memory)

        # Retrieve
        retrieved = self.storage.retrieve_short_term(memory.id)
        assert retrieved.content == memory.content

    def test_memory_consolidation(self):
        """Test memory consolidation"""
        # Create memories with high importance
        memory1 = MemoryUnit("important content", "episodic")
        memory1.importance = 0.9
        memory1.timestamp = datetime.now() - timedelta(days=10)

        memory2 = MemoryUnit("less important", "episodic")
        memory2.importance = 0.3

        # Store in short-term
        self.storage.store_short_term(memory1)
        self.storage.store_short_term(memory2)

        # Consolidate
        consolidated = self.storage.consolidate_memories(threshold_days=5, min_importance=0.8)
        assert consolidated == 1

        # Check long-term storage
        retrieved = self.storage.retrieve_long_term(memory1.id)
        assert retrieved is not None
        assert retrieved.consolidated


class TestMemoryIndex:
    """Test MemoryIndex functionality"""

    def test_index_operations(self):
        """Test indexing operations"""
        index = MemoryIndex()

        memory = MemoryUnit("test content", "episodic", ["tag1", "tag2"])

        # Add to index
        index.add_memory(memory)

        # Search by tag
        results = index.search({"tags": ["tag1"]})
        assert memory.id in results

        # Search by type
        results = index.search({"memory_type": "episodic"})
        assert memory.id in results


class TestMemoryAPI:
    """Test MemoryAPI functionality"""

    def setup_method(self):
        """Setup temporary API for testing"""
        self.temp_dir = Path(tempfile.mkdtemp())
        # Use temporary directory for testing
        import ncl_memory
        original_init = ncl_memory.MemoryManager.__init__

        def test_init(self, config_path="ncl_config.json"):
            self.config = {"memory": {"storage_path": str(self.temp_dir)}}
            self.storage = MemoryStorage(str(self.temp_dir))
            self.index = MemoryIndex()
            self.consolidation_queue = []
            self.learning_queue = []
            self.running = True

        ncl_memory.MemoryManager.__init__ = test_init

        self.api = MemoryAPI()

        # Restore original
        ncl_memory.MemoryManager.__init__ = original_init

    def teardown_method(self):
        """Clean up"""
        shutil.rmtree(self.temp_dir)

    def test_event_memory_storage(self):
        """Test storing event memories"""
        event = {
            "event_type": "focus_session",
            "occurred_at": "2024-01-15T10:00:00Z",
            "data": {"duration": 25}
        }

        memory_id = self.api.store_event_memory(event)
        assert memory_id is not None

    def test_task_memory_storage(self):
        """Test storing task execution memories"""
        task = {"type": "daily_brief", "mission_id": "test123"}
        result = {"success": True, "duration": 45}

        memory_id = self.api.store_task_memory(task, result)
        assert memory_id is not None

    def test_semantic_memory_storage(self):
        """Test storing semantic memories"""
        memory_id = self.api.store_learning(
            "productivity",
            "Deep work sessions of 90+ minutes are optimal",
            confidence=0.85
        )
        assert memory_id is not None


class TestLearningEngine:
    """Test LearningEngine functionality"""

    def setup_method(self):
        """Setup temporary learning engine"""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Mock memory system for testing
        import ncl_memory
        original_init = ncl_memory.MemoryManager.__init__

        def test_init(self, config_path="ncl_config.json"):
            self.config = {"memory": {"storage_path": str(self.temp_dir)}}
            self.storage = MemoryStorage(str(self.temp_dir))
            self.index = MemoryIndex()
            self.consolidation_queue = []
            self.learning_queue = []
            self.running = True

        ncl_memory.MemoryManager.__init__ = test_init

        self.engine = LearningEngine()

        # Restore original
        ncl_memory.MemoryManager.__init__ = original_init

    def teardown_method(self):
        """Clean up"""
        shutil.rmtree(self.temp_dir)

    def test_pattern_analysis(self):
        """Test pattern analysis with mock data"""
        # Create mock events
        events = [
            {
                "event_type": "focus_session",
                "occurred_at": "2024-01-15T10:00:00Z",
                "data": {"duration": 25, "quality": "high"}
            },
            {
                "event_type": "task_completed",
                "occurred_at": "2024-01-15T11:00:00Z",
                "data": {"time_taken": 30}
            }
        ]

        # Mock the search function to return our test events
        import ncl_memory
        original_search = ncl_memory.search_memories

        def mock_search(query, limit=50):
            return [MemoryUnit(event, "episodic") for event in events]

        ncl_memory.search_memories = mock_search

        # Analyze patterns
        analysis = self.engine.analyze_recent_events(days_back=7)

        assert analysis["total_events"] == 2
        assert "patterns" in analysis
        assert "insights" in analysis
        assert "recommendations" in analysis

        # Restore original
        ncl_memory.search_memories = original_search


if __name__ == "__main__":
    pytest.main([__file__])
