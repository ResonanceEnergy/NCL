"""Tests for AI Daily Brief & Exponential Intelligence Engine.

Covers NLW's AI Daily Brief taxonomy, Diamandis 6 D's, abundance,
convergence, metatrends, moonshots, lessons learned, and BeaconAgent
integration with the Future Predictor Council.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# §1  Enum Tests
# ═══════════════════════════════════════════════════════════════


class TestBriefingCategory:
    def test_all_values(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        assert len(BriefingCategory) == 10
        assert BriefingCategory.AI_POLICY == "ai_policy"
        assert BriefingCategory.AI_SAFETY == "ai_safety"
        assert BriefingCategory.AI_INDUSTRY == "ai_industry"
        assert BriefingCategory.AI_MODELS == "ai_models"
        assert BriefingCategory.AI_REGULATION == "ai_regulation"
        assert BriefingCategory.AI_BUSINESS == "ai_business"
        assert BriefingCategory.AI_GEOPOLITICS == "ai_geopolitics"
        assert BriefingCategory.AI_RESEARCH == "ai_research"
        assert BriefingCategory.AI_OPEN_SOURCE == "ai_open_source"
        assert BriefingCategory.AI_ETHICS == "ai_ethics"


class TestExponentialStage:
    def test_six_ds(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage
        assert len(ExponentialStage) == 6
        stages = list(ExponentialStage)
        assert stages[0] == "digitized"
        assert stages[1] == "deceptive"
        assert stages[2] == "disruptive"
        assert stages[3] == "demonetized"
        assert stages[4] == "dematerialized"
        assert stages[5] == "democratized"


class TestTechnologyDomain:
    def test_all_domains(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import TechnologyDomain
        assert len(TechnologyDomain) == 10
        assert TechnologyDomain.ARTIFICIAL_INTELLIGENCE == "artificial_intelligence"
        assert TechnologyDomain.ROBOTICS == "robotics"
        assert TechnologyDomain.LONGEVITY == "longevity"


class TestInsightTier:
    def test_tier_hierarchy(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import InsightTier
        assert len(InsightTier) == 5
        tiers = list(InsightTier)
        assert tiers[0] == "background"
        assert tiers[4] == "paradigm_shift"


class TestConvergenceType:
    def test_all_types(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceType
        assert len(ConvergenceType) == 5
        assert ConvergenceType.SYNERGISTIC == "synergistic"
        assert ConvergenceType.DISRUPTIVE_CONVERGENCE == "disruptive_convergence"


class TestAbundanceDomain:
    def test_all_domains(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        assert len(AbundanceDomain) == 8
        assert AbundanceDomain.ENERGY == "energy"
        assert AbundanceDomain.HEALTHCARE == "healthcare"
        assert AbundanceDomain.EDUCATION == "education"


# ═══════════════════════════════════════════════════════════════
# §2  Dataclass Tests
# ═══════════════════════════════════════════════════════════════


class TestAIBriefing:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AIBriefing, BriefingCategory
        b = AIBriefing()
        assert b.source == "ai_daily_brief"
        assert b.category == BriefingCategory.AI_INDUSTRY
        assert b.tags == []
        assert b.implications == []

    def test_fingerprint(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AIBriefing
        b = AIBriefing(title="test", source="nlw")
        fp = b.compute_fingerprint()
        assert len(fp) == 16
        assert fp == b.fingerprint

    def test_fingerprint_deterministic(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AIBriefing
        b1 = AIBriefing(title="same", source="same")
        b2 = AIBriefing(title="same", source="same")
        assert b1.compute_fingerprint() == b2.compute_fingerprint()


class TestExponentialSignal:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialSignal, ExponentialStage, TechnologyDomain
        s = ExponentialSignal()
        assert s.technology == TechnologyDomain.ARTIFICIAL_INTELLIGENCE
        assert s.stage == ExponentialStage.DIGITIZED
        assert s.velocity == 0.0

    def test_advance_stage(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialSignal, ExponentialStage
        s = ExponentialSignal(stage=ExponentialStage.DIGITIZED)
        new_stage = s.advance_stage()
        assert new_stage == ExponentialStage.DECEPTIVE
        assert s.stage == ExponentialStage.DECEPTIVE

    def test_advance_stage_at_end(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialSignal, ExponentialStage
        s = ExponentialSignal(stage=ExponentialStage.DEMOCRATIZED)
        new_stage = s.advance_stage()
        assert new_stage == ExponentialStage.DEMOCRATIZED  # stays at end

    def test_score_impact(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialSignal, ExponentialStage
        s = ExponentialSignal(stage=ExponentialStage.DISRUPTIVE, evidence=["a", "b", "c"])
        score = s.score_impact()
        assert 0.0 < score <= 1.0
        assert score == s.impact_score


class TestConvergenceEvent:
    def test_compute_multiplier(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceEvent, ConvergenceType, TechnologyDomain
        e = ConvergenceEvent(
            technologies=[TechnologyDomain.ARTIFICIAL_INTELLIGENCE, TechnologyDomain.ROBOTICS],
            convergence_type=ConvergenceType.SYNERGISTIC,
        )
        m = e.compute_multiplier()
        assert m > 1.0
        assert m == e.impact_multiplier

    def test_disruptive_highest(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceEvent, ConvergenceType, TechnologyDomain
        e = ConvergenceEvent(
            technologies=[TechnologyDomain.ARTIFICIAL_INTELLIGENCE],
            convergence_type=ConvergenceType.DISRUPTIVE_CONVERGENCE,
        )
        m = e.compute_multiplier()
        assert m >= 2.0


class TestAbundanceAssessment:
    def test_abundance_score(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceAssessment, TechnologyDomain
        a = AbundanceAssessment(
            current_scarcity=0.3,
            enabling_technologies=[TechnologyDomain.ARTIFICIAL_INTELLIGENCE],
        )
        score = a.abundance_score()
        assert 0.0 <= score <= 1.0
        assert score > 0.5  # low scarcity = high abundance

    def test_high_scarcity(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceAssessment
        a = AbundanceAssessment(current_scarcity=0.9)
        score = a.abundance_score()
        assert score < 0.5


class TestMetatrend:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import Metatrend
        m = Metatrend(name="AI everywhere")
        assert m.name == "AI everywhere"
        assert m.horizon_years == 20
        assert m.momentum == 0.0
        assert m.evidence_count == 0


class TestMoonshotIdea:
    def test_moonshot_score(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import MoonshotIdea
        m = MoonshotIdea(
            title="Cure aging",
            feasibility=0.6,
            impact_potential=0.9,
            mtp_alignment=0.8,
        )
        score = m.moonshot_score()
        assert 0.0 <= score <= 1.0

    def test_high_mtp_high_score(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import MoonshotIdea
        high = MoonshotIdea(feasibility=0.8, impact_potential=0.9, mtp_alignment=1.0)
        low = MoonshotIdea(feasibility=0.8, impact_potential=0.9, mtp_alignment=0.0)
        assert high.moonshot_score() > low.moonshot_score()


class TestBriefingDigest:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingDigest
        d = BriefingDigest(date="2026-03-09")
        assert d.date == "2026-03-09"
        assert d.overall_tempo == "normal"
        assert d.key_insights == []


# ═══════════════════════════════════════════════════════════════
# §3  BriefingCollector Tests
# ═══════════════════════════════════════════════════════════════


class TestBriefingCollector:
    def _make_collector(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCollector
        return BriefingCollector()

    def test_ingest_basic(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        c = self._make_collector()
        b = c.ingest("GPT-5 released", "OpenAI releases GPT-5", BriefingCategory.AI_MODELS)
        assert b.title == "GPT-5 released"
        assert b.briefing_id in c.briefings

    def test_deduplication(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        c = self._make_collector()
        c.ingest("Same title", "Same headline", BriefingCategory.AI_POLICY, tags=["a"])
        c.ingest("Same title", "Same headline", BriefingCategory.AI_POLICY, tags=["a"])
        assert len(c.briefings) == 1

    def test_category_counts(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        c = self._make_collector()
        c.ingest("A", "H1", BriefingCategory.AI_SAFETY)
        c.ingest("B", "H2", BriefingCategory.AI_SAFETY)
        c.ingest("C", "H3", BriefingCategory.AI_MODELS)
        assert c.category_counts["ai_safety"] == 2
        assert c.category_counts["ai_models"] == 1

    def test_get_by_category(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        c = self._make_collector()
        c.ingest("A", "H1", BriefingCategory.AI_SAFETY)
        c.ingest("B", "H2", BriefingCategory.AI_MODELS)
        safety = c.get_by_category(BriefingCategory.AI_SAFETY)
        assert len(safety) == 1

    def test_get_by_tier(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory, InsightTier
        c = self._make_collector()
        c.ingest("A", "H1", BriefingCategory.AI_SAFETY, tier=InsightTier.BREAKTHROUGH)
        c.ingest("B", "H2", BriefingCategory.AI_MODELS, tier=InsightTier.BACKGROUND)
        high = c.get_by_tier(InsightTier.SIGNIFICANT)
        assert len(high) == 1  # only breakthrough

    def test_top_category(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        c = self._make_collector()
        c.ingest("A", "H1", BriefingCategory.AI_SAFETY)
        c.ingest("B", "H2", BriefingCategory.AI_SAFETY)
        c.ingest("C", "H3", BriefingCategory.AI_MODELS)
        assert c.top_category() == "ai_safety"

    def test_stats(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        c = self._make_collector()
        c.ingest("A", "H1", BriefingCategory.AI_SAFETY)
        stats = c.stats()
        assert stats["total_briefings"] == 1
        assert stats["unique_fingerprints"] == 1


# ═══════════════════════════════════════════════════════════════
# §4  ExponentialTracker Tests
# ═══════════════════════════════════════════════════════════════


class TestExponentialTracker:
    def _make_tracker(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialTracker
        return ExponentialTracker()

    def test_track_signal(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        t = self._make_tracker()
        s = t.track(TechnologyDomain.ARTIFICIAL_INTELLIGENCE, ExponentialStage.DISRUPTIVE, "LLMs")
        assert s.signal_id in t.signals
        assert s.impact_score > 0

    def test_get_by_technology(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        t = self._make_tracker()
        t.track(TechnologyDomain.ROBOTICS, ExponentialStage.DECEPTIVE)
        t.track(TechnologyDomain.ARTIFICIAL_INTELLIGENCE, ExponentialStage.DISRUPTIVE)
        robotics = t.get_by_technology(TechnologyDomain.ROBOTICS)
        assert len(robotics) == 1

    def test_get_by_stage(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        t = self._make_tracker()
        t.track(TechnologyDomain.ROBOTICS, ExponentialStage.DECEPTIVE)
        t.track(TechnologyDomain.ARTIFICIAL_INTELLIGENCE, ExponentialStage.DECEPTIVE)
        deceptive = t.get_by_stage(ExponentialStage.DECEPTIVE)
        assert len(deceptive) == 2

    def test_furthest_stage(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        t = self._make_tracker()
        t.track(TechnologyDomain.ARTIFICIAL_INTELLIGENCE, ExponentialStage.DIGITIZED)
        t.track(TechnologyDomain.ARTIFICIAL_INTELLIGENCE, ExponentialStage.DISRUPTIVE)
        furthest = t.furthest_stage(TechnologyDomain.ARTIFICIAL_INTELLIGENCE)
        assert furthest == ExponentialStage.DISRUPTIVE

    def test_furthest_stage_none(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import TechnologyDomain
        t = self._make_tracker()
        assert t.furthest_stage(TechnologyDomain.QUANTUM_COMPUTING) is None

    def test_velocity_zero_single(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        t = self._make_tracker()
        t.track(TechnologyDomain.ROBOTICS, ExponentialStage.DIGITIZED)
        assert t.velocity(TechnologyDomain.ROBOTICS) == 0.0

    def test_stats(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        t = self._make_tracker()
        t.track(TechnologyDomain.ROBOTICS, ExponentialStage.DIGITIZED)
        stats = t.stats()
        assert stats["total_signals"] == 1
        assert stats["technologies_tracked"] == 1


# ═══════════════════════════════════════════════════════════════
# §5  ConvergenceAnalyzer Tests
# ═══════════════════════════════════════════════════════════════


class TestConvergenceAnalyzer:
    def _make_analyzer(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceAnalyzer
        return ConvergenceAnalyzer()

    def test_detect(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceType, TechnologyDomain
        a = self._make_analyzer()
        e = a.detect(
            [TechnologyDomain.ARTIFICIAL_INTELLIGENCE, TechnologyDomain.ROBOTICS],
            ConvergenceType.SYNERGISTIC,
        )
        assert e.convergence_id in a.convergences
        assert e.impact_multiplier > 1.0

    def test_get_by_technology(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import TechnologyDomain
        a = self._make_analyzer()
        a.detect([TechnologyDomain.ARTIFICIAL_INTELLIGENCE, TechnologyDomain.ROBOTICS])
        results = a.get_by_technology(TechnologyDomain.ARTIFICIAL_INTELLIGENCE)
        assert len(results) == 1

    def test_highest_impact(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceType, TechnologyDomain
        a = self._make_analyzer()
        a.detect([TechnologyDomain.ARTIFICIAL_INTELLIGENCE], ConvergenceType.SEQUENTIAL)
        a.detect(
            [TechnologyDomain.ARTIFICIAL_INTELLIGENCE, TechnologyDomain.BIOTECHNOLOGY],
            ConvergenceType.DISRUPTIVE_CONVERGENCE,
        )
        top = a.highest_impact(1)
        assert len(top) == 1
        assert top[0].convergence_type == ConvergenceType.DISRUPTIVE_CONVERGENCE

    def test_stats(self):
        a = self._make_analyzer()
        stats = a.stats()
        assert stats["total_convergences"] == 0
        assert stats["avg_impact_multiplier"] == 0.0


# ═══════════════════════════════════════════════════════════════
# §6  AbundanceScorer Tests
# ═══════════════════════════════════════════════════════════════


class TestAbundanceScorer:
    def _make_scorer(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceScorer
        return AbundanceScorer()

    def test_assess(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain, TechnologyDomain
        s = self._make_scorer()
        a = s.assess(
            AbundanceDomain.ENERGY,
            current_scarcity=0.6,
            enabling_technologies=[TechnologyDomain.ARTIFICIAL_INTELLIGENCE],
            enablers=["solar", "fusion"],
            barriers=["policy"],
        )
        assert a.assessment_id in s.assessments
        assert a.abundance_trajectory != 0.0

    def test_most_abundant(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        s = self._make_scorer()
        s.assess(AbundanceDomain.ENERGY, current_scarcity=0.8)
        s.assess(AbundanceDomain.INFORMATION, current_scarcity=0.1)
        most = s.most_abundant()
        assert most is not None
        assert most.domain == AbundanceDomain.INFORMATION

    def test_most_scarce(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        s = self._make_scorer()
        s.assess(AbundanceDomain.ENERGY, current_scarcity=0.8)
        s.assess(AbundanceDomain.INFORMATION, current_scarcity=0.1)
        scarce = s.most_scarce()
        assert scarce is not None
        assert scarce.domain == AbundanceDomain.ENERGY

    def test_most_abundant_empty(self):
        s = self._make_scorer()
        assert s.most_abundant() is None

    def test_stats(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        s = self._make_scorer()
        s.assess(AbundanceDomain.EDUCATION, current_scarcity=0.5)
        stats = s.stats()
        assert stats["total_assessments"] == 1
        assert stats["domains_assessed"] == 1


# ═══════════════════════════════════════════════════════════════
# §7  MetatrendEngine Tests
# ═══════════════════════════════════════════════════════════════


class TestMetatrendEngine:
    def _make_engine(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import MetatrendEngine
        return MetatrendEngine()

    def test_register(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import TechnologyDomain
        e = self._make_engine()
        t = e.register("AI everywhere", "AI permeates all industries",
                        [TechnologyDomain.ARTIFICIAL_INTELLIGENCE])
        assert t.trend_id in e.trends
        assert t.name == "AI everywhere"

    def test_add_evidence(self):
        e = self._make_engine()
        t = e.register("Trend1", "Desc")
        assert e.add_evidence(t.trend_id, "New evidence found")
        assert e.trends[t.trend_id].evidence_count == 1
        assert e.trends[t.trend_id].momentum > 0

    def test_add_evidence_invalid(self):
        e = self._make_engine()
        assert not e.add_evidence("nonexistent", "data")

    def test_accelerating(self):
        e = self._make_engine()
        t = e.register("Fast", "Accelerating")
        e.add_evidence(t.trend_id, "ev1")
        accel = e.accelerating()
        assert len(accel) == 1

    def test_by_technology(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import TechnologyDomain
        e = self._make_engine()
        e.register("AI trend", "Desc", [TechnologyDomain.ARTIFICIAL_INTELLIGENCE])
        e.register("Biotech trend", "Desc", [TechnologyDomain.BIOTECHNOLOGY])
        ai_trends = e.by_technology(TechnologyDomain.ARTIFICIAL_INTELLIGENCE)
        assert len(ai_trends) == 1

    def test_stats(self):
        e = self._make_engine()
        stats = e.stats()
        assert stats["total_trends"] == 0
        assert stats["accelerating_count"] == 0


# ═══════════════════════════════════════════════════════════════
# §8  MoonshotFactory Tests
# ═══════════════════════════════════════════════════════════════


class TestMoonshotFactory:
    def _make_factory(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import MoonshotFactory
        return MoonshotFactory()

    def test_create(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        f = self._make_factory()
        m = f.create("Cure aging", AbundanceDomain.HEALTHCARE,
                      "80yr lifespan", "200yr lifespan",
                      ["ai_biotech", "crispr_ai"], mtp_alignment=0.9)
        assert m.idea_id in f.ideas
        assert m.feasibility > 0
        assert m.impact_potential > 0

    def test_top_moonshots(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        f = self._make_factory()
        f.create("Low score", AbundanceDomain.ENERGY, mtp_alignment=0.1)
        f.create("High score", AbundanceDomain.HEALTHCARE,
                  enabling_convergences=["a", "b", "c"], mtp_alignment=0.9)
        top = f.top_moonshots(1)
        assert len(top) == 1
        assert top[0].title == "High score"

    def test_by_domain(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        f = self._make_factory()
        f.create("A", AbundanceDomain.HEALTHCARE)
        f.create("B", AbundanceDomain.ENERGY)
        health = f.by_domain(AbundanceDomain.HEALTHCARE)
        assert len(health) == 1

    def test_stats(self):
        f = self._make_factory()
        stats = f.stats()
        assert stats["total_moonshots"] == 0


# ═══════════════════════════════════════════════════════════════
# §9  Lessons Tests
# ═══════════════════════════════════════════════════════════════


class TestLessons:
    def test_nlw_lessons_count(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import NLW_LESSONS
        assert len(NLW_LESSONS) == 5

    def test_diamandis_lessons_count(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import DIAMANDIS_LESSONS
        assert len(DIAMANDIS_LESSONS) == 7

    def test_all_lessons_combined(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ALL_LESSONS
        assert len(ALL_LESSONS) == 12

    def test_lesson_structure(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ALL_LESSONS
        for lesson in ALL_LESSONS:
            assert "lesson" in lesson
            assert "source" in lesson
            assert "insight" in lesson
            assert len(lesson["insight"]) > 0

    def test_nlw_sources(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import NLW_LESSONS
        for lesson in NLW_LESSONS:
            assert lesson["source"] == "AI Daily Brief"

    def test_diamandis_sources(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import DIAMANDIS_LESSONS
        for lesson in DIAMANDIS_LESSONS:
            assert lesson["source"] == "Peter H. Diamandis"

    def test_key_nlw_lessons(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import NLW_LESSONS
        lesson_names = {entry["lesson"] for entry in NLW_LESSONS}
        assert "velocity_matters" in lesson_names
        assert "policy_lags_technology" in lesson_names
        assert "open_source_equalizer" in lesson_names
        assert "safety_alignment_tension" in lesson_names
        assert "inference_cost_deflation" in lesson_names

    def test_key_diamandis_lessons(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import DIAMANDIS_LESSONS
        lesson_names = {entry["lesson"] for entry in DIAMANDIS_LESSONS}
        assert "six_ds_inevitable" in lesson_names
        assert "abundance_over_scarcity" in lesson_names
        assert "convergence_amplifies" in lesson_names
        assert "ten_x_over_ten_percent" in lesson_names
        assert "mtp_drives_everything" in lesson_names
        assert "longevity_escape_velocity" in lesson_names
        assert "crowd_over_expert" in lesson_names


# ═══════════════════════════════════════════════════════════════
# §10  AIDailyBriefEngine Tests
# ═══════════════════════════════════════════════════════════════


class TestAIDailyBriefEngine:
    def _make_engine(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AIDailyBriefEngine
        engine = AIDailyBriefEngine()
        engine.initialize()
        return engine

    def test_initialize(self):
        engine = self._make_engine()
        assert engine._initialized is True

    def test_ingest_briefing(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        engine = self._make_engine()
        result = engine.ingest_briefing(
            "GPT-5", "OpenAI launches GPT-5", BriefingCategory.AI_MODELS,
        )
        assert "briefing_id" in result
        assert result["category"] == "ai_models"

    def test_track_exponential(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ExponentialStage, TechnologyDomain
        engine = self._make_engine()
        result = engine.track_exponential(
            TechnologyDomain.ARTIFICIAL_INTELLIGENCE,
            ExponentialStage.DISRUPTIVE,
            "LLMs disrupting search",
        )
        assert "signal_id" in result
        assert result["impact_score"] > 0

    def test_detect_convergence(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import ConvergenceType, TechnologyDomain
        engine = self._make_engine()
        result = engine.detect_convergence(
            [TechnologyDomain.ARTIFICIAL_INTELLIGENCE, TechnologyDomain.BIOTECHNOLOGY],
            ConvergenceType.CATALYTIC,
            "AI accelerating drug discovery",
        )
        assert "convergence_id" in result
        assert result["impact_multiplier"] > 1.0

    def test_assess_abundance(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain, TechnologyDomain
        engine = self._make_engine()
        result = engine.assess_abundance(
            AbundanceDomain.ENERGY,
            current_scarcity=0.6,
            enabling_technologies=[TechnologyDomain.ARTIFICIAL_INTELLIGENCE],
        )
        assert "assessment_id" in result
        assert "abundance_score" in result

    def test_register_metatrend(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import TechnologyDomain
        engine = self._make_engine()
        result = engine.register_metatrend(
            "AI permeation", "AI in everything",
            [TechnologyDomain.ARTIFICIAL_INTELLIGENCE],
        )
        assert "trend_id" in result
        assert result["name"] == "AI permeation"

    def test_create_moonshot(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import AbundanceDomain
        engine = self._make_engine()
        result = engine.create_moonshot(
            "Cure aging", AbundanceDomain.HEALTHCARE,
            "80yr", "200yr", ["ai_biotech"], mtp_alignment=0.9,
        )
        assert "idea_id" in result
        assert result["moonshot_score"] > 0

    def test_generate_digest_empty(self):
        engine = self._make_engine()
        result = engine.generate_digest("2026-03-09")
        assert result["tempo"] == "quiet"
        assert result["briefing_count"] == 0

    def test_generate_digest_with_data(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        engine = self._make_engine()
        for i in range(5):
            engine.ingest_briefing(
                f"Brief {i}", f"Headline {i}", BriefingCategory.AI_MODELS,
            )
        result = engine.generate_digest()
        assert result["tempo"] == "accelerating"
        assert result["briefing_count"] == 5

    def test_query_lessons_all(self):
        engine = self._make_engine()
        result = engine.query_lessons()
        assert result["lessons_found"] == 12

    def test_query_lessons_by_source(self):
        engine = self._make_engine()
        result = engine.query_lessons(source="diamandis")
        assert result["lessons_found"] == 7

    def test_query_lessons_by_keyword(self):
        engine = self._make_engine()
        result = engine.query_lessons(keyword="abundance")
        assert result["lessons_found"] >= 1

    def test_score_lessons_baseline(self):
        engine = self._make_engine()
        result = engine.score_lessons()
        assert result["total_lessons"] == 12
        assert result["nlw_lessons"] == 5
        assert result["diamandis_lessons"] == 7
        assert result["avg_compliance"] == 0.5  # baseline

    def test_score_lessons_with_context(self):
        engine = self._make_engine()
        result = engine.score_lessons({"velocity_matters": 0.9, "six_ds_inevitable": 0.8})
        assert result["lesson_scores"]["velocity_matters"] == 0.9
        assert result["avg_compliance"] > 0.5

    def test_full_pipeline(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import (
            BriefingCategory,
            ExponentialStage,
            TechnologyDomain,
        )
        engine = self._make_engine()
        result = engine.full_pipeline(
            "GPT-5", "OpenAI launches GPT-5",
            BriefingCategory.AI_MODELS,
            TechnologyDomain.ARTIFICIAL_INTELLIGENCE,
            ExponentialStage.DISRUPTIVE,
            ["llm", "openai"],
        )
        assert result["pipeline"] == "complete"
        assert "briefing" in result
        assert "exponential" in result
        assert "digest" in result

    def test_full_pipeline_no_tech(self):
        from ncl_agency_runtime.fpc.ai_daily_brief import BriefingCategory
        engine = self._make_engine()
        result = engine.full_pipeline(
            "EU AI Act", "EU passes AI Act",
            BriefingCategory.AI_REGULATION,
        )
        assert result["pipeline"] == "complete"
        assert result["exponential"] == {}

    def test_operational_readiness(self):
        engine = self._make_engine()
        result = engine.operational_readiness()
        assert result["engine"] == "ai_daily_brief"
        assert result["initialized"] is True
        assert result["lessons_integrated"] == 12
        assert result["nlw_lessons"] == 5
        assert result["diamandis_lessons"] == 7


# ═══════════════════════════════════════════════════════════════
# §11  BeaconAgent Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestBeaconAgentIntegration:
    def _make_task(self):
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        return Task(id="test-beacon-001", agent_codename="ai", description="test ai daily brief")

    def test_beacon_agent_exists(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert "ai" in EXPANSION_STUBS

    def test_beacon_codename(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        agent = EXPANSION_STUBS["ai"]
        assert agent.codename == "ai"
        assert agent.callsign == "BEACON"

    def test_default_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {}})
        assert result["_callsign"] == "BEACON"
        assert "status" in result

    def test_ingest_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "ingest",
            "title": "GPT-5",
            "headline": "OpenAI releases GPT-5",
            "category": "ai_models",
        }})
        assert result["status"] == "briefing_ingested"
        assert result["_callsign"] == "BEACON"

    def test_exponential_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "exponential",
            "technology": "artificial_intelligence",
            "stage": "disruptive",
        }})
        assert result["status"] == "exponential_tracked"

    def test_converge_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "converge",
            "technologies": ["artificial_intelligence", "robotics"],
            "convergence_type": "synergistic",
        }})
        assert result["status"] == "convergence_detected"

    def test_abundance_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "abundance",
            "domain": "energy",
            "current_scarcity": 0.6,
        }})
        assert result["status"] == "abundance_assessed"

    def test_metatrend_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "metatrend",
            "name": "AI everywhere",
            "description": "AI permeates all industries",
        }})
        assert result["status"] == "metatrend_registered"

    def test_moonshot_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "moonshot",
            "title": "Cure aging",
            "domain": "healthcare",
            "mtp_alignment": 0.9,
        }})
        assert result["status"] == "moonshot_created"

    def test_digest_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "digest",
            "date": "2026-03-09",
        }})
        assert result["status"] == "digest_generated"

    def test_pipeline_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "pipeline",
            "title": "GPT-5",
            "headline": "GPT-5 launched",
            "category": "ai_models",
            "technology": "artificial_intelligence",
            "stage": "disruptive",
        }})
        assert result["status"] == "pipeline_complete"

    def test_lessons_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "lessons",
            "source": "diamandis",
        }})
        assert result["status"] == "lessons_queried"
        assert result["lessons_found"] == 7

    def test_score_lessons_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "score_lessons",
        }})
        assert result["status"] == "lessons_scored"
        assert result["total_lessons"] == 12

    def test_readiness_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        task = self._make_task()
        result = EXPANSION_STUBS["ai"].handle(task, {"payload": {
            "action": "readiness",
        }})
        assert result["status"] == "readiness_checked"
        assert result["engine"] == "ai_daily_brief"


# ═══════════════════════════════════════════════════════════════
# §12  EventType Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestBriefEventTypes:
    def test_brief_ingest(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRIEF_INGEST == "brief.ingest"

    def test_brief_analyze(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRIEF_ANALYZE == "brief.analyze"

    def test_brief_exponential(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRIEF_EXPONENTIAL == "brief.exponential"

    def test_brief_converge(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRIEF_CONVERGE == "brief.converge"

    def test_brief_digest(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRIEF_DIGEST == "brief.digest"

    def test_brief_cycle(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRIEF_CYCLE == "brief.cycle"

    def test_total_event_types(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        # 13 core + 4 Wolfram + 10 Triad + 8 Unit8200 + 5 GeoPol + 6 Brain + 6 Brief = 52
        assert len(EventType) == 71

    def test_event_creation_with_brief_type(self):
        from ncl_agency_runtime.fpc.agents.events import Event, EventType
        evt = Event(
            detail_type=EventType.BRIEF_INGEST,
            source="agent.BEACON",
            payload={"title": "Test", "category": "ai_models"},
        )
        assert evt.detail_type == EventType.BRIEF_INGEST
        assert evt.source == "agent.BEACON"


# ═══════════════════════════════════════════════════════════════
# §13  Roster Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestAIDailyBriefRosterIntegration:
    def test_beacon_in_expansion_pack(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        codenames = [a.codename for a in EXPANSION_PACK]
        assert "ai" in codenames

    def test_beacon_in_all_agents(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        codenames = [a.codename for a in ALL_AGENTS]
        assert "ai" in codenames

    def test_expansion_pack_count(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        assert len(EXPANSION_PACK) == 21

    def test_all_agents_count(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_beacon_role_details(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        agent = get_agent("ai")
        assert agent is not None
        assert agent.callsign == "BEACON"
        assert agent.name == "AI Daily Brief & Exponential Intelligence"

    def test_beacon_by_callsign(self):
        from ncl_agency_runtime.fpc.agents import get_agent_by_callsign
        agent = get_agent_by_callsign("BEACON")
        assert agent is not None
        assert agent.codename == "ai"

    def test_callsign_map(self):
        from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
        assert CALLSIGN_MAP["ai"] == "BEACON"

    def test_expansion_stubs_includes_beacon(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert "ai" in EXPANSION_STUBS
        assert len(EXPANSION_STUBS) == 21

    def test_beacon_capabilities(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        beacon = get_agent("ai")
        assert beacon is not None
        assert len(beacon.capabilities) == 8
        assert any("NLW" in c for c in beacon.capabilities)
        assert any("Diamandis" in c for c in beacon.capabilities)

    def test_beacon_in_stubs_callable(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        stub = EXPANSION_STUBS["ai"]
        task = Task("T-ai", "ai", "Test")
        result = stub.handle(task, {"payload": {}})
        assert "_callsign" in result
        assert result["_callsign"] == "BEACON"
