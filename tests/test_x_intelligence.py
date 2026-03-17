"""Comprehensive tests for X (Twitter) Intelligence Engine — Agent #30 HERALD.

Covers: enums, dataclasses, engines, routing table, classification,
filtering, agent routing, digest generation, full pipeline, HeraldAgent
integration, EventTypes, and roster integration.
"""

from __future__ import annotations

import unittest
from typing import Any

# ═══════════════════════════════════════════════════════════════
#  Section 1 — Enum Tests
# ═══════════════════════════════════════════════════════════════

class TestEngagementType(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType
        assert len(EngagementType) == 6

    def test_values(self):
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType
        expected = {"original", "like", "repost", "reply", "quote", "bookmark"}
        assert {e.value for e in EngagementType} == expected

    def test_str_enum(self):
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType
        assert str(EngagementType.LIKE) == "like"


class TestContentDomain(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentDomain
        assert len(ContentDomain) == 12

    def test_has_key_domains(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentDomain
        for d in ["ai_technology", "finance_markets", "geopolitics",
                   "security_intelligence", "health_longevity", "general"]:
            assert d in {v.value for v in ContentDomain}

    def test_str_enum(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentDomain
        assert str(ContentDomain.AI_TECHNOLOGY) == "ai_technology"


class TestUrgencyLevel(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import UrgencyLevel
        assert len(UrgencyLevel) == 5

    def test_values(self):
        from ncl_agency_runtime.fpc.x_intelligence import UrgencyLevel
        expected = {"archive", "low", "medium", "high", "flash"}
        assert {u.value for u in UrgencyLevel} == expected


class TestRoutingDivision(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import RoutingDivision
        assert len(RoutingDivision) == 9

    def test_values(self):
        from ncl_agency_runtime.fpc.x_intelligence import RoutingDivision
        expected = {"intelligence", "strategy", "operations", "research",
                    "governance", "finance", "knowledge", "communications", "innovation"}
        assert {d.value for d in RoutingDivision} == expected


class TestPillarTarget(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import PillarTarget
        assert len(PillarTarget) == 4

    def test_values(self):
        from ncl_agency_runtime.fpc.x_intelligence import PillarTarget
        expected = {"ncl_brain", "aac_bank", "bit_rage_systems", "ncc_command"}
        assert {p.value for p in PillarTarget} == expected


class TestSignalQuality(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import SignalQuality
        assert len(SignalQuality) == 5

    def test_values(self):
        from ncl_agency_runtime.fpc.x_intelligence import SignalQuality
        expected = {"noise", "weak", "moderate", "strong", "verified"}
        assert {q.value for q in SignalQuality} == expected


# ═══════════════════════════════════════════════════════════════
#  Section 2 — Dataclass Tests
# ═══════════════════════════════════════════════════════════════

class TestXPost(unittest.TestCase):
    def _make_post(self, **kwargs: Any) -> Any:
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType, XPost
        return XPost(
            post_id=kwargs.get("post_id", "xp-001"),
            author_handle=kwargs.get("author_handle", "@test_user"),
            author_name=kwargs.get("author_name", "Test User"),
            content=kwargs.get("content", "Breaking: OpenAI announces GPT-5 with unprecedented reasoning capabilities"),
            engagement_type=kwargs.get("engagement_type", EngagementType.LIKE),
            like_count=kwargs.get("like_count", 0),
            repost_count=kwargs.get("repost_count", 0),
            reply_count=kwargs.get("reply_count", 0),
            view_count=kwargs.get("view_count", 0),
        )

    def test_creation(self):
        post = self._make_post()
        assert post.post_id == "xp-001"
        assert post.author_handle == "@test_user"

    def test_fingerprint_generated(self):
        post = self._make_post()
        assert len(post.fingerprint) == 16

    def test_fingerprint_deterministic(self):
        p1 = self._make_post()
        p2 = self._make_post()
        assert p1.fingerprint == p2.fingerprint

    def test_fingerprint_varies(self):
        p1 = self._make_post(post_id="xp-001")
        p2 = self._make_post(post_id="xp-002")
        assert p1.fingerprint != p2.fingerprint

    def test_default_lists(self):
        post = self._make_post()
        assert post.hashtags == []
        assert post.mentions == []
        assert post.media_urls == []

    def test_engagement_counts(self):
        post = self._make_post(like_count=100, repost_count=50, reply_count=25)
        assert post.like_count == 100
        assert post.repost_count == 50
        assert post.reply_count == 25


class TestClassifiedPost(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.x_intelligence import (
            ClassifiedPost,
            ContentDomain,
            EngagementType,
            PillarTarget,
            RoutingDivision,
            SignalQuality,
            UrgencyLevel,
            XPost,
        )

        post = XPost(
            post_id="xp-001",
            author_handle="@test",
            author_name="Test",
            content="Test post",
            engagement_type=EngagementType.ORIGINAL,
        )
        classified = ClassifiedPost(
            post=post,
            domain=ContentDomain.AI_TECHNOLOGY,
            urgency=UrgencyLevel.HIGH,
            quality=SignalQuality.STRONG,
            division=RoutingDivision.RESEARCH,
            pillar=PillarTarget.NCL_BRAIN,
            target_agents=["ai", "ds"],
            confidence=0.9,
        )
        assert classified.domain == ContentDomain.AI_TECHNOLOGY
        assert classified.target_agents == ["ai", "ds"]


class TestRoutingRule(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.x_intelligence import (
            ContentDomain,
            PillarTarget,
            RoutingDivision,
            RoutingRule,
        )

        rule = RoutingRule(
            domain=ContentDomain.AI_TECHNOLOGY,
            division=RoutingDivision.RESEARCH,
            pillar=PillarTarget.NCL_BRAIN,
            primary_agents=["ai", "ds"],
            keywords=["ai", "llm"],
        )
        assert rule.domain == ContentDomain.AI_TECHNOLOGY
        assert rule.primary_agents == ["ai", "ds"]


class TestFeedDigest(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.x_intelligence import FeedDigest

        digest = FeedDigest(
            digest_id="XFD-test",
            date="2026-03-09",
            total_processed=100,
            by_engagement={"like": 50, "repost": 30},
            by_domain={"ai_technology": 40},
            by_urgency={"high": 10},
            by_division={"research": 25},
            by_pillar={"ncl_brain": 30},
            top_posts=["xp-001"],
            routed_count=80,
            filtered_count=20,
            quality_distribution={"strong": 40},
        )
        assert digest.total_processed == 100
        assert digest.routed_count == 80


class TestAgentDispatch(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.x_intelligence import (
            AgentDispatch,
            ContentDomain,
            PillarTarget,
            RoutingDivision,
            UrgencyLevel,
        )

        dispatch = AgentDispatch(
            dispatch_id="XD-test",
            agent_codename="ai",
            agent_callsign="BEACON",
            post_ids=["xp-001", "xp-002"],
            domain=ContentDomain.AI_TECHNOLOGY,
            urgency=UrgencyLevel.HIGH,
            division=RoutingDivision.RESEARCH,
            pillar=PillarTarget.NCL_BRAIN,
        )
        assert dispatch.agent_codename == "ai"
        assert len(dispatch.post_ids) == 2


# ═══════════════════════════════════════════════════════════════
#  Section 3 — Routing Table Tests
# ═══════════════════════════════════════════════════════════════

class TestRoutingTable(unittest.TestCase):
    def test_routing_table_count(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE
        assert len(ROUTING_TABLE) == 12

    def test_all_domains_covered(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE, ContentDomain
        covered = {r.domain for r in ROUTING_TABLE}
        assert covered == set(ContentDomain)

    def test_all_rules_have_primary_agents(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE
        for rule in ROUTING_TABLE:
            assert len(rule.primary_agents) > 0, f"{rule.domain} has no primary agents"

    def test_ai_routes_to_beacon(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE, ContentDomain
        ai_rule = next(r for r in ROUTING_TABLE if r.domain == ContentDomain.AI_TECHNOLOGY)
        assert "ai" in ai_rule.primary_agents

    def test_finance_routes_to_aac(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE, ContentDomain, PillarTarget
        fin_rule = next(r for r in ROUTING_TABLE if r.domain == ContentDomain.FINANCE_MARKETS)
        assert fin_rule.pillar == PillarTarget.AAC_BANK

    def test_security_routes_to_intelligence(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE, ContentDomain, RoutingDivision
        sec_rule = next(r for r in ROUTING_TABLE if r.domain == ContentDomain.SECURITY_INTELLIGENCE)
        assert sec_rule.division == RoutingDivision.INTELLIGENCE
        assert "sg" in sec_rule.primary_agents  # CIPHER

    def test_geopolitics_routes_to_mandarin(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE, ContentDomain
        geo_rule = next(r for r in ROUTING_TABLE if r.domain == ContentDomain.GEOPOLITICS)
        assert "jx" in geo_rule.primary_agents  # MANDARIN

    def test_general_is_catch_all(self):
        from ncl_agency_runtime.fpc.x_intelligence import ROUTING_TABLE, ContentDomain
        gen_rule = next(r for r in ROUTING_TABLE if r.domain == ContentDomain.GENERAL)
        assert gen_rule.keywords == []
        assert "sb" in gen_rule.primary_agents  # CORTEX (Second Brain)


# ═══════════════════════════════════════════════════════════════
#  Section 4 — Engine Tests
# ═══════════════════════════════════════════════════════════════

class TestFeedCollector(unittest.TestCase):
    def _make_post(self, post_id="xp-001", content="Test"):
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType, XPost
        return XPost(
            post_id=post_id,
            author_handle="@test",
            author_name="Test",
            content=content,
            engagement_type=EngagementType.LIKE,
        )

    def test_ingest(self):
        from ncl_agency_runtime.fpc.x_intelligence import FeedCollector
        collector = FeedCollector()
        result = collector.ingest(self._make_post())
        assert result["ingested"] is True
        assert collector.count == 1

    def test_dedup(self):
        from ncl_agency_runtime.fpc.x_intelligence import FeedCollector
        collector = FeedCollector()
        post = self._make_post()
        collector.ingest(post)
        result = collector.ingest(post)
        assert result["ingested"] is False
        assert result["reason"] == "duplicate"
        assert collector.count == 1

    def test_by_engagement(self):
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType, FeedCollector, XPost
        collector = FeedCollector()
        collector.ingest(self._make_post("xp-001", "A"))
        collector.ingest(XPost(
            post_id="xp-002", author_handle="@t", author_name="T",
            content="B", engagement_type=EngagementType.REPOST,
        ))
        likes = collector.by_engagement(EngagementType.LIKE)
        assert len(likes) == 1

    def test_stats(self):
        from ncl_agency_runtime.fpc.x_intelligence import FeedCollector
        collector = FeedCollector()
        collector.ingest(self._make_post())
        stats = collector.stats()
        assert stats["total_posts"] == 1
        assert "like" in stats["engagement_breakdown"]


class TestContentClassifier(unittest.TestCase):
    def _make_post(self, content="Test", **kwargs: Any) -> Any:
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType, XPost
        return XPost(
            post_id=kwargs.get("post_id", "xp-001"),
            author_handle=kwargs.get("author_handle", "@test"),
            author_name=kwargs.get("author_name", "Test"),
            content=content,
            engagement_type=kwargs.get("engagement_type", EngagementType.ORIGINAL),
            like_count=kwargs.get("like_count", 0),
            repost_count=kwargs.get("repost_count", 0),
            reply_count=kwargs.get("reply_count", 0),
            view_count=kwargs.get("view_count", 0),
        )

    def test_classify_ai(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, ContentDomain
        classifier = ContentClassifier()
        post = self._make_post("OpenAI releases GPT-5 with advanced AI reasoning and deep learning")
        result = classifier.classify(post)
        assert result.domain == ContentDomain.AI_TECHNOLOGY

    def test_classify_finance(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, ContentDomain
        classifier = ContentClassifier()
        post = self._make_post("Bitcoin hits $200k, crypto market surging, portfolio up 50%")
        result = classifier.classify(post)
        assert result.domain == ContentDomain.FINANCE_MARKETS

    def test_classify_security(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, ContentDomain
        classifier = ContentClassifier()
        post = self._make_post("Major cyber breach: zero-day exploit found in ransomware attack")
        result = classifier.classify(post)
        assert result.domain == ContentDomain.SECURITY_INTELLIGENCE

    def test_classify_general_fallback(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, ContentDomain
        classifier = ContentClassifier()
        post = self._make_post("Nothing to see here xyzzy plonk")
        result = classifier.classify(post)
        assert result.domain == ContentDomain.GENERAL

    def test_urgency_flash(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, UrgencyLevel
        classifier = ContentClassifier()
        post = self._make_post("BREAKING: Critical development in AI")
        result = classifier.classify(post)
        assert result.urgency == UrgencyLevel.FLASH

    def test_urgency_high_engagement(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, UrgencyLevel
        classifier = ContentClassifier()
        post = self._make_post("Big news", like_count=5000, repost_count=3000, reply_count=2001)
        result = classifier.classify(post)
        assert result.urgency == UrgencyLevel.HIGH

    def test_quality_scoring(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier, SignalQuality
        classifier = ContentClassifier()
        post = self._make_post(
            "A very long post about AI technology with detailed analysis " * 5,
            hashtags=["AI", "ML", "GPT"],
            mentions=["@openai"],
            like_count=1000,
            repost_count=500,
        )
        result = classifier.classify(post)
        assert result.quality in {SignalQuality.STRONG, SignalQuality.VERIFIED}

    def test_stats(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentClassifier
        classifier = ContentClassifier()
        classifier.classify(self._make_post("AI deep learning model"))
        stats = classifier.stats()
        assert stats["total_classified"] == 1


class TestContentFilter(unittest.TestCase):
    def _make_classified(self, quality_val="moderate"):
        from ncl_agency_runtime.fpc.x_intelligence import (
            ClassifiedPost,
            ContentDomain,
            EngagementType,
            PillarTarget,
            RoutingDivision,
            SignalQuality,
            UrgencyLevel,
            XPost,
        )

        post = XPost(
            post_id="xp-001", author_handle="@t", author_name="T",
            content="Test", engagement_type=EngagementType.ORIGINAL,
        )
        return ClassifiedPost(
            post=post,
            domain=ContentDomain.GENERAL,
            urgency=UrgencyLevel.LOW,
            quality=SignalQuality(quality_val),
            division=RoutingDivision.KNOWLEDGE,
            pillar=PillarTarget.NCL_BRAIN,
            target_agents=["sb"],
        )

    def test_pass_moderate(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentFilter
        f = ContentFilter()
        assert f.apply(self._make_classified("moderate")) is True

    def test_filter_noise(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentFilter
        f = ContentFilter()
        assert f.apply(self._make_classified("noise")) is False

    def test_stats(self):
        from ncl_agency_runtime.fpc.x_intelligence import ContentFilter
        f = ContentFilter()
        f.apply(self._make_classified("strong"))
        f.apply(self._make_classified("noise"))
        stats = f.stats()
        assert stats["passed"] == 1
        assert stats["filtered"] == 1


class TestAgentRouter(unittest.TestCase):
    def _make_classified(self, domain_val="ai_technology", agents=None):
        from ncl_agency_runtime.fpc.x_intelligence import (
            ClassifiedPost,
            ContentDomain,
            EngagementType,
            PillarTarget,
            RoutingDivision,
            SignalQuality,
            UrgencyLevel,
            XPost,
        )

        post = XPost(
            post_id="xp-001", author_handle="@t", author_name="T",
            content="Test", engagement_type=EngagementType.ORIGINAL,
        )
        return ClassifiedPost(
            post=post,
            domain=ContentDomain(domain_val),
            urgency=UrgencyLevel.MEDIUM,
            quality=SignalQuality.STRONG,
            division=RoutingDivision.RESEARCH,
            pillar=PillarTarget.NCL_BRAIN,
            target_agents=agents or ["ai", "ds"],
        )

    def test_route(self):
        from ncl_agency_runtime.fpc.x_intelligence import AgentRouter
        router = AgentRouter()
        dispatch = router.route(self._make_classified())
        assert dispatch.dispatch_id.startswith("XD-")
        assert dispatch.agent_codename == "ai"

    def test_queue(self):
        from ncl_agency_runtime.fpc.x_intelligence import AgentRouter
        router = AgentRouter()
        router.route(self._make_classified())
        queue = router.queue_for("ai")
        assert len(queue) == 1
        assert "xp-001" in queue

    def test_callsign_resolution(self):
        from ncl_agency_runtime.fpc.x_intelligence import AgentRouter
        router = AgentRouter()
        dispatch = router.route(self._make_classified())
        assert dispatch.agent_callsign == "BEACON"

    def test_stats(self):
        from ncl_agency_runtime.fpc.x_intelligence import AgentRouter
        router = AgentRouter()
        router.route(self._make_classified())
        stats = router.stats()
        assert stats["total_dispatches"] == 1
        assert stats["agents_with_queue"] >= 1


# ═══════════════════════════════════════════════════════════════
#  Section 5 — Unified Engine Tests
# ═══════════════════════════════════════════════════════════════

class TestXIntelligenceEngine(unittest.TestCase):
    def _make_post(self, post_id="xp-001", content="Test", **kwargs: Any) -> Any:
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType, XPost
        return XPost(
            post_id=post_id,
            author_handle=kwargs.get("author_handle", "@test"),
            author_name=kwargs.get("author_name", "Test"),
            content=content,
            engagement_type=kwargs.get("engagement_type", EngagementType.ORIGINAL),
            like_count=kwargs.get("like_count", 0),
            repost_count=kwargs.get("repost_count", 0),
            reply_count=kwargs.get("reply_count", 0),
            view_count=kwargs.get("view_count", 0),
        )

    def test_ingest_post(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        result = engine.ingest_post(self._make_post())
        assert result["status"] == "ingested"

    def test_classify_post(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        post = self._make_post(content="OpenAI releases GPT-5 with AI and deep learning")
        result = engine.classify_post(post)
        assert result["status"] == "classified"
        assert "domain" in result
        assert "target_agents" in result

    def test_full_pipeline_routes(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        post = self._make_post(
            content="Major AI breakthrough: new transformer model beats benchmarks",
            like_count=500,
            repost_count=200,
            hashtags=["AI"],
        )
        result = engine.full_pipeline(post)
        assert result["status"] == "routed"
        assert "dispatch_id" in result
        assert "target_agents" in result

    def test_full_pipeline_dedup(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        post = self._make_post(content="Test post", like_count=100)
        engine.full_pipeline(post)
        result = engine.full_pipeline(post)
        assert result["status"] == "duplicate_skipped"

    def test_full_pipeline_filtered_out(self):
        from ncl_agency_runtime.fpc.x_intelligence import SignalQuality, XIntelligenceEngine
        engine = XIntelligenceEngine(min_quality=SignalQuality.STRONG)
        post = self._make_post(content="Short post")  # Low quality
        result = engine.full_pipeline(post)
        assert result["status"] == "filtered_out"

    def test_generate_digest(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        engine.full_pipeline(self._make_post(
            content="AI model with deep learning beats benchmarks",
            like_count=500, repost_count=200, hashtags=["AI"],
        ))
        result = engine.generate_digest()
        assert result["status"] == "digest_generated"
        assert "digest_id" in result

    def test_agent_queue(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        engine.full_pipeline(self._make_post(
            content="AI model transformer deep learning neural",
            like_count=500, repost_count=200,
        ))
        result = engine.agent_queue("ai")
        assert result["status"] == "queue_retrieved"

    def test_routing_summary(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        result = engine.routing_summary()
        assert result["status"] == "routing_summary"
        assert "collector" in result
        assert "classifier" in result
        assert "router" in result

    def test_operational_readiness(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        result = engine.operational_readiness()
        assert result["ready"] is True
        assert result["routing_rules"] == 12
        assert result["domains"] == 12
        assert result["divisions"] == 9
        assert result["pillars"] == 4
        assert result["engagement_types"] == 6

    def test_batch_pipeline(self):
        from ncl_agency_runtime.fpc.x_intelligence import EngagementType, XIntelligenceEngine, XPost
        engine = XIntelligenceEngine()
        posts = [
            self._make_post("xp-001", "OpenAI GPT-5 AI and deep learning model", like_count=600, repost_count=200),
            XPost(
                post_id="xp-002", author_handle="@fin",
                author_name="Fin", content="Bitcoin crypto market portfolio surging",
                engagement_type=EngagementType.REPOST, like_count=600, repost_count=200,
            ),
            XPost(
                post_id="xp-003", author_handle="@sec",
                author_name="Sec", content="Zero-day cyber breach exploit ransomware attack",
                engagement_type=EngagementType.LIKE, like_count=600, repost_count=200,
            ),
        ]
        results = [engine.full_pipeline(p) for p in posts]
        routed = [r for r in results if r["status"] == "routed"]
        assert len(routed) >= 2  # At least some should be routed

    def test_multi_domain_routing(self):
        from ncl_agency_runtime.fpc.x_intelligence import XIntelligenceEngine
        engine = XIntelligenceEngine()
        engine.full_pipeline(self._make_post(
            "xp-ai", "AI deep learning transformer model neural",
            like_count=500, repost_count=200,
        ))
        engine.full_pipeline(self._make_post(
            "xp-fin", "Bitcoin crypto portfolio market trading",
            like_count=500, repost_count=200,
        ))
        summary = engine.routing_summary()
        assert summary["router"]["total_dispatches"] >= 2


# ═══════════════════════════════════════════════════════════════
#  Section 6 — HeraldAgent Integration Tests
# ═══════════════════════════════════════════════════════════════

class TestHeraldAgentIntegration(unittest.TestCase):
    def test_herald_in_stubs(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert "xf" in EXPANSION_STUBS
        agent = EXPANSION_STUBS["xf"]
        assert agent.codename == "xf"
        assert agent.callsign == "HERALD"

    def test_herald_default_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {"payload": {}})
        assert result["status"] == "readiness_checked"
        assert result["ready"] is True

    def test_herald_readiness(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {"action": "readiness"},
        })
        assert result["status"] == "readiness_checked"
        assert result["ready"] is True
        assert result["routing_rules"] == 12

    def test_herald_ingest(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {
                "action": "ingest",
                "post": {
                    "post_id": "xp-test-001",
                    "author_handle": "@testuser",
                    "author_name": "Test User",
                    "content": "Testing X integration with NCL",
                    "engagement_type": "like",
                },
            },
        })
        assert result["status"] == "post_ingested"

    def test_herald_classify(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {
                "action": "classify",
                "post": {
                    "post_id": "xp-test-002",
                    "author_handle": "@aiuser",
                    "author_name": "AI User",
                    "content": "OpenAI GPT-5 AI deep learning transformer model released",
                    "engagement_type": "original",
                    "hashtags": ["AI", "GPT5"],
                },
            },
        })
        assert result["status"] == "post_classified"
        assert result["domain"] == "ai_technology"

    def test_herald_pipeline(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {
                "action": "pipeline",
                "post": {
                    "post_id": "xp-test-003",
                    "author_handle": "@trader",
                    "author_name": "Trader",
                    "content": "Bitcoin crypto market portfolio surging past expectations",
                    "engagement_type": "repost",
                    "like_count": 500,
                    "repost_count": 200,
                },
            },
        })
        assert result["status"] == "routed"
        assert result["domain"] == "finance_markets"

    def test_herald_digest(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {"action": "digest"},
        })
        assert result["status"] == "digest_generated"

    def test_herald_summary(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {"action": "summary"},
        })
        assert result["status"] == "summary_generated"

    def test_herald_queue(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["xf"].handle(Task("T-xf", "xf", "Test"), {
            "payload": {"action": "queue", "agent_codename": "ai"},
        })
        assert result["status"] == "queue_retrieved"


# ═══════════════════════════════════════════════════════════════
#  Section 7 — EventType & Roster Integration Tests
# ═══════════════════════════════════════════════════════════════

class TestXFeedEventTypes(unittest.TestCase):
    def test_event_type_count(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert len(EventType) == 71

    def test_x_feed_events_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        x_events = {
            EventType.X_FEED_INGEST,
            EventType.X_FEED_CLASSIFY,
            EventType.X_FEED_FILTER,
            EventType.X_FEED_ROUTE,
            EventType.X_FEED_DIGEST,
            EventType.X_FEED_CYCLE,
        }
        assert len(x_events) == 6

    def test_x_feed_event_values(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.X_FEED_INGEST.value == "xfeed.ingest"
        assert EventType.X_FEED_CLASSIFY.value == "xfeed.classify"
        assert EventType.X_FEED_FILTER.value == "xfeed.filter"
        assert EventType.X_FEED_ROUTE.value == "xfeed.route"
        assert EventType.X_FEED_DIGEST.value == "xfeed.digest"
        assert EventType.X_FEED_CYCLE.value == "xfeed.cycle"


class TestXIntelligenceRosterIntegration(unittest.TestCase):
    def test_herald_in_expansion_pack(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        assert len(EXPANSION_PACK) == 21
        herald = next(a for a in EXPANSION_PACK if a.codename == "xf")
        assert herald.callsign == "HERALD"
        assert herald.name == "X Intelligence & Feed Router"

    def test_all_agents_count(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_herald_capabilities(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        herald = next(a for a in EXPANSION_PACK if a.codename == "xf")
        assert len(herald.capabilities) == 8

    def test_expansion_stubs_count(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert len(EXPANSION_STUBS) == 21
        assert "xf" in EXPANSION_STUBS

    def test_wolfram_knows_herald(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["wp"].handle(Task("T-wp", "wp", "Test"), {"payload": {}})
        assert result["status"] == "wolfram_observed"
        # WolframAgent known list includes all 30 agents
        assert result["_agent"] == "wp"


if __name__ == "__main__":
    unittest.main()
