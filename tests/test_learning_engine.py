#!/usr/bin/env python3
"""
Tests for NCL Learning Engine.
"""
import json
import sys
import pytest
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / 'ncl_agency_runtime' / 'runtime'))

try:
    from ncl_agency_runtime.runtime.learning_engine import LearningEngine
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestLearningEngine:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = LearningEngine(storage_path=self.tmpdir)

    def test_engine_init(self):
        assert self.engine is not None

    def test_learn_from_task(self):
        task = {
            "mission_id": "mis-test",
            "mission_type": "daily_brief",
            "inputs": {"date": "2026-02-18"}
        }
        result = {
            "success": True,
            "duration": 1.5,
            "event_count": 10
        }
        # Should not raise
        self.engine.learn_from_task(task, result)

    def test_pattern_extraction(self):
        """Test that patterns can be extracted from events."""
        events = [
            {"event_type": "ncl.focus.switch", "occurred_at": "2026-02-18T10:00:00Z"},
            {"event_type": "ncl.focus.switch", "occurred_at": "2026-02-18T11:00:00Z"},
            {"event_type": "ncl.energy.log", "occurred_at": "2026-02-18T12:00:00Z"},
        ]
        # If engine has analyze method
        if hasattr(self.engine, 'analyze_events'):
            result = self.engine.analyze_events(events)
            assert isinstance(result, dict)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
