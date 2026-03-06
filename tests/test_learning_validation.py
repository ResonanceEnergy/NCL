"""Phase 2 — Learning engine validation with realistic data.

Tests analyze_recent_events and learn_from_task_execution with
realistic mocked memory data rather than just synthetic mocks.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from ncl_agency_runtime.runtime.learning_engine import LearningEngine
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False

if LEARNING_AVAILABLE:
    from ncl_memory import MemoryUnit


def _make_memory_unit(content: dict, memory_type: str = "episodic",
                      tags: list | None = None) -> "MemoryUnit":
    """Helper: create a MemoryUnit with dict content."""
    m = MemoryUnit(content, memory_type, tags or [])
    return m


def _realistic_events() -> list[dict]:
    """Simulate a week of realistic NCL events."""
    base = datetime(2025, 6, 15, 8, 0)
    events = []
    for day in range(7):
        dt = base + timedelta(days=day)
        # Morning focus session
        events.append({
            "event_type": "ncl.focus.deep_work_start",
            "occurred_at": (dt + timedelta(hours=1)).isoformat(),
            "category": "productivity",
            "duration": 90,
            "quality": "high",
        })
        # Task completions
        events.append({
            "event_type": "ncl.task.completed",
            "occurred_at": (dt + timedelta(hours=3)).isoformat(),
            "category": "productivity",
            "success": True,
        })
        # Energy log
        events.append({
            "event_type": "ncl.energy.log",
            "occurred_at": (dt + timedelta(hours=5)).isoformat(),
            "category": "health",
        })
        # Afternoon focus
        events.append({
            "event_type": "ncl.focus.deep_work_start",
            "occurred_at": (dt + timedelta(hours=6)).isoformat(),
            "category": "productivity",
            "duration": 45,
            "quality": "medium",
        })
    return events


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestAnalyzeRecentEventsRealistic:
    """Test analyze_recent_events with realistic mocked memory data."""

    def _make_engine(self):
        engine = LearningEngine.__new__(LearningEngine)
        engine.storage_path = None
        engine.memory_api = MagicMock()
        engine.patterns = engine._load_patterns()
        return engine

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_realistic_week(self, mock_ncl_memory):
        """analyze_recent_events with 7 days of realistic events."""
        engine = self._make_engine()
        events = _realistic_events()
        memories = [_make_memory_unit(e) for e in events]

        mock_ncl_memory.search_memories.return_value = memories
        mock_ncl_memory.store_semantic_memory = MagicMock()

        analysis = engine.analyze_recent_events(days_back=7)

        assert analysis["total_events"] == len(events)
        assert "patterns" in analysis
        assert "insights" in analysis
        assert "recommendations" in analysis

        # Should find focus sessions and task completions
        prod = analysis["patterns"]["productivity"]
        assert prod["focus_sessions"]["count"] == 14  # 2 per day x 7 days
        assert prod["task_completions"]["count"] == 7   # 1 per day x 7 days
        assert prod["task_completions"]["success_rate"] == 1.0

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_generates_temporal_patterns(self, mock_ncl_memory):
        """Temporal patterns detect peak hours from realistic data."""
        engine = self._make_engine()
        events = _realistic_events()
        memories = [_make_memory_unit(e) for e in events]
        mock_ncl_memory.search_memories.return_value = memories
        mock_ncl_memory.store_semantic_memory = MagicMock()

        analysis = engine.analyze_recent_events(days_back=7)
        temporal = analysis["patterns"]["temporal"]

        # Should have peak hours identified
        assert len(temporal["peak_hours"]) > 0
        # Should have weekday vs weekend data
        assert "weekday_vs_weekend" in temporal

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_generates_insights(self, mock_ncl_memory):
        """Realistic data should produce actionable insights."""
        engine = self._make_engine()
        events = _realistic_events()
        memories = [_make_memory_unit(e) for e in events]
        mock_ncl_memory.search_memories.return_value = memories
        mock_ncl_memory.store_semantic_memory = MagicMock()

        analysis = engine.analyze_recent_events(days_back=7)

        # With good focus sessions, should get positive insight
        insights = analysis["insights"]
        assert len(insights) > 0
        assert any("productive" in i.lower() or "hour" in i.lower() for i in insights)

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_stores_learned_knowledge(self, mock_ncl_memory):
        """analyze_recent_events stores insights as semantic memory."""
        engine = self._make_engine()
        events = _realistic_events()
        memories = [_make_memory_unit(e) for e in events]
        mock_ncl_memory.search_memories.return_value = memories
        mock_ncl_memory.store_semantic_memory = MagicMock()

        engine.analyze_recent_events(days_back=7)

        # Should have called store_semantic_memory for insights and patterns
        assert mock_ncl_memory.store_semantic_memory.call_count >= 1

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_no_events(self, mock_ncl_memory):
        """analyze_recent_events with no memories returns empty analysis."""
        engine = self._make_engine()
        mock_ncl_memory.search_memories.return_value = []
        mock_ncl_memory.store_semantic_memory = MagicMock()

        analysis = engine.analyze_recent_events(days_back=7)
        assert analysis["total_events"] == 0
        assert analysis["patterns"]["productivity"]["focus_sessions"]["count"] == 0

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", False)
    def test_analyze_memory_disabled(self):
        """Returns error dict when memory system is disabled."""
        engine = self._make_engine()
        analysis = engine.analyze_recent_events()
        assert "error" in analysis

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_mixed_content_types(self, mock_ncl_memory):
        """Non-dict content in memories is skipped gracefully."""
        engine = self._make_engine()
        memories = [
            _make_memory_unit({"event_type": "test", "occurred_at": "2025-06-15T10:00:00Z"}),
            _make_memory_unit("plain string content"),  # Not a dict
            _make_memory_unit(42),  # Not a dict
            _make_memory_unit({"event_type": "ncl.focus.deep_work", "occurred_at": "2025-06-15T11:00:00Z"}),
        ]
        mock_ncl_memory.search_memories.return_value = memories
        mock_ncl_memory.store_semantic_memory = MagicMock()

        analysis = engine.analyze_recent_events(days_back=7)
        # Only dict-content memories count
        assert analysis["total_events"] == 2

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_analyze_category_distribution(self, mock_ncl_memory):
        """Event categories are counted in analysis."""
        engine = self._make_engine()
        events = _realistic_events()
        memories = [_make_memory_unit(e) for e in events]
        mock_ncl_memory.search_memories.return_value = memories
        mock_ncl_memory.store_semantic_memory = MagicMock()

        analysis = engine.analyze_recent_events(days_back=7)
        categories = analysis["patterns"]["categories"]
        assert "productivity" in categories
        assert "health" in categories


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestLearnFromTaskExecution:
    """Test learn_from_task_execution with realistic task/result pairs."""

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_successful_task_stores_pattern(self, mock_ncl_memory):
        """Successful task execution stores pattern in semantic memory."""
        engine = LearningEngine.__new__(LearningEngine)
        engine.patterns = {}
        mock_ncl_memory.store_semantic_memory = MagicMock()

        task = {"type": "daily_brief", "inputs": {"date": "2025-06-15"}}
        result = {"success": True, "duration": 25, "event_count": 42}

        engine.learn_from_task_execution(task, result)

        mock_ncl_memory.store_semantic_memory.assert_called_once()
        call_kwargs = mock_ncl_memory.store_semantic_memory.call_args
        content = call_kwargs[1]["content"] if "content" in (call_kwargs[1] or {}) else call_kwargs[0][0]
        assert content["task_type"] == "daily_brief"
        assert content["success"] is True
        assert "quick_completion" in content["factors"]

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_failed_task_stores_failure_pattern(self, mock_ncl_memory):
        """Failed task records failure factors."""
        engine = LearningEngine.__new__(LearningEngine)
        engine.patterns = {}
        mock_ncl_memory.store_semantic_memory = MagicMock()

        task = {"type": "anomaly_report"}
        result = {"success": False, "duration": 200}

        engine.learn_from_task_execution(task, result)

        call_kwargs = mock_ncl_memory.store_semantic_memory.call_args
        content = call_kwargs[1]["content"] if "content" in (call_kwargs[1] or {}) else call_kwargs[0][0]
        assert content["success"] is False
        assert "failed_execution" in content["factors"]
        assert "long_duration" in content["factors"]

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", False)
    def test_learn_disabled_memory_no_op(self):
        """learn_from_task_execution is no-op when memory disabled."""
        engine = LearningEngine.__new__(LearningEngine)
        engine.patterns = {}
        # Should not raise
        engine.learn_from_task_execution({"type": "test"}, {"success": True})

    @patch("ncl_agency_runtime.runtime.learning_engine.MEMORY_ENABLED", True)
    @patch("ncl_agency_runtime.runtime.learning_engine.ncl_memory")
    def test_task_tags_include_type(self, mock_ncl_memory):
        """Stored memory includes task type in tags."""
        engine = LearningEngine.__new__(LearningEngine)
        engine.patterns = {}
        mock_ncl_memory.store_semantic_memory = MagicMock()

        engine.learn_from_task_execution({"type": "weekly_analysis"}, {"success": True})

        call_kwargs = mock_ncl_memory.store_semantic_memory.call_args
        tags = call_kwargs[1]["tags"] if "tags" in (call_kwargs[1] or {}) else call_kwargs[0][1]
        assert "task:weekly_analysis" in tags
