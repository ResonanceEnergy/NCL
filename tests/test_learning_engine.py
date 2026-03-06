#!/usr/bin/env python3
"""
Tests for NCL Learning Engine.
"""
import sys
import tempfile
from pathlib import Path

import pytest

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


# ── Pure-logic helper tests (no memory system needed) ──────


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestAnalyzeTemporalPatterns:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)
        self.engine.patterns = {}

    def test_empty_events(self):
        result = self.engine._analyze_temporal_patterns([])
        assert result["peak_hours"] == []
        assert result["active_days"] == []

    def test_single_hour_peak(self):
        events = [
            {"occurred_at": "2026-03-10T14:00:00Z"},
            {"occurred_at": "2026-03-10T14:30:00Z"},
            {"occurred_at": "2026-03-10T09:00:00Z"},
        ]
        result = self.engine._analyze_temporal_patterns(events)
        assert result["peak_hours"][0][0] == 14  # hour 14 has 2 events

    def test_weekday_vs_weekend(self):
        # Monday (weekday=0) events
        events = [
            {"occurred_at": "2026-03-09T10:00:00Z"},  # Monday
            {"occurred_at": "2026-03-09T11:00:00Z"},  # Monday
        ]
        result = self.engine._analyze_temporal_patterns(events)
        assert result["weekday_vs_weekend"]["weekday_avg"] > 0
        assert result["weekday_vs_weekend"]["weekend_avg"] == 0

    def test_invalid_dates_skipped(self):
        events = [
            {"occurred_at": "not-a-date"},
            {"occurred_at": "2026-03-10T10:00:00Z"},
        ]
        result = self.engine._analyze_temporal_patterns(events)
        assert result["peak_hours"][0][0] == 10

    def test_no_occurred_at_skipped(self):
        events = [{"event_type": "test"}, {}]
        result = self.engine._analyze_temporal_patterns(events)
        assert result["peak_hours"] == []


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestAnalyzeProductivityPatterns:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)
        self.engine.patterns = {}

    def test_empty_events(self):
        result = self.engine._analyze_productivity_patterns([])
        assert result["focus_sessions"]["count"] == 0
        assert result["task_completions"]["count"] == 0

    def test_focus_keywords_detected(self):
        events = [
            {"event_type": "deep_work_start"},
            {"event_type": "focus_mode_on"},
            {"event_type": "unrelated"},
        ]
        result = self.engine._analyze_productivity_patterns(events)
        assert result["focus_sessions"]["count"] == 2

    def test_completion_keywords_detected(self):
        events = [
            {"event_type": "task_completed", "success": True},
            {"event_type": "finished_review", "success": True},
            {"event_type": "done_building", "success": False},
        ]
        result = self.engine._analyze_productivity_patterns(events)
        assert result["task_completions"]["count"] == 3
        assert result["task_completions"]["success_rate"] == pytest.approx(2 / 3)


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestGenerateInsights:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)

    def test_empty_patterns(self):
        assert self.engine._generate_insights({}) == []

    def test_long_focus_sessions(self):
        patterns = {"productivity": {"focus_sessions": {"count": 3, "avg_duration": 90}}}
        insights = self.engine._generate_insights(patterns)
        assert any("deep work" in i for i in insights)

    def test_short_focus_sessions(self):
        patterns = {"productivity": {"focus_sessions": {"count": 3, "avg_duration": 15}}}
        insights = self.engine._generate_insights(patterns)
        assert any("interruptions" in i for i in insights)

    def test_peak_hour_insight(self):
        patterns = {"temporal": {"peak_hours": [(14, 10)]}}
        insights = self.engine._generate_insights(patterns)
        assert any("14:00" in i for i in insights)

    def test_high_weekend_activity(self):
        patterns = {"temporal": {"weekday_vs_weekend": {"weekday_avg": 5, "weekend_avg": 10}}}
        insights = self.engine._generate_insights(patterns)
        assert any("weekend" in i.lower() for i in insights)

    def test_high_weekday_activity(self):
        patterns = {"temporal": {"weekday_vs_weekend": {"weekday_avg": 10, "weekend_avg": 5}}}
        insights = self.engine._generate_insights(patterns)
        assert any("weekday" in i.lower() for i in insights)


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestGenerateRecommendations:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)

    def test_empty_patterns(self):
        # Empty patterns still triggers "low focus sessions" since count defaults to 0 < 5
        recs = self.engine._generate_recommendations({})
        assert any("focus" in r.lower() for r in recs)

    def test_low_focus_sessions(self):
        patterns = {"productivity": {"focus_sessions": {"count": 2}}}
        recs = self.engine._generate_recommendations(patterns)
        assert any("focus" in r.lower() for r in recs)

    def test_peak_hour_scheduling(self):
        patterns = {"temporal": {"peak_hours": [(10, 15), (14, 8)]}}
        recs = self.engine._generate_recommendations(patterns)
        assert any("peak" in r.lower() or "creative" in r.lower() for r in recs)

    def test_no_recommendation_when_good(self):
        patterns = {"productivity": {"focus_sessions": {"count": 10}}, "temporal": {"peak_hours": [(10, 5)]}}
        recs = self.engine._generate_recommendations(patterns)
        # Only peak-hour rec, no focus-session rec
        assert not any("increase" in r.lower() for r in recs)


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestExtractSuccessFactors:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)

    def test_success(self):
        factors = self.engine._extract_success_factors({}, {"success": True})
        assert "successful_execution" in factors

    def test_failure(self):
        factors = self.engine._extract_success_factors({}, {"success": False})
        assert "failed_execution" in factors

    def test_quick_completion(self):
        factors = self.engine._extract_success_factors({}, {"success": True, "duration": 10})
        assert "quick_completion" in factors

    def test_long_duration(self):
        factors = self.engine._extract_success_factors({}, {"success": True, "duration": 200})
        assert "long_duration" in factors

    def test_mid_duration_no_extra_factor(self):
        factors = self.engine._extract_success_factors({}, {"success": True, "duration": 60})
        assert "quick_completion" not in factors
        assert "long_duration" not in factors


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestCalculateAvgDuration:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)

    def test_empty_events(self):
        assert self.engine._calculate_avg_duration([]) == 0

    def test_events_with_duration(self):
        events = [{"data": {"duration": 30}}, {"data": {"duration": 60}}]
        assert self.engine._calculate_avg_duration(events) == 45

    def test_events_without_duration(self):
        events = [{"data": {"quality": "high"}}, {}]
        assert self.engine._calculate_avg_duration(events) == 0


@pytest.mark.skipif(not LEARNING_AVAILABLE, reason="LearningEngine not importable")
class TestAnalyzeQuality:

    def setup_method(self):
        self.engine = LearningEngine.__new__(LearningEngine)

    def test_empty_events(self):
        assert self.engine._analyze_quality([]) == {}

    def test_quality_count(self):
        events = [
            {"data": {"quality": "high"}},
            {"data": {"quality": "high"}},
            {"data": {"quality": "low"}},
        ]
        result = self.engine._analyze_quality(events)
        assert result == {"high": 2, "low": 1}
