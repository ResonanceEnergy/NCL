"""Tests for the Jiang Xueqin Geopolitical Advisor integration.

Covers:
  - Enums and data contracts
  - SignalCollector
  - NarrativeEngine
  - GeopoliticalPipeline
  - AdvisoryBoard
  - AssessmentEngine
  - JiangXueqinAdvisor (unified engine)
  - MandarinAgent (#27)
  - EventTypes (5 new GEOPOL events)
  - Roster integration (27 agents, 17 expansion)
"""

import pytest

# ═══════════════════════════════════════════════════════════════
# §1  Enums
# ═══════════════════════════════════════════════════════════════

class TestEnums:
    def test_geopolitical_lens_values(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import GeopoliticalLens
        assert len(GeopoliticalLens) == 6
        assert GeopoliticalLens.INNOVATION_ECOSYSTEM == "innovation_ecosystem"
        assert GeopoliticalLens.EDUCATION_PIPELINE == "education_pipeline"
        assert GeopoliticalLens.STRATEGIC_COMPETITION == "strategic_competition"
        assert GeopoliticalLens.TRADE_SUPPLY_CHAIN == "trade_supply_chain"
        assert GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY == "technology_sovereignty"
        assert GeopoliticalLens.CULTURAL_DIPLOMACY == "cultural_diplomacy"

    def test_signal_strength_values(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import SignalStrength
        assert len(SignalStrength) == 5
        assert SignalStrength.NOISE == "noise"
        assert SignalStrength.CRITICAL == "critical"

    def test_advisory_tier_values(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryTier
        assert len(AdvisoryTier) == 4
        assert AdvisoryTier.ROUTINE == "routine"
        assert AdvisoryTier.FLASH == "flash"

    def test_region_values(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import Region
        assert len(Region) == 6
        assert Region.CHINA == "china"
        assert Region.GLOBAL == "global"


# ═══════════════════════════════════════════════════════════════
# §2  Data Contracts
# ═══════════════════════════════════════════════════════════════

class TestDataContracts:
    def test_geopolitical_signal_defaults(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import GeopoliticalSignal
        sig = GeopoliticalSignal()
        assert len(sig.signal_id) == 12
        assert sig.credibility == 0.5
        assert len(sig.fingerprint) == 16

    def test_geopolitical_signal_fingerprint_deterministic(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalSignal,
            Region,
        )
        s1 = GeopoliticalSignal(source="gov", headline="test", region=Region.CHINA, fingerprint="")
        s2 = GeopoliticalSignal(source="gov", headline="test", region=Region.CHINA, fingerprint="")
        assert s1.fingerprint == s2.fingerprint

    def test_strategic_assessment_composite(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import StrategicAssessment
        sa = StrategicAssessment(
            lens_scores={"a": 0.8, "b": 0.6},
            overall_risk=0.2,
            overall_opportunity=0.5,
        )
        composite = sa.compute_composite()
        assert 0.0 <= composite <= 1.0

    def test_strategic_assessment_composite_empty(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import StrategicAssessment
        sa = StrategicAssessment()
        assert sa.compute_composite() == 0.0

    def test_advisory_note_defaults(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryNote
        note = AdvisoryNote(title="Test Advisory")
        assert len(note.note_id) == 12
        assert note.title == "Test Advisory"
        assert note.confidence == 0.5

    def test_trend_line_defaults(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import TrendLine
        tl = TrendLine(trend_id="t1", description="test")
        assert tl.direction == "stable"
        assert tl.momentum == 0.0


# ═══════════════════════════════════════════════════════════════
# §3  SignalCollector
# ═══════════════════════════════════════════════════════════════

class TestSignalCollector:
    def test_ingest_basic(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        sig = collector.ingest(
            source="academic_paper",
            region=Region.CHINA,
            lens=GeopoliticalLens.INNOVATION_ECOSYSTEM,
            headline="China R&D spending reaches new high",
        )
        assert sig.source == "academic_paper"
        assert sig.region == Region.CHINA
        assert len(collector.signals) == 1

    def test_ingest_credibility_academic(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        sig = collector.ingest("academic", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "Test")
        assert sig.credibility == 0.85

    def test_ingest_credibility_patent(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        sig = collector.ingest("patent_filing", Region.CHINA, GeopoliticalLens.INNOVATION_ECOSYSTEM, "Test")
        assert sig.credibility == 0.92

    def test_ingest_credibility_unknown(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        sig = collector.ingest("random_blog", Region.GLOBAL, GeopoliticalLens.CULTURAL_DIPLOMACY, "Test")
        assert sig.credibility == 0.5

    def test_deduplication(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        collector.ingest("gov", Region.USA, GeopoliticalLens.STRATEGIC_COMPETITION, "Same headline")
        collector.ingest("gov", Region.USA, GeopoliticalLens.STRATEGIC_COMPETITION, "Same headline")
        assert len(collector.signals) == 1

    def test_strength_classification_critical(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
            SignalStrength,
        )
        collector = SignalCollector()
        sig = collector.ingest(
            "satellite",
            Region.CHINA,
            GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY,
            "Critical event",
            content={"confirmed": True, "policy_change": True, "inflection_point": True},
        )
        assert sig.strength == SignalStrength.CRITICAL

    def test_strength_classification_noise(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
            SignalStrength,
        )
        collector = SignalCollector()
        sig = collector.ingest(
            "social_media",
            Region.GLOBAL,
            GeopoliticalLens.CULTURAL_DIPLOMACY,
            "Random noise",
            content={},
        )
        assert sig.strength == SignalStrength.NOISE

    def test_signals_by_lens(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        collector.ingest("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "H1")
        collector.ingest("gov", Region.USA, GeopoliticalLens.STRATEGIC_COMPETITION, "H2")
        collector.ingest("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "H3")
        edu = collector.signals_by_lens(GeopoliticalLens.EDUCATION_PIPELINE)
        assert len(edu) == 2

    def test_signals_by_region(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        collector.ingest("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "H1")
        collector.ingest("gov", Region.USA, GeopoliticalLens.STRATEGIC_COMPETITION, "H2")
        china = collector.signals_by_region(Region.CHINA)
        assert len(china) == 1

    def test_strong_signals(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        collector.ingest("satellite", Region.CHINA, GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY,
                         "Strong", content={"confirmed": True, "policy_change": True, "inflection_point": True})
        collector.ingest("social_media", Region.GLOBAL, GeopoliticalLens.CULTURAL_DIPLOMACY, "Weak")
        strong = collector.strong_signals()
        assert len(strong) == 1

    def test_summary(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            Region,
            SignalCollector,
        )
        collector = SignalCollector()
        collector.ingest("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "H1")
        collector.ingest("academic", Region.USA, GeopoliticalLens.INNOVATION_ECOSYSTEM, "H2")
        summary = collector.summary()
        assert summary["total_signals"] == 2
        assert "gov" in summary["sources"]
        assert summary["avg_credibility"] > 0.5

    def test_summary_empty(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import SignalCollector
        collector = SignalCollector()
        summary = collector.summary()
        assert summary["total_signals"] == 0
        assert summary["avg_credibility"] == 0.0


# ═══════════════════════════════════════════════════════════════
# §4  NarrativeEngine
# ═══════════════════════════════════════════════════════════════

class TestNarrativeEngine:
    def test_principles(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import NarrativeEngine
        assert len(NarrativeEngine.PRINCIPLES) == 6

    def test_build_narrative_empty(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import NarrativeEngine
        engine = NarrativeEngine()
        result = engine.build_narrative([])
        assert result["status"] == "insufficient_data"
        assert result["signal_count"] == 0

    def test_build_narrative_with_signals(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalSignal,
            NarrativeEngine,
            Region,
            SignalStrength,
        )
        engine = NarrativeEngine()
        signals = [
            GeopoliticalSignal(source="gov", region=Region.CHINA,
                               lens=GeopoliticalLens.EDUCATION_PIPELINE, headline="Edu1",
                               strength=SignalStrength.STRONG, credibility=0.85),
            GeopoliticalSignal(source="think_tank", region=Region.CHINA,
                               lens=GeopoliticalLens.INNOVATION_ECOSYSTEM, headline="Inn1",
                               strength=SignalStrength.MODERATE, credibility=0.80),
        ]
        result = engine.build_narrative(signals, Region.CHINA)
        assert result["status"] == "narrative_built"
        assert result["signal_count"] == 2
        assert result["lens_coverage"] == 2
        assert result["confidence"] > 0.0
        assert len(engine.narratives) == 1

    def test_find_tensions(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalSignal,
            NarrativeEngine,
            Region,
            SignalStrength,
        )
        engine = NarrativeEngine()
        signals = [
            GeopoliticalSignal(source="a", region=Region.CHINA,
                               lens=GeopoliticalLens.STRATEGIC_COMPETITION, headline="Pos",
                               strength=SignalStrength.STRONG, credibility=0.8,
                               tags=["growth", "opportunity"]),
            GeopoliticalSignal(source="b", region=Region.CHINA,
                               lens=GeopoliticalLens.STRATEGIC_COMPETITION, headline="Neg",
                               strength=SignalStrength.STRONG, credibility=0.8,
                               tags=["decline", "risk"]),
        ]
        result = engine.build_narrative(signals, Region.CHINA)
        assert len(result["tensions"]) == 1
        assert result["tensions"][0]["type"] == "opposing_signals"

    def test_structural_filter(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalSignal,
            NarrativeEngine,
            Region,
            SignalStrength,
        )
        engine = NarrativeEngine()
        signals = [
            GeopoliticalSignal(source="a", region=Region.CHINA,
                               lens=GeopoliticalLens.EDUCATION_PIPELINE, headline="Structural",
                               strength=SignalStrength.STRONG, credibility=0.9,
                               content={"policy_change": True}),
            GeopoliticalSignal(source="b", region=Region.CHINA,
                               lens=GeopoliticalLens.CULTURAL_DIPLOMACY, headline="Surface",
                               strength=SignalStrength.NOISE, credibility=0.3),
        ]
        filtered = engine.apply_structural_filter(signals)
        assert len(filtered) == 1
        assert filtered[0].headline == "Structural"

    def test_structural_filter_by_tags(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalSignal,
            NarrativeEngine,
            Region,
            SignalStrength,
        )
        engine = NarrativeEngine()
        signals = [
            GeopoliticalSignal(source="a", region=Region.CHINA,
                               lens=GeopoliticalLens.EDUCATION_PIPELINE, headline="Tagged",
                               strength=SignalStrength.WEAK, credibility=0.5,
                               tags=["education_reform"]),
        ]
        filtered = engine.apply_structural_filter(signals)
        assert len(filtered) == 1


# ═══════════════════════════════════════════════════════════════
# §5  GeopoliticalPipeline
# ═══════════════════════════════════════════════════════════════

class TestGeopoliticalPipeline:
    def test_collect(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        sig = pipe.collect("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "Test")
        assert sig.source == "gov"
        assert len(pipe.collector.signals) == 1

    def test_analyze_empty(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import GeopoliticalPipeline
        pipe = GeopoliticalPipeline()
        result = pipe.analyze()
        assert result["status"] == "insufficient_data"

    def test_analyze_with_signals(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        pipe.collect("satellite", Region.CHINA, GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY,
                     "Tech shift", content={"confirmed": True, "structural_shift": True})
        result = pipe.analyze(Region.CHINA)
        assert result["signal_count"] >= 1

    def test_track_trend(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        pipe.track_trend("t1", GeopoliticalLens.INNOVATION_ECOSYSTEM, Region.CHINA, "Innovation index", 0.5)
        pipe.track_trend("t1", GeopoliticalLens.INNOVATION_ECOSYSTEM, Region.CHINA, "Innovation index", 0.6)
        pipe.track_trend("t1", GeopoliticalLens.INNOVATION_ECOSYSTEM, Region.CHINA, "Innovation index", 0.7)
        assert "t1" in pipe.trends
        assert pipe.trends["t1"].direction == "rising"

    def test_track_trend_falling(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        for val in [0.9, 0.7, 0.5]:
            pipe.track_trend("t2", GeopoliticalLens.TRADE_SUPPLY_CHAIN, Region.GLOBAL, "Trade index", val)
        assert pipe.trends["t2"].direction == "falling"

    def test_generate_advisory(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        pipe.collect("gov", Region.CHINA, GeopoliticalLens.STRATEGIC_COMPETITION, "Competition event")
        advisory = pipe.generate_advisory(Region.CHINA)
        assert advisory.region == Region.CHINA
        assert len(pipe.advisories) == 1

    def test_classify_tier_flash(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            AdvisoryTier,
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        for i in range(3):
            pipe.collect(
                "satellite", Region.CHINA, GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY,
                f"Critical {i}",
                content={"confirmed": True, "policy_change": True, "inflection_point": True},
            )
        advisory = pipe.generate_advisory(Region.CHINA)
        assert advisory.tier == AdvisoryTier.FLASH

    def test_run_cycle(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        pipe.collect("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "Signal 1")
        pipe.collect("academic", Region.USA, GeopoliticalLens.INNOVATION_ECOSYSTEM, "Signal 2")
        result = pipe.run_cycle()
        assert result["status"] == "cycle_complete"
        assert result["cycle"] == 1
        assert result["narratives_built"] >= 1

    def test_pipeline_health(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import GeopoliticalPipeline
        pipe = GeopoliticalPipeline()
        health = pipe.pipeline_health()
        assert health["status"] == "starved"
        assert health["total_signals"] == 0

    def test_pipeline_health_healthy(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            GeopoliticalLens,
            GeopoliticalPipeline,
            Region,
        )
        pipe = GeopoliticalPipeline()
        pipe.collect("gov", Region.CHINA, GeopoliticalLens.EDUCATION_PIPELINE, "H1")
        health = pipe.pipeline_health()
        assert health["status"] == "healthy"


# ═══════════════════════════════════════════════════════════════
# §6  AdvisoryBoard
# ═══════════════════════════════════════════════════════════════

class TestAdvisoryBoard:
    def test_jiang_xueqin_pre_registered(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryBoard
        board = AdvisoryBoard()
        jx = board.get_advisor("jiang_xueqin")
        assert jx is not None
        assert jx["name"] == "Jiang Xueqin"
        assert jx["credibility"] == 0.92

    def test_jiang_xueqin_expertise(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryBoard
        board = AdvisoryBoard()
        jx = board.get_advisor("jiang_xueqin")
        assert jx is not None
        assert len(jx["expertise"]) == 6
        assert "China innovation ecosystem" in jx["expertise"]

    def test_register_advisor(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryBoard
        board = AdvisoryBoard()
        advisor = board.register_advisor("test_id", "Test Advisor", "Analyst")
        assert advisor["advisor_id"] == "test_id"
        assert len(board.advisors) == 2  # Jiang Xueqin + Test

    def test_consult(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryBoard
        board = AdvisoryBoard()
        result = board.consult("jiang_xueqin", "What about China innovation?")
        assert result["status"] == "consulted"
        assert result["advisor"] == "Jiang Xueqin"
        assert result["expertise_match"] > 0.0

    def test_consult_not_found(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryBoard
        board = AdvisoryBoard()
        result = board.consult("nonexistent", "question")
        assert result["status"] == "advisor_not_found"

    def test_board_summary(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AdvisoryBoard
        board = AdvisoryBoard()
        summary = board.board_summary()
        assert summary["total_advisors"] == 1
        assert summary["advisors"][0]["name"] == "Jiang Xueqin"


# ═══════════════════════════════════════════════════════════════
# §7  AssessmentEngine
# ═══════════════════════════════════════════════════════════════

class TestAssessmentEngine:
    def test_assess_empty(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AssessmentEngine
        engine = AssessmentEngine()
        result = engine.assess([])
        assert result.narrative == "Insufficient signals for assessment."

    def test_assess_with_signals(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            AssessmentEngine,
            GeopoliticalLens,
            GeopoliticalSignal,
            Region,
            SignalStrength,
        )
        engine = AssessmentEngine()
        signals = [
            GeopoliticalSignal(source="gov", region=Region.CHINA,
                               lens=GeopoliticalLens.EDUCATION_PIPELINE, headline="H1",
                               strength=SignalStrength.STRONG, credibility=0.85,
                               tags=["growth", "reform"]),
            GeopoliticalSignal(source="academic", region=Region.CHINA,
                               lens=GeopoliticalLens.INNOVATION_ECOSYSTEM, headline="H2",
                               strength=SignalStrength.MODERATE, credibility=0.80,
                               tags=["innovation"]),
        ]
        result = engine.assess(signals, Region.CHINA, 10)
        assert result.signal_count == 2
        assert result.horizon_years == 10
        assert result.overall_risk >= 0.0
        assert result.overall_opportunity >= 0.0
        assert result.confidence > 0.0
        assert len(engine.assessments) == 1

    def test_risk_detection(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            AssessmentEngine,
            GeopoliticalLens,
            GeopoliticalSignal,
            Region,
            SignalStrength,
        )
        engine = AssessmentEngine()
        signals = [
            GeopoliticalSignal(source="gov", region=Region.CHINA,
                               lens=GeopoliticalLens.STRATEGIC_COMPETITION, headline="Conflict",
                               strength=SignalStrength.STRONG, credibility=0.8,
                               tags=["risk", "conflict", "sanction"]),
        ]
        result = engine.assess(signals, Region.CHINA)
        assert result.overall_risk > 0.0

    def test_opportunity_detection(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            AssessmentEngine,
            GeopoliticalLens,
            GeopoliticalSignal,
            Region,
            SignalStrength,
        )
        engine = AssessmentEngine()
        signals = [
            GeopoliticalSignal(source="trade_data", region=Region.ASIA_PACIFIC,
                               lens=GeopoliticalLens.TRADE_SUPPLY_CHAIN, headline="Cooperation",
                               strength=SignalStrength.STRONG, credibility=0.88,
                               tags=["growth", "cooperation", "opportunity"]),
        ]
        result = engine.assess(signals, Region.ASIA_PACIFIC)
        assert result.overall_opportunity > 0.0

    def test_recommendations_include_coverage_gap(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import (
            AssessmentEngine,
            GeopoliticalLens,
            GeopoliticalSignal,
            Region,
            SignalStrength,
        )
        engine = AssessmentEngine()
        # Only one lens covered -> should flag gaps
        signals = [
            GeopoliticalSignal(source="gov", region=Region.CHINA,
                               lens=GeopoliticalLens.EDUCATION_PIPELINE, headline="H1",
                               strength=SignalStrength.MODERATE, credibility=0.8),
        ]
        result = engine.assess(signals, Region.CHINA)
        gap_recs = [r for r in result.recommendations if "Coverage gap" in r]
        assert len(gap_recs) >= 1

    def test_risk_weights(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import AssessmentEngine
        weights = AssessmentEngine.RISK_WEIGHTS
        assert len(weights) == 6
        assert abs(sum(weights.values()) - 1.0) < 0.01


# ═══════════════════════════════════════════════════════════════
# §8  JiangXueqinAdvisor (unified engine)
# ═══════════════════════════════════════════════════════════════

class TestJiangXueqinAdvisor:
    def test_initialize(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        result = advisor.initialize()
        assert result["status"] == "initialized"
        assert result["advisor"] == "Jiang Xueqin"
        assert result["lessons"] == 6
        assert result["lenses"] == 6
        assert result["trends_seeded"] == 5
        assert result["board_advisors"] == 1

    def test_lessons_constant(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        assert len(JiangXueqinAdvisor.LESSONS) == 6
        lesson_names = {lesson["name"] for lesson in JiangXueqinAdvisor.LESSONS}
        assert "innovation_over_imitation" in lesson_names
        assert "education_as_predictor" in lesson_names
        assert "bridge_perspectives" in lesson_names
        assert "structural_over_surface" in lesson_names
        assert "data_driven_narrative" in lesson_names
        assert "long_horizon_thinking" in lesson_names

    def test_score_lessons_perfect(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        result = advisor.score_lessons({
            "innovation_over_imitation": True,
            "education_as_predictor": True,
            "bridge_perspectives": True,
            "structural_over_surface": True,
            "data_driven_narrative": True,
            "long_horizon_thinking": True,
        })
        assert result["score"] == 1.0
        assert result["grade"] == "S"
        assert len(result["lessons_violated"]) == 0

    def test_score_lessons_partial(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        result = advisor.score_lessons({
            "innovation_over_imitation": True,
            "education_as_predictor": True,
        })
        assert result["score"] == pytest.approx(2.0 / 6.0, abs=0.01)
        assert result["grade"] == "D"
        assert len(result["lessons_violated"]) == 4

    def test_score_lessons_none(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        result = advisor.score_lessons({})
        assert result["score"] == 0.0
        assert result["grade"] == "F"

    def test_consult_advisor(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        advisor.initialize()
        result = advisor.consult_advisor("What about China innovation ecosystem trends?")
        assert result["status"] == "consulted"
        assert result["credibility"] == 0.92

    def test_ingest_signal(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        advisor.initialize()
        result = advisor.ingest_signal(
            source="government",
            region="china",
            lens="education_pipeline",
            headline="New STEM curriculum nationwide",
            tags=["education_reform"],
        )
        assert result["status"] == "signal_ingested"
        assert result["region"] == "china"
        assert result["lens"] == "education_pipeline"

    def test_strategic_assessment(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        advisor.initialize()
        advisor.ingest_signal("gov", "china", "education_pipeline", "H1",
                              content={"confirmed": True}, tags=["growth"])
        result = advisor.strategic_assessment("china")
        assert result["status"] == "assessed"
        assert result["region"] == "china"

    def test_run_pipeline_cycle(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        advisor.initialize()
        advisor.ingest_signal("gov", "china", "education_pipeline", "H1")
        advisor.ingest_signal("academic", "usa", "innovation_ecosystem", "H2")
        result = advisor.run_pipeline_cycle()
        assert result["status"] == "cycle_complete"
        assert result["cycle"] == 1

    def test_operational_readiness_not_ready(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        result = advisor.operational_readiness()
        assert result["status"] in ("NOT_READY", "LIMITED")

    def test_operational_readiness_after_init(self):
        from ncl_agency_runtime.fpc.geopolitical_advisor import JiangXueqinAdvisor
        advisor = JiangXueqinAdvisor()
        advisor.initialize()
        result = advisor.operational_readiness()
        # After init but no signals collected, some checks will fail
        assert result["readiness_score"] > 0.0
        assert result["components"]["advisors"] == 1


# ═══════════════════════════════════════════════════════════════
# §9  MandarinAgent
# ═══════════════════════════════════════════════════════════════

class TestMandarinAgent:
    def test_codename_callsign(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        agent = MandarinAgent()
        assert agent.codename == "jx"
        assert agent.callsign == "MANDARIN"

    def test_handle_default(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Test")
        result = agent.handle(task, {"payload": {}})
        assert result["status"] == "assessment_complete"
        assert "_callsign" in result
        assert result["_callsign"] == "MANDARIN"

    def test_handle_assess(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Assess")
        result = agent.handle(task, {"payload": {"action": "assess", "region": "global"}})
        assert result["status"] == "assessment_complete"

    def test_handle_advisory(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Advisory")
        result = agent.handle(task, {"payload": {"action": "advisory", "question": "China trends?"}})
        assert result["status"] == "advisor_consulted"

    def test_handle_pipeline(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Pipeline")
        result = agent.handle(task, {"payload": {"action": "pipeline"}})
        assert result["status"] == "pipeline_cycle_complete"

    def test_handle_ingest(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Ingest")
        result = agent.handle(task, {"payload": {
            "action": "ingest",
            "source": "gov",
            "region": "china",
            "lens": "education_pipeline",
            "headline": "Test signal",
        }})
        assert result["status"] == "signal_ingested"

    def test_handle_lessons(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Lessons")
        result = agent.handle(task, {"payload": {"action": "lessons", "context": {
            "innovation_over_imitation": True,
            "bridge_perspectives": True,
        }}})
        assert result["status"] == "lessons_scored"
        assert result["score"] > 0.0

    def test_handle_readiness(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Readiness")
        result = agent.handle(task, {"payload": {"action": "readiness"}})
        assert result["status"] == "readiness_checked"

    def test_handle_narrative(self):
        from ncl_agency_runtime.fpc.agents.expansion import MandarinAgent
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        agent = MandarinAgent()
        task = Task("T-jx", "jx", "Narrative")
        result = agent.handle(task, {"payload": {"action": "narrative", "region": "global"}})
        assert result["status"] in ("narrative_built", "insufficient_data")


# ═══════════════════════════════════════════════════════════════
# §10  EventTypes
# ═══════════════════════════════════════════════════════════════

class TestGeoPolEventTypes:
    def test_geopol_signal(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.GEOPOL_SIGNAL == "geopol.signal"

    def test_geopol_assessment(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.GEOPOL_ASSESSMENT == "geopol.assessment"

    def test_geopol_narrative(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.GEOPOL_NARRATIVE == "geopol.narrative"

    def test_geopol_pipeline(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.GEOPOL_PIPELINE == "geopol.pipeline"

    def test_geopol_advisory(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.GEOPOL_ADVISORY == "geopol.advisory"

    def test_total_event_types(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        # 13 core + 4 wolfram + 10 triad + 8 unit8200 + 5 geopol = 40
        assert len(EventType) == 71


# ═══════════════════════════════════════════════════════════════
# §11  Roster Integration
# ═══════════════════════════════════════════════════════════════

class TestRosterIntegration:
    def test_total_agents_27(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_expansion_pack_17(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        assert len(EXPANSION_PACK) == 21

    def test_mandarin_in_roster(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        mandarin = get_agent("jx")
        assert mandarin is not None
        assert mandarin.callsign == "MANDARIN"
        assert mandarin.name == "Geopolitical Intelligence Advisor"

    def test_mandarin_callsign_map(self):
        from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
        assert CALLSIGN_MAP["jx"] == "MANDARIN"

    def test_mandarin_by_callsign(self):
        from ncl_agency_runtime.fpc.agents import get_agent_by_callsign
        agent = get_agent_by_callsign("MANDARIN")
        assert agent is not None
        assert agent.codename == "jx"

    def test_mandarin_capabilities(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        mandarin = get_agent("jx")
        assert mandarin is not None
        assert len(mandarin.capabilities) == 6
        assert any("Jiang Xueqin" in c for c in mandarin.capabilities)

    def test_expansion_stubs_17(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert len(EXPANSION_STUBS) == 21
        assert "jx" in EXPANSION_STUBS

    def test_mandarin_in_stubs_callable(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        stub = EXPANSION_STUBS["jx"]
        task = Task("T-jx", "jx", "Test")
        result = stub.handle(task, {"payload": {}})
        assert "_callsign" in result
        assert result["_callsign"] == "MANDARIN"
