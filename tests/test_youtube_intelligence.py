"""Comprehensive tests for YouTube Intelligence Engine — Agent #31 CATALYST.

Covers: enums, dataclasses, tool extraction, classification, impact scoring,
filtering, routing, trend tracking, digest generation, full pipeline,
CatalystAgent integration, EventTypes, roster integration, and
AI Upload strategic intelligence pipeline.
"""

from __future__ import annotations

import unittest
from typing import Any

# ═══════════════════════════════════════════════════════════════
#  Section 1 — Enum Tests
# ═══════════════════════════════════════════════════════════════


class TestVideoSource(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoSource
        assert len(VideoSource) == 6

    def test_values(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoSource
        expected = {"there_is_an_ai_for_that", "ai_upload", "subscriber_feed", "recommended", "playlist", "search"}
        assert {v.value for v in VideoSource} == expected

    def test_str_enum(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoSource
        assert str(VideoSource.TIAIFT) == "there_is_an_ai_for_that"


class TestToolCategory(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory
        assert len(ToolCategory) == 15

    def test_has_key_categories(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory
        assert ToolCategory.TEXT_GENERATION == "text_generation"
        assert ToolCategory.IMAGE_GENERATION == "image_generation"
        assert ToolCategory.VIDEO_GENERATION == "video_generation"
        assert ToolCategory.CODE_ASSISTANT == "code_assistant"
        assert ToolCategory.AGENT_FRAMEWORK == "agent_framework"
        assert ToolCategory.OPEN_SOURCE == "open_source"
        assert ToolCategory.GENERAL == "general"


class TestImpactLevel(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ImpactLevel
        assert len(ImpactLevel) == 5

    def test_values(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ImpactLevel
        expected = {"paradigm_shift", "high", "moderate", "low", "noise"}
        assert {v.value for v in ImpactLevel} == expected


class TestRoutingTarget(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import RoutingTarget
        assert len(RoutingTarget) == 8

    def test_values(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import RoutingTarget
        expected = {"research", "innovation", "operations", "intelligence",
                    "knowledge", "communications", "finance", "strategy"}
        assert {v.value for v in RoutingTarget} == expected


class TestPillarMapping(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import PillarMapping
        assert len(PillarMapping) == 4

    def test_values(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import PillarMapping
        expected = {"ncl_brain", "aac_bank", "bit_rage_systems", "ncc_command"}
        assert {v.value for v in PillarMapping} == expected


# ═══════════════════════════════════════════════════════════════
#  Section 2 — Dataclass Tests
# ═══════════════════════════════════════════════════════════════


class TestVideoEntry(unittest.TestCase):
    def _make_video(self, **kwargs: Any) -> Any:
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
        return VideoEntry(
            video_id=kwargs.get("video_id", "vid-001"),
            title=kwargs.get("title", "Best AI Tools 2026 - ChatGPT vs Claude vs Gemini"),
            channel_name=kwargs.get("channel_name", "There Is An AI For That"),
            description=kwargs.get("description", "Comparing top AI tools"),
            source=kwargs.get("source", VideoSource.TIAIFT),
            view_count=kwargs.get("view_count", 0),
            like_count=kwargs.get("like_count", 0),
            comment_count=kwargs.get("comment_count", 0),
            tags=kwargs.get("tags", []),
            transcript_snippet=kwargs.get("transcript_snippet", ""),
        )

    def test_creation(self):
        video = self._make_video()
        assert video.video_id == "vid-001"
        assert video.channel_name == "There Is An AI For That"

    def test_fingerprint_generated(self):
        video = self._make_video()
        assert len(video.fingerprint) == 16

    def test_fingerprint_deterministic(self):
        v1 = self._make_video()
        v2 = self._make_video()
        assert v1.fingerprint == v2.fingerprint

    def test_fingerprint_varies(self):
        v1 = self._make_video(video_id="vid-001")
        v2 = self._make_video(video_id="vid-002")
        assert v1.fingerprint != v2.fingerprint

    def test_default_lists(self):
        video = self._make_video()
        assert video.tags == []

    def test_engagement_counts(self):
        video = self._make_video(view_count=100000, like_count=5000, comment_count=200)
        assert video.view_count == 100000
        assert video.like_count == 5000
        assert video.comment_count == 200


class TestToolMention(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory, ToolMention
        m = ToolMention(tool_name="chatgpt", category=ToolCategory.TEXT_GENERATION, is_primary=True)
        assert m.tool_name == "chatgpt"
        assert m.is_primary is True

    def test_default_capabilities(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory, ToolMention
        m = ToolMention(tool_name="sora", category=ToolCategory.VIDEO_GENERATION, is_primary=False)
        assert m.capabilities == []


class TestCategoryRule(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            CategoryRule,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
        )
        r = CategoryRule(
            category=ToolCategory.TEXT_GENERATION,
            division=RoutingTarget.RESEARCH,
            pillar=PillarMapping.NCL_BRAIN,
            primary_agents=["ai", "sb"],
            keywords=["chatgpt", "llm"],
        )
        assert r.category == ToolCategory.TEXT_GENERATION
        assert "ai" in r.primary_agents


class TestVideoDigest(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoDigest
        d = VideoDigest(
            total_ingested=10,
            total_classified=3,
            total_routed=8,
            duplicates_skipped=2,
            category_breakdown={"text_generation": 5},
            impact_breakdown={"passed": 8, "filtered": 2},
            top_tools=["chatgpt", "claude"],
            generated_at=1000.0,
        )
        assert d.total_ingested == 10
        assert d.top_tools == ["chatgpt", "claude"]


class TestAgentDispatch(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import AgentDispatch, PillarMapping, RoutingTarget
        d = AgentDispatch(
            dispatch_id="yd-abc12345-ai",
            agent_codename="ai",
            agent_callsign="BEACON",
            division=RoutingTarget.RESEARCH,
            pillar=PillarMapping.NCL_BRAIN,
            video_ids=["vid-001"],
        )
        assert d.agent_codename == "ai"
        assert d.video_ids == ["vid-001"]


# ═══════════════════════════════════════════════════════════════
#  Section 3 — Routing Table Tests
# ═══════════════════════════════════════════════════════════════


class TestCategoryRouting(unittest.TestCase):
    def test_all_categories_covered(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import CATEGORY_ROUTING, ToolCategory
        covered = {r.category for r in CATEGORY_ROUTING}
        assert covered == set(ToolCategory)

    def test_routing_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import CATEGORY_ROUTING
        assert len(CATEGORY_ROUTING) == 15

    def test_text_gen_routes_to_research(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import CATEGORY_ROUTING, RoutingTarget, ToolCategory
        rule = next(r for r in CATEGORY_ROUTING if r.category == ToolCategory.TEXT_GENERATION)
        assert rule.division == RoutingTarget.RESEARCH
        assert "ai" in rule.primary_agents

    def test_code_assistant_routes_to_operations(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import CATEGORY_ROUTING, RoutingTarget, ToolCategory
        rule = next(r for r in CATEGORY_ROUTING if r.category == ToolCategory.CODE_ASSISTANT)
        assert rule.division == RoutingTarget.OPERATIONS

    def test_agent_framework_routes_to_strategy(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import CATEGORY_ROUTING, PillarMapping, ToolCategory
        rule = next(r for r in CATEGORY_ROUTING if r.category == ToolCategory.AGENT_FRAMEWORK)
        assert rule.pillar == PillarMapping.NCC_COMMAND
        assert "ai" in rule.primary_agents

    def test_general_is_catch_all(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import CATEGORY_ROUTING, ToolCategory
        rule = next(r for r in CATEGORY_ROUTING if r.category == ToolCategory.GENERAL)
        assert rule.keywords == []


# ═══════════════════════════════════════════════════════════════
#  Section 4 — Engine Component Tests
# ═══════════════════════════════════════════════════════════════


class TestVideoCollector(unittest.TestCase):
    def _make_video(self, video_id: str = "vid-001", title: str = "Test") -> Any:
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
        return VideoEntry(
            video_id=video_id,
            title=title,
            channel_name="TIAIFT",
            description="Test description",
            source=VideoSource.TIAIFT,
        )

    def test_ingest(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoCollector
        collector = VideoCollector()
        result = collector.ingest(self._make_video())
        assert result["ingested"] is True
        assert collector.count == 1

    def test_dedup(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoCollector
        collector = VideoCollector()
        v = self._make_video()
        collector.ingest(v)
        result = collector.ingest(v)
        assert result["ingested"] is False
        assert collector.count == 1
        assert collector.duplicate_count == 1

    def test_multiple_unique(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoCollector
        collector = VideoCollector()
        for i in range(5):
            collector.ingest(self._make_video(video_id=f"vid-{i}"))
        assert collector.count == 5


class TestToolExtractor(unittest.TestCase):
    def _make_video(self, title: str, description: str = "", tags: list[str] | None = None) -> Any:
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
        return VideoEntry(
            video_id="vid-test",
            title=title,
            channel_name="TIAIFT",
            description=description,
            source=VideoSource.TIAIFT,
            tags=tags or [],
        )

    def test_extract_from_title(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor
        extractor = ToolExtractor()
        video = self._make_video("ChatGPT vs Claude: Which is Better?")
        tools = extractor.extract(video)
        names = {t.tool_name for t in tools}
        assert "chatgpt" in names
        assert "claude" in names

    def test_primary_detection(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor
        extractor = ToolExtractor()
        video = self._make_video("Midjourney Tutorial", description="Also mentions stable diffusion")
        tools = extractor.extract(video)
        mj = next(t for t in tools if t.tool_name == "midjourney")
        sd = next(t for t in tools if t.tool_name == "stable diffusion")
        assert mj.is_primary is True
        assert sd.is_primary is False

    def test_extract_from_tags(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor
        extractor = ToolExtractor()
        video = self._make_video("AI Tools Review", tags=["sora", "pika"])
        tools = extractor.extract(video)
        names = {t.tool_name for t in tools}
        assert "sora" in names
        assert "pika" in names

    def test_no_tools_found(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor
        extractor = ToolExtractor()
        video = self._make_video("How to cook pasta")
        tools = extractor.extract(video)
        assert tools == []

    def test_known_tools_count(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor
        assert len(ToolExtractor.KNOWN_TOOLS) >= 25


class TestVideoClassifier(unittest.TestCase):
    def _make_video(self, title: str, description: str = "", **kwargs: Any) -> Any:
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
        return VideoEntry(
            video_id=kwargs.get("video_id", "vid-test"),
            title=title,
            channel_name="TIAIFT",
            description=description,
            source=VideoSource.TIAIFT,
            view_count=kwargs.get("view_count", 0),
            like_count=kwargs.get("like_count", 0),
            comment_count=kwargs.get("comment_count", 0),
            tags=kwargs.get("tags", []),
        )

    def test_classify_text_gen(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory, ToolExtractor, VideoClassifier
        classifier = VideoClassifier()
        extractor = ToolExtractor()
        video = self._make_video("ChatGPT GPT-4 language model review", "A deep dive into ChatGPT llm")
        tools = extractor.extract(video)
        result = classifier.classify(video, tools)
        assert result.category == ToolCategory.TEXT_GENERATION

    def test_classify_image_gen(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory, ToolExtractor, VideoClassifier
        classifier = VideoClassifier()
        extractor = ToolExtractor()
        video = self._make_video("Midjourney V7 - Best AI Art Generator", "midjourney text to image")
        tools = extractor.extract(video)
        result = classifier.classify(video, tools)
        assert result.category == ToolCategory.IMAGE_GENERATION

    def test_classify_code_assistant(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolCategory, ToolExtractor, VideoClassifier
        classifier = VideoClassifier()
        extractor = ToolExtractor()
        video = self._make_video("Cursor vs Copilot - Best AI Coding Tool", "cursor code assistant comparison")
        tools = extractor.extract(video)
        result = classifier.classify(video, tools)
        assert result.category == ToolCategory.CODE_ASSISTANT

    def test_impact_high_engagement(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ImpactLevel, ToolExtractor, VideoClassifier
        classifier = VideoClassifier()
        extractor = ToolExtractor()
        video = self._make_video(
            "Revolutionary GPT-5 Just Launched", "First ever gpt-5",
            view_count=600_000, like_count=15_000, comment_count=600,
        )
        tools = extractor.extract(video)
        result = classifier.classify(video, tools)
        assert result.impact in (ImpactLevel.HIGH, ImpactLevel.PARADIGM_SHIFT)

    def test_impact_noise(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ImpactLevel, VideoClassifier
        classifier = VideoClassifier()
        video = self._make_video("Random video", view_count=0, like_count=0)
        result = classifier.classify(video, [])
        assert result.impact == ImpactLevel.NOISE

    def test_confidence_ranges(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor, VideoClassifier
        classifier = VideoClassifier()
        extractor = ToolExtractor()
        video = self._make_video("ChatGPT GPT-4 language model llm", "chatgpt gpt prompt")
        tools = extractor.extract(video)
        result = classifier.classify(video, tools)
        assert 0.0 <= result.confidence <= 1.0

    def test_category_counts(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ToolExtractor, VideoClassifier
        classifier = VideoClassifier()
        extractor = ToolExtractor()
        v1 = self._make_video("ChatGPT Review", video_id="v1")
        v2 = self._make_video("Midjourney Art", video_id="v2")
        classifier.classify(v1, extractor.extract(v1))
        classifier.classify(v2, extractor.extract(v2))
        counts = classifier.category_counts()
        assert len(counts) >= 2


class TestImpactFilter(unittest.TestCase):
    def test_pass_above_threshold(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            ClassifiedVideo,
            ImpactFilter,
            ImpactLevel,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
            VideoEntry,
            VideoSource,
        )
        filt = ImpactFilter(ImpactLevel.LOW)
        video = VideoEntry(
            video_id="v1", title="Test", channel_name="TIAIFT",
            description="", source=VideoSource.TIAIFT,
        )
        classified = ClassifiedVideo(
            video=video, category=ToolCategory.TEXT_GENERATION,
            impact=ImpactLevel.MODERATE, tools=[], confidence=0.7,
            routing_target=RoutingTarget.RESEARCH, pillar=PillarMapping.NCL_BRAIN,
            target_agents=["ai"],
        )
        assert filt.apply(classified) is True
        assert filt.passed_count == 1

    def test_filter_below_threshold(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            ClassifiedVideo,
            ImpactFilter,
            ImpactLevel,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
            VideoEntry,
            VideoSource,
        )
        filt = ImpactFilter(ImpactLevel.MODERATE)
        video = VideoEntry(
            video_id="v1", title="Test", channel_name="TIAIFT",
            description="", source=VideoSource.TIAIFT,
        )
        classified = ClassifiedVideo(
            video=video, category=ToolCategory.GENERAL,
            impact=ImpactLevel.NOISE, tools=[], confidence=0.3,
            routing_target=RoutingTarget.KNOWLEDGE, pillar=PillarMapping.NCL_BRAIN,
            target_agents=["sb"],
        )
        assert filt.apply(classified) is False
        assert filt.filtered_count == 1

    def test_stats(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ImpactFilter, ImpactLevel
        filt = ImpactFilter(ImpactLevel.LOW)
        stats = filt.stats()
        assert stats["min_impact"] == "low"


class TestVideoRouter(unittest.TestCase):
    def test_route(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            ClassifiedVideo,
            ImpactLevel,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
            VideoEntry,
            VideoRouter,
            VideoSource,
        )
        router = VideoRouter()
        video = VideoEntry(
            video_id="v1", title="Test", channel_name="TIAIFT",
            description="", source=VideoSource.TIAIFT,
        )
        classified = ClassifiedVideo(
            video=video, category=ToolCategory.TEXT_GENERATION,
            impact=ImpactLevel.HIGH, tools=[], confidence=0.8,
            routing_target=RoutingTarget.RESEARCH, pillar=PillarMapping.NCL_BRAIN,
            target_agents=["ai", "sb"],
        )
        dispatch = router.route(classified)
        assert dispatch.agent_codename == "ai"
        assert dispatch.agent_callsign == "BEACON"
        assert "v1" in dispatch.video_ids

    def test_agent_queue(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            ClassifiedVideo,
            ImpactLevel,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
            VideoEntry,
            VideoRouter,
            VideoSource,
        )
        router = VideoRouter()
        for i in range(3):
            video = VideoEntry(
                video_id=f"v{i}", title="Test", channel_name="TIAIFT",
                description="", source=VideoSource.TIAIFT,
            )
            classified = ClassifiedVideo(
                video=video, category=ToolCategory.TEXT_GENERATION,
                impact=ImpactLevel.HIGH, tools=[], confidence=0.8,
                routing_target=RoutingTarget.RESEARCH, pillar=PillarMapping.NCL_BRAIN,
                target_agents=["ai"],
            )
            router.route(classified)
        q = router.agent_queue("ai")
        assert q["queued_videos"] == 3

    def test_routing_summary(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoRouter
        router = VideoRouter()
        summary = router.routing_summary()
        assert summary["total_dispatches"] == 0

    def test_callsign_map_has_catalyst(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoRouter
        assert VideoRouter.CALLSIGN_MAP["yt"] == "CATALYST"


class TestTrendTracker(unittest.TestCase):
    def test_track_and_trending(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            ClassifiedVideo,
            ImpactLevel,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
            ToolMention,
            TrendTracker,
            VideoEntry,
            VideoSource,
        )
        tracker = TrendTracker()
        video = VideoEntry(
            video_id="v1", title="Test", channel_name="TIAIFT",
            description="", source=VideoSource.TIAIFT,
        )
        tools = [ToolMention(tool_name="chatgpt", category=ToolCategory.TEXT_GENERATION, is_primary=True)]
        classified = ClassifiedVideo(
            video=video, category=ToolCategory.TEXT_GENERATION,
            impact=ImpactLevel.HIGH, tools=tools, confidence=0.8,
            routing_target=RoutingTarget.RESEARCH, pillar=PillarMapping.NCL_BRAIN,
            target_agents=["ai"],
        )
        tracker.track(classified)
        trending = tracker.trending_tools(5)
        assert ("chatgpt", 1) in trending

    def test_high_impact_recorded(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            ClassifiedVideo,
            ImpactLevel,
            PillarMapping,
            RoutingTarget,
            ToolCategory,
            TrendTracker,
            VideoEntry,
            VideoSource,
        )
        tracker = TrendTracker()
        video = VideoEntry(
            video_id="v1", title="GPT-5 Launch", channel_name="TIAIFT",
            description="", source=VideoSource.TIAIFT,
        )
        classified = ClassifiedVideo(
            video=video, category=ToolCategory.TEXT_GENERATION,
            impact=ImpactLevel.PARADIGM_SHIFT, tools=[], confidence=0.9,
            routing_target=RoutingTarget.RESEARCH, pillar=PillarMapping.NCL_BRAIN,
            target_agents=["ai"],
        )
        tracker.track(classified)
        launches = tracker.recent_launches()
        assert len(launches) == 1
        assert launches[0]["impact"] == "paradigm_shift"

    def test_trend_report(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import TrendTracker
        tracker = TrendTracker()
        report = tracker.trend_report()
        assert report["total_tools_tracked"] == 0
        assert report["recent_high_impact"] == 0


# ═══════════════════════════════════════════════════════════════
#  Section 5 — Unified Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestYouTubeIntelligenceEngine(unittest.TestCase):
    def _make_video(self, video_id: str = "vid-001", title: str = "Test", **kwargs: Any) -> Any:
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
        return VideoEntry(
            video_id=video_id,
            title=title,
            channel_name=kwargs.get("channel_name", "There Is An AI For That"),
            description=kwargs.get("description", ""),
            source=kwargs.get("source", VideoSource.TIAIFT),
            view_count=kwargs.get("view_count", 0),
            like_count=kwargs.get("like_count", 0),
            comment_count=kwargs.get("comment_count", 0),
            tags=kwargs.get("tags", []),
            transcript_snippet=kwargs.get("transcript_snippet", ""),
        )

    def test_ingest_video(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        result = engine.ingest_video(self._make_video())
        assert result["status"] == "ingested"

    def test_extract_tools(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        video = self._make_video(title="ChatGPT vs Claude AI Battle")
        result = engine.extract_tools(video)
        assert result["status"] == "extracted"
        assert result["tools_found"] >= 2

    def test_classify_video(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        video = self._make_video(title="Midjourney V7 Tutorial", description="ai art image generation midjourney")
        result = engine.classify_video(video)
        assert result["status"] == "classified"
        assert result["category"] == "image_generation"

    def test_full_pipeline_routes(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        video = self._make_video(
            title="ChatGPT GPT-4 language model review",
            description="chatgpt llm deep dive",
            view_count=200_000, like_count=5000, comment_count=300,
        )
        result = engine.full_pipeline(video)
        assert result["status"] == "routed"
        assert result["category"] == "text_generation"

    def test_full_pipeline_dedup(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        video = self._make_video(title="Test", view_count=50000, like_count=1000)
        engine.full_pipeline(video)
        result = engine.full_pipeline(video)
        assert result["status"] == "duplicate_skipped"

    def test_full_pipeline_filtered_out(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import ImpactLevel, YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine(min_impact=ImpactLevel.HIGH)
        video = self._make_video(title="Random no-tool video", view_count=0)
        result = engine.full_pipeline(video)
        assert result["status"] == "filtered_out"
        assert result["reason"] == "below_impact_threshold"

    def test_generate_digest(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        result = engine.generate_digest()
        assert result["status"] == "digest_generated"
        assert "total_ingested" in result

    def test_agent_queue(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        result = engine.agent_queue("ai")
        assert result["agent_codename"] == "ai"

    def test_trend_report(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        result = engine.trend_report()
        assert "total_tools_tracked" in result

    def test_routing_summary(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        result = engine.routing_summary()
        assert result["total_dispatches"] == 0

    def test_operational_readiness(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        result = engine.operational_readiness()
        assert result["ready"] is True
        assert result["routing_rules"] == 15
        assert result["categories"] == 15
        assert result["impact_levels"] == 5
        assert result["sources"] == 6
        assert result["pillars"] == 4
        assert result["divisions"] == 8
        assert result["known_tools"] >= 25
        assert result["channels"] == ["There Is An AI For That", "AI Upload"]

    def test_batch_pipeline(self):
        from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
        engine = YouTubeIntelligenceEngine()
        videos = [
            self._make_video(
                video_id="v1", title="ChatGPT GPT-4 language model llm deep dive",
                description="chatgpt gpt prompt llm language model",
                view_count=200_000, like_count=5000, comment_count=300,
            ),
            self._make_video(
                video_id="v2", title="Cursor vs Copilot - Best AI Coding Tool",
                description="cursor copilot code assistant programming ide",
                view_count=150_000, like_count=3000, comment_count=200,
            ),
            self._make_video(
                video_id="v3", title="Sora Video Generation Just Launched - Revolutionary",
                description="sora text to video ai video generation",
                view_count=500_000, like_count=20_000, comment_count=800,
            ),
        ]
        results = [engine.full_pipeline(v) for v in videos]
        routed = [r for r in results if r["status"] == "routed"]
        assert len(routed) >= 2


# ═══════════════════════════════════════════════════════════════
#  Section 6 — CatalystAgent Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestCatalystAgentIntegration(unittest.TestCase):
    def test_catalyst_in_stubs(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert "yt" in EXPANSION_STUBS
        agent = EXPANSION_STUBS["yt"]
        assert agent.codename == "yt"
        assert agent.callsign == "CATALYST"

    def test_catalyst_default_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Test"), {"payload": {}})
        assert result["status"] == "readiness_checked"

    def test_catalyst_ingest_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        event = {
            "payload": {
                "action": "ingest",
                "video": {
                    "video_id": "vid-test-001",
                    "title": "ChatGPT 5 Demo",
                    "channel_name": "There Is An AI For That",
                    "description": "Full chatgpt demo",
                },
            },
        }
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Ingest"), event)
        assert result["status"] == "video_ingested"

    def test_catalyst_extract_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        event = {
            "payload": {
                "action": "extract",
                "video": {
                    "video_id": "vid-test-002",
                    "title": "ChatGPT vs Claude Review",
                    "channel_name": "TIAIFT",
                    "description": "Comparing chatgpt and claude",
                },
            },
        }
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Extract"), event)
        assert result["status"] == "tools_extracted"
        assert result["tools_found"] >= 2

    def test_catalyst_classify_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        event = {
            "payload": {
                "action": "classify",
                "video": {
                    "video_id": "vid-test-003",
                    "title": "Midjourney V7 Tutorial",
                    "channel_name": "TIAIFT",
                    "description": "midjourney image generation ai art",
                },
            },
        }
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Classify"), event)
        assert result["status"] == "video_classified"
        assert result["category"] == "image_generation"

    def test_catalyst_trends_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        event = {"payload": {"action": "trends"}}
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Trends"), event)
        assert result["status"] == "trends_reported"

    def test_catalyst_digest_action(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        event = {"payload": {"action": "digest"}}
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Digest"), event)
        assert result["status"] == "digest_generated"

    def test_catalyst_callsign_in_result(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        result = EXPANSION_STUBS["yt"].handle(Task("T-yt", "yt", "Test"), {"payload": {}})
        assert result["_callsign"] == "CATALYST"


# ═══════════════════════════════════════════════════════════════
#  Section 7 — EventType & Roster Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestYTEventTypes(unittest.TestCase):
    def test_yt_event_types_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        yt_events = [e for e in EventType if e.value.startswith("yt.")]
        assert len(yt_events) == 7

    def test_yt_event_values(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.YT_INGEST.value == "yt.ingest"
        assert EventType.YT_EXTRACT.value == "yt.extract"
        assert EventType.YT_CLASSIFY.value == "yt.classify"
        assert EventType.YT_FILTER.value == "yt.filter"
        assert EventType.YT_ROUTE.value == "yt.route"
        assert EventType.YT_TREND.value == "yt.trend"
        assert EventType.YT_CYCLE.value == "yt.cycle"

    def test_total_event_types(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert len(EventType) == 71


class TestYTRosterIntegration(unittest.TestCase):
    def test_catalyst_in_all_agents(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        codenames = {a.codename for a in ALL_AGENTS}
        assert "yt" in codenames

    def test_catalyst_agent_role(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        catalyst = next(a for a in ALL_AGENTS if a.codename == "yt")
        assert catalyst.callsign == "CATALYST"
        assert catalyst.tier.value == "expansion"
        assert "YouTube" in catalyst.name

    def test_expansion_pack_count(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        assert len(EXPANSION_PACK) == 21

    def test_all_agents_count(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_expansion_stubs_count(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert len(EXPANSION_STUBS) == 21

    def test_callsign_map_has_catalyst(self):
        from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
        assert CALLSIGN_MAP["yt"] == "CATALYST"


# ═══════════════════════════════════════════════════════════════
#  Section 8 — AI Upload Intelligence — Enum Tests
# ═══════════════════════════════════════════════════════════════


class TestContentType(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import ContentType
        assert len(ContentType) == 10

    def test_values(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import ContentType
        expected = {
            "model_release", "company_news", "research_paper", "safety_alignment",
            "agi_progress", "market_analysis", "geopolitical", "expert_opinion",
            "industry_trend", "regulation",
        }
        assert {v.value for v in ContentType} == expected

    def test_str_enum(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import ContentType
        assert str(ContentType.MODEL_RELEASE) == "model_release"


class TestEntityType(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityType
        assert len(EntityType) == 5

    def test_values(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityType
        expected = {"company", "ai_model", "researcher", "institution", "regulation"}
        assert {v.value for v in EntityType} == expected


class TestSignalType(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import SignalType
        assert len(SignalType) == 8

    def test_values(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import SignalType
        expected = {
            "capability_leap", "competitive_shift", "risk_alert",
            "investment_signal", "regulatory_change", "talent_movement",
            "partnership", "paradigm_indicator",
        }
        assert {v.value for v in SignalType} == expected


class TestUrgencyLevel(unittest.TestCase):
    def test_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import UrgencyLevel
        assert len(UrgencyLevel) == 4

    def test_values(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import UrgencyLevel
        expected = {"flash", "priority", "standard", "archive"}
        assert {v.value for v in UrgencyLevel} == expected


# ═══════════════════════════════════════════════════════════════
#  Section 9 — AI Upload Intelligence — Dataclass Tests
# ═══════════════════════════════════════════════════════════════


class TestEntityMention(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            EntityMention,
            EntityType,
        )
        entity = EntityMention(
            name="OpenAI", entity_type=EntityType.COMPANY, is_primary=True,
        )
        assert entity.name == "OpenAI"
        assert entity.entity_type == EntityType.COMPANY
        assert entity.is_primary is True
        assert entity.context == ""

    def test_with_context(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            EntityMention,
            EntityType,
        )
        entity = EntityMention(
            name="GPT-5", entity_type=EntityType.AI_MODEL,
            is_primary=False, context="mentioned in comparison",
        )
        assert entity.context == "mentioned in comparison"


class TestStrategicSignal(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            SignalType,
            StrategicSignal,
            UrgencyLevel,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import (
            PillarMapping,
            RoutingTarget,
        )
        signal = StrategicSignal(
            signal_id="au-abc123",
            signal_type=SignalType.CAPABILITY_LEAP,
            urgency=UrgencyLevel.FLASH,
            title="GPT-5 Released",
            summary="OpenAI releases GPT-5",
            entities=[],
            source_video_id="vid-001",
            confidence=0.9,
            target_division=RoutingTarget.RESEARCH,
            target_pillar=PillarMapping.NCL_BRAIN,
            target_agents=["ai", "wp"],
        )
        assert signal.signal_id.startswith("au-")
        assert signal.urgency == UrgencyLevel.FLASH
        assert len(signal.target_agents) == 2


class TestAnalyzedContent(unittest.TestCase):
    def test_creation(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            AnalyzedContent,
            ContentType,
            UrgencyLevel,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
        video = VideoEntry(
            video_id="v-test", title="Test Video", channel_name="AI Upload",
            description="test video description",
            source=VideoSource.AI_UPLOAD,
        )
        ac = AnalyzedContent(
            video=video, content_type=ContentType.MODEL_RELEASE,
            entities=[], signals=[], urgency=UrgencyLevel.STANDARD,
            confidence=0.7,
        )
        assert ac.content_type == ContentType.MODEL_RELEASE
        assert ac.keywords_matched == []


class TestNarrativeThread(unittest.TestCase):
    def test_creation(self):
        import time as _time

        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            NarrativeThread,
        )
        now = _time.time()
        thread = NarrativeThread(
            thread_id="abcd1234",
            title="model_release: GPT-5 Released",
            content_type=ContentType.MODEL_RELEASE,
            video_ids=["v1", "v2"],
            entities=["OpenAI"],
            signal_count=3,
            first_seen=now,
            last_updated=now,
        )
        assert len(thread.video_ids) == 2
        assert thread.signal_count == 3


class TestIntelligenceBrief(unittest.TestCase):
    def test_creation(self):
        import time as _time

        from ncl_agency_runtime.fpc.ai_upload_intelligence import IntelligenceBrief
        brief = IntelligenceBrief(
            total_analyzed=10, total_signals=5, flash_signals=1,
            priority_signals=2, content_breakdown={"model_release": 4},
            signal_breakdown={"capability_leap": 3},
            top_entities=["OpenAI", "GPT-5"],
            active_narratives=3, generated_at=_time.time(),
        )
        assert brief.total_analyzed == 10
        assert brief.flash_signals == 1


# ═══════════════════════════════════════════════════════════════
#  Section 10 — AI Upload Intelligence — Routing Table Tests
# ═══════════════════════════════════════════════════════════════


class TestContentSignalRouting(unittest.TestCase):
    def test_routing_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import CONTENT_SIGNAL_ROUTING
        assert len(CONTENT_SIGNAL_ROUTING) == 10

    def test_all_content_types_routed(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            CONTENT_SIGNAL_ROUTING,
            ContentType,
        )
        routed = {r.content_type for r in CONTENT_SIGNAL_ROUTING}
        assert routed == set(ContentType)

    def test_every_rule_has_agents(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import CONTENT_SIGNAL_ROUTING
        for rule in CONTENT_SIGNAL_ROUTING:
            assert len(rule.primary_agents) >= 1
            assert len(rule.signal_types) >= 1
            assert len(rule.keywords) >= 5

    def test_model_release_routes_to_research(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            CONTENT_SIGNAL_ROUTING,
            ContentType,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import RoutingTarget
        rule = next(r for r in CONTENT_SIGNAL_ROUTING if r.content_type == ContentType.MODEL_RELEASE)
        assert rule.division == RoutingTarget.RESEARCH
        assert "ai" in rule.primary_agents
        assert "wp" in rule.primary_agents

    def test_safety_routes_to_intelligence(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            CONTENT_SIGNAL_ROUTING,
            ContentType,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import RoutingTarget
        rule = next(r for r in CONTENT_SIGNAL_ROUTING if r.content_type == ContentType.SAFETY_ALIGNMENT)
        assert rule.division == RoutingTarget.INTELLIGENCE
        assert "nc" in rule.primary_agents

    def test_geopolitical_routes_to_mandarin(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            CONTENT_SIGNAL_ROUTING,
            ContentType,
        )
        rule = next(r for r in CONTENT_SIGNAL_ROUTING if r.content_type == ContentType.GEOPOLITICAL)
        assert "jx" in rule.primary_agents

    def test_market_analysis_routes_to_finance(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            CONTENT_SIGNAL_ROUTING,
            ContentType,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import RoutingTarget
        rule = next(r for r in CONTENT_SIGNAL_ROUTING if r.content_type == ContentType.MARKET_ANALYSIS)
        assert rule.division == RoutingTarget.FINANCE
        assert "ab" in rule.primary_agents

    def test_regulation_routes_to_sentinel_and_cipher(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            CONTENT_SIGNAL_ROUTING,
            ContentType,
        )
        rule = next(r for r in CONTENT_SIGNAL_ROUTING if r.content_type == ContentType.REGULATION)
        assert "nc" in rule.primary_agents
        assert "sg" in rule.primary_agents


# ═══════════════════════════════════════════════════════════════
#  Section 11 — AI Upload Intelligence — Engine Tests
# ═══════════════════════════════════════════════════════════════


def _make_au_video(**kwargs: Any) -> Any:
    """Helper to create an AI Upload VideoEntry."""
    from ncl_agency_runtime.fpc.youtube_intelligence import VideoEntry, VideoSource
    return VideoEntry(
        video_id=kwargs.get("video_id", "au-test-001"),
        title=kwargs.get("title", "OpenAI GPT-5 Released — Everything You Need to Know"),
        channel_name=kwargs.get("channel_name", "AI Upload"),
        description=kwargs.get("description", "openai gpt-5 released benchmark state of the art"),
        source=kwargs.get("source", VideoSource.AI_UPLOAD),
        published_at=kwargs.get("published_at", "2025-01-15T12:00:00Z"),
        duration_seconds=kwargs.get("duration_seconds", 900),
        view_count=kwargs.get("view_count", 250_000),
        like_count=kwargs.get("like_count", 10_000),
        comment_count=kwargs.get("comment_count", 500),
        tags=kwargs.get("tags", ["openai", "gpt-5", "ai", "benchmark"]),
        transcript_snippet=kwargs.get("transcript_snippet", "openai released gpt-5 today"),
    )


class TestEntityExtractor(unittest.TestCase):
    def test_known_companies_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor
        assert len(EntityExtractor.KNOWN_COMPANIES) >= 20

    def test_known_models_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor
        assert len(EntityExtractor.KNOWN_MODELS) >= 20

    def test_known_researchers_count(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor
        assert len(EntityExtractor.KNOWN_RESEARCHERS) >= 10

    def test_extract_company(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor, EntityType
        ex = EntityExtractor()
        video = _make_au_video(
            title="OpenAI Announces Major Update",
            description="openai has just announced big changes",
        )
        entities = ex.extract(video)
        companies = [e for e in entities if e.entity_type == EntityType.COMPANY]
        assert len(companies) >= 1
        assert any(e.name == "OpenAI" for e in companies)

    def test_extract_model(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor, EntityType
        ex = EntityExtractor()
        video = _make_au_video(
            title="GPT-5 Benchmark Results Revealed",
            description="gpt-5 achieves state of the art on all benchmarks",
        )
        entities = ex.extract(video)
        models = [e for e in entities if e.entity_type == EntityType.AI_MODEL]
        assert len(models) >= 1

    def test_extract_researcher(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor, EntityType
        ex = EntityExtractor()
        video = _make_au_video(
            title="Sam Altman on the Future of AI",
            description="sam altman discusses agi timelines",
        )
        entities = ex.extract(video)
        researchers = [e for e in entities if e.entity_type == EntityType.RESEARCHER]
        assert len(researchers) >= 1
        assert any(e.name == "Sam Altman" for e in researchers)

    def test_extract_primary_flag(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor
        ex = EntityExtractor()
        video = _make_au_video(
            title="OpenAI GPT-5 Released",
            description="openai released gpt-5",
        )
        entities = ex.extract(video)
        primaries = [e for e in entities if e.is_primary]
        assert len(primaries) >= 1

    def test_deduplicate_entities(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor
        ex = EntityExtractor()
        video = _make_au_video(
            title="OpenAI OpenAI OpenAI",
            description="openai openai openai",
            tags=["openai"],
            transcript_snippet="openai",
        )
        entities = ex.extract(video)
        names = [e.name for e in entities]
        assert names.count("OpenAI") == 1

    def test_no_matches(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import EntityExtractor
        ex = EntityExtractor()
        video = _make_au_video(
            title="Random Topic",
            description="nothing relevant here",
            tags=[], transcript_snippet="",
        )
        entities = ex.extract(video)
        assert len(entities) == 0


class TestContentAnalyzer(unittest.TestCase):
    def test_analyze_model_release(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentAnalyzer,
            ContentType,
            EntityExtractor,
        )
        video = _make_au_video(
            title="GPT-5 Released — State of the Art Benchmarks",
            description="openai gpt-5 launched new model benchmark",
        )
        entities = EntityExtractor().extract(video)
        analyzer = ContentAnalyzer()
        result = analyzer.analyze(video, entities)
        assert result == ContentType.MODEL_RELEASE

    def test_analyze_safety(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentAnalyzer,
            ContentType,
            EntityExtractor,
        )
        video = _make_au_video(
            title="AI Safety Crisis: Alignment Research Falls Behind",
            description="safety alignment risk existential guardrails ethics responsible",
        )
        entities = EntityExtractor().extract(video)
        analyzer = ContentAnalyzer()
        result = analyzer.analyze(video, entities)
        assert result == ContentType.SAFETY_ALIGNMENT

    def test_analyze_geopolitical(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentAnalyzer,
            ContentType,
            EntityExtractor,
        )
        video = _make_au_video(
            title="US vs China AI Race Heats Up — Export Controls Expanded",
            description="china us geopolitical chip export control sanctions ai race",
        )
        entities = EntityExtractor().extract(video)
        analyzer = ContentAnalyzer()
        result = analyzer.analyze(video, entities)
        assert result == ContentType.GEOPOLITICAL

    def test_analyze_regulation(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentAnalyzer,
            ContentType,
            EntityExtractor,
        )
        video = _make_au_video(
            title="EU AI Act Passed — New Regulation Framework for AI",
            description="regulation law act policy compliance ban restrict mandate governance",
        )
        entities = EntityExtractor().extract(video)
        analyzer = ContentAnalyzer()
        result = analyzer.analyze(video, entities)
        assert result == ContentType.REGULATION

    def test_analyze_company_news(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentAnalyzer,
            ContentType,
            EntityExtractor,
        )
        video = _make_au_video(
            title="Anthropic Raised $10B — Valued at $60B",
            description="anthropic raised funding valued ipo ceo restructure",
        )
        entities = EntityExtractor().extract(video)
        analyzer = ContentAnalyzer()
        result = analyzer.analyze(video, entities)
        assert result == ContentType.COMPANY_NEWS

    def test_default_fallback(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentAnalyzer,
            ContentType,
        )
        video = _make_au_video(
            title="Nothing Specific",
            description="",
            tags=[], transcript_snippet="",
        )
        analyzer = ContentAnalyzer()
        result = analyzer.analyze(video, [])
        assert isinstance(result, ContentType)


class TestSignalDetector(unittest.TestCase):
    def test_detect_signals(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            EntityExtractor,
            SignalDetector,
        )
        video = _make_au_video()
        entities = EntityExtractor().extract(video)
        detector = SignalDetector()
        signals = detector.detect(video, ContentType.MODEL_RELEASE, entities)
        assert len(signals) >= 1
        assert all(s.signal_id.startswith("au-") for s in signals)

    def test_urgency_flash(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            EntityExtractor,
            SignalDetector,
            UrgencyLevel,
        )
        video = _make_au_video(
            title="BREAKING: AGI Achieved — Superintelligence is Here",
            description="agi achieved superintelligence safety alignment",
            view_count=1_000_000,
        )
        entities = EntityExtractor().extract(video)
        detector = SignalDetector()
        signals = detector.detect(video, ContentType.AGI_PROGRESS, entities)
        assert any(s.urgency == UrgencyLevel.FLASH for s in signals)

    def test_urgency_archive(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            SignalDetector,
            UrgencyLevel,
        )
        video = _make_au_video(
            title="Some obscure topic",
            description="nothing important",
            view_count=100,
            tags=[], transcript_snippet="",
        )
        detector = SignalDetector()
        signals = detector.detect(video, ContentType.INDUSTRY_TREND, [])
        for sig in signals:
            assert sig.urgency in {UrgencyLevel.STANDARD, UrgencyLevel.ARCHIVE}

    def test_signal_count_tracked(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            SignalDetector,
        )
        video = _make_au_video()
        detector = SignalDetector()
        detector.detect(video, ContentType.MODEL_RELEASE, [])
        assert detector.signal_count >= 1

    def test_signal_breakdown(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            SignalDetector,
        )
        video = _make_au_video()
        detector = SignalDetector()
        detector.detect(video, ContentType.MODEL_RELEASE, [])
        breakdown = detector.signal_breakdown()
        assert len(breakdown) >= 1

    def test_confidence_range(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            ContentType,
            SignalDetector,
        )
        video = _make_au_video()
        detector = SignalDetector()
        signals = detector.detect(video, ContentType.MODEL_RELEASE, [])
        for sig in signals:
            assert 0.0 <= sig.confidence <= 1.0


class TestNarrativeTracker(unittest.TestCase):
    def test_track_creates_thread(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            AnalyzedContent,
            ContentType,
            NarrativeTracker,
            UrgencyLevel,
        )
        video = _make_au_video()
        ac = AnalyzedContent(
            video=video, content_type=ContentType.MODEL_RELEASE,
            entities=[], signals=[], urgency=UrgencyLevel.STANDARD,
            confidence=0.7,
        )
        tracker = NarrativeTracker()
        thread_id = tracker.track(ac)
        assert len(thread_id) == 10
        assert tracker.active_threads == 1

    def test_same_thread_merges(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            AnalyzedContent,
            ContentType,
            NarrativeTracker,
            UrgencyLevel,
        )
        v1 = _make_au_video(video_id="v1")
        v2 = _make_au_video(video_id="v2")
        tracker = NarrativeTracker()
        ac1 = AnalyzedContent(
            video=v1, content_type=ContentType.MODEL_RELEASE,
            entities=[], signals=[], urgency=UrgencyLevel.STANDARD,
            confidence=0.7,
        )
        ac2 = AnalyzedContent(
            video=v2, content_type=ContentType.MODEL_RELEASE,
            entities=[], signals=[], urgency=UrgencyLevel.STANDARD,
            confidence=0.7,
        )
        tid1 = tracker.track(ac1)
        tid2 = tracker.track(ac2)
        assert tid1 == tid2
        assert tracker.active_threads == 1

    def test_entity_frequency(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            AnalyzedContent,
            ContentType,
            EntityMention,
            EntityType,
            NarrativeTracker,
            UrgencyLevel,
        )
        video = _make_au_video()
        ac = AnalyzedContent(
            video=video, content_type=ContentType.MODEL_RELEASE,
            entities=[EntityMention(name="OpenAI", entity_type=EntityType.COMPANY, is_primary=True)],
            signals=[], urgency=UrgencyLevel.STANDARD, confidence=0.7,
        )
        tracker = NarrativeTracker()
        tracker.track(ac)
        top = tracker.top_entities(5)
        assert len(top) >= 1

    def test_narrative_report(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            AnalyzedContent,
            ContentType,
            NarrativeTracker,
            UrgencyLevel,
        )
        video = _make_au_video()
        ac = AnalyzedContent(
            video=video, content_type=ContentType.MODEL_RELEASE,
            entities=[], signals=[], urgency=UrgencyLevel.STANDARD,
            confidence=0.7,
        )
        tracker = NarrativeTracker()
        tracker.track(ac)
        report = tracker.narrative_report()
        assert report["active_threads"] >= 1
        assert "threads" in report
        assert "top_entities" in report


class TestStrategicRouter(unittest.TestCase):
    def test_route_signal(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            SignalType,
            StrategicRouter,
            StrategicSignal,
            UrgencyLevel,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import PillarMapping, RoutingTarget
        router = StrategicRouter()
        signal = StrategicSignal(
            signal_id="au-test123",
            signal_type=SignalType.CAPABILITY_LEAP,
            urgency=UrgencyLevel.PRIORITY,
            title="Test", summary="Test signal",
            entities=[], source_video_id="v1",
            confidence=0.8,
            target_division=RoutingTarget.RESEARCH,
            target_pillar=PillarMapping.NCL_BRAIN,
            target_agents=["ai", "wp"],
        )
        dispatch = router.route(signal)
        assert dispatch["agent_codename"] == "ai"
        assert dispatch["agent_callsign"] == "BEACON"
        assert dispatch["urgency"] == "priority"

    def test_agent_queue(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            SignalType,
            StrategicRouter,
            StrategicSignal,
            UrgencyLevel,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import PillarMapping, RoutingTarget
        router = StrategicRouter()
        signal = StrategicSignal(
            signal_id="au-q123",
            signal_type=SignalType.RISK_ALERT,
            urgency=UrgencyLevel.FLASH,
            title="Test", summary="",
            entities=[], source_video_id="v2",
            confidence=0.9,
            target_division=RoutingTarget.INTELLIGENCE,
            target_pillar=PillarMapping.NCC_COMMAND,
            target_agents=["nc"],
        )
        router.route(signal)
        queue = router.agent_queue("nc")
        assert queue["queued_signals"] == 1
        assert queue["agent_callsign"] == "SENTINEL"

    def test_routing_summary(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            SignalType,
            StrategicRouter,
            StrategicSignal,
            UrgencyLevel,
        )
        from ncl_agency_runtime.fpc.youtube_intelligence import PillarMapping, RoutingTarget
        router = StrategicRouter()
        for i in range(3):
            signal = StrategicSignal(
                signal_id=f"au-sum{i}",
                signal_type=SignalType.COMPETITIVE_SHIFT,
                urgency=UrgencyLevel.STANDARD,
                title="Test", summary="",
                entities=[], source_video_id=f"v{i}",
                confidence=0.7,
                target_division=RoutingTarget.STRATEGY,
                target_pillar=PillarMapping.NCC_COMMAND,
                target_agents=["sa"],
            )
            router.route(signal)
        summary = router.routing_summary()
        assert summary["total_routed"] == 3
        assert summary["agents_targeted"] == 1

    def test_callsign_map_coverage(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import StrategicRouter
        assert len(StrategicRouter.CALLSIGN_MAP) >= 30


class TestBriefGenerator(unittest.TestCase):
    def test_generate(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import (
            BriefGenerator,
            ContentAnalyzer,
            NarrativeTracker,
            SignalDetector,
        )
        bg = BriefGenerator()
        brief = bg.generate(ContentAnalyzer(), SignalDetector(), NarrativeTracker())
        assert brief.total_analyzed == 0
        assert brief.total_signals == 0


# ═══════════════════════════════════════════════════════════════
#  Section 12 — AI Upload Intelligence — Unified Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestAIUploadEngine(unittest.TestCase):
    def test_analyze_video(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        video = _make_au_video()
        result = engine.analyze_video(video)
        assert result["status"] == "analyzed"
        assert result["entities_found"] >= 1

    def test_detect_signals(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        video = _make_au_video()
        result = engine.detect_signals(video)
        assert result["status"] == "signals_detected"
        assert result["signals_found"] >= 1

    def test_full_pipeline(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        video = _make_au_video()
        result = engine.full_pipeline(video)
        assert result["status"] == "routed"
        assert result["entities_found"] >= 1
        assert result["signals_found"] >= 1
        assert result["dispatches"] >= 1
        assert "thread_id" in result

    def test_duplicate_skipped(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        video = _make_au_video()
        r1 = engine.full_pipeline(video)
        r2 = engine.full_pipeline(video)
        assert r1["status"] == "routed"
        assert r2["status"] == "duplicate_skipped"

    def test_generate_brief(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        engine.full_pipeline(_make_au_video())
        result = engine.generate_brief()
        assert result["status"] == "brief_generated"
        assert result["total_analyzed"] >= 1
        assert result["total_signals"] >= 1

    def test_narrative_report(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        engine.full_pipeline(_make_au_video())
        report = engine.narrative_report()
        assert report["active_threads"] >= 1

    def test_routing_summary(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        engine.full_pipeline(_make_au_video())
        summary = engine.routing_summary()
        assert summary["total_routed"] >= 1

    def test_agent_queue(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        engine.full_pipeline(_make_au_video())
        queue = engine.agent_queue("ai")
        assert isinstance(queue["queued_signals"], int)

    def test_operational_readiness(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        result = engine.operational_readiness()
        assert result["ready"] is True
        assert result["channel"] == "AI Upload"
        assert result["content_types"] == 10
        assert result["entity_types"] == 5
        assert result["signal_types"] == 8
        assert result["urgency_levels"] == 4
        assert result["routing_rules"] == 10
        assert result["known_companies"] >= 20
        assert result["known_models"] >= 20
        assert result["known_researchers"] >= 10
        assert result["divisions"] == 8
        assert result["pillars"] == 4

    def test_batch_pipeline(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        videos = [
            _make_au_video(
                video_id="batch-1",
                title="OpenAI GPT-5 Released — State of the Art",
                description="openai released gpt-5 benchmark state of the art",
            ),
            _make_au_video(
                video_id="batch-2",
                title="US vs China AI Race — Export Controls Tightened",
                description="us china geopolitical chip export control sanctions",
            ),
            _make_au_video(
                video_id="batch-3",
                title="AI Safety Experts Sound the Alarm",
                description="safety alignment existential risk guardrails ethics",
            ),
        ]
        results = [engine.full_pipeline(v) for v in videos]
        assert all(r["status"] == "routed" for r in results)
        summary = engine.routing_summary()
        assert summary["total_routed"] >= 3

    def test_safety_video_routes_to_sentinel(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        video = _make_au_video(
            video_id="safety-001",
            title="AI Safety Crisis — Alignment Research Falls Behind",
            description="safety alignment existential risk guardrails containment",
        )
        result = engine.full_pipeline(video)
        assert "nc" in result["target_agents"] or result["content_type"] == "safety_alignment"

    def test_geopolitical_video_routes_to_mandarin(self):
        from ncl_agency_runtime.fpc.ai_upload_intelligence import AIUploadEngine
        engine = AIUploadEngine()
        video = _make_au_video(
            video_id="geo-001",
            title="US-China AI Race — Chips Export Controls Sanctions",
            description="china us geopolitical chip export control sanctions ai race national security",
        )
        result = engine.full_pipeline(video)
        assert "jx" in result["target_agents"] or result["content_type"] == "geopolitical"


# ═══════════════════════════════════════════════════════════════
#  Section 13 — AI Upload — CatalystAgent Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestCatalystAIUploadIntegration(unittest.TestCase):
    def _dispatch(self, action: str, video: dict[str, Any] | None = None) -> dict[str, Any]:
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        payload: dict[str, Any] = {"action": action}
        if video:
            payload["video"] = video
        return EXPANSION_STUBS["yt"].handle(Task("T-au", "yt", "AI Upload test"), {"payload": payload})

    def test_au_ingest(self):
        result = self._dispatch("au_ingest", {
            "video_id": "au-int-001",
            "title": "OpenAI GPT-5 Released",
            "channel_name": "AI Upload",
            "description": "openai gpt-5 released benchmark",
            "source": "ai_upload",
        })
        assert result["status"] == "au_analyzed"
        assert result["entities_found"] >= 1

    def test_au_analyze(self):
        result = self._dispatch("au_analyze", {
            "video_id": "au-int-002",
            "title": "AI Safety Alignment Crisis",
            "channel_name": "AI Upload",
            "description": "safety alignment risk existential",
            "source": "ai_upload",
        })
        assert result["status"] == "au_signals_detected"
        assert result["signals_found"] >= 1

    def test_au_signal(self):
        result = self._dispatch("au_signal", {
            "video_id": "au-int-003",
            "title": "US China AI Race Export Controls",
            "channel_name": "AI Upload",
            "description": "china us geopolitical chip export control sanctions",
            "source": "ai_upload",
            "view_count": 100_000,
        })
        assert result["status"] in {"routed", "au_pipeline_complete"}

    def test_au_brief(self):
        result = self._dispatch("au_brief")
        assert result["status"] == "au_brief_generated"
        assert "total_signals" in result

    def test_au_narrative(self):
        result = self._dispatch("au_narrative")
        assert result["status"] == "au_narrative_reported"
        assert "active_threads" in result

    def test_au_readiness(self):
        result = self._dispatch("au_readiness")
        assert result["status"] == "au_readiness_checked"
        assert result["channel"] == "AI Upload"
        assert result["content_types"] == 10

    def test_au_default_readiness(self):
        """Unknown au_ action falls through to AU readiness."""
        result = self._dispatch("au_unknown")
        assert result["status"] == "au_readiness_checked"

    def test_tiaift_still_works(self):
        """Ensure the original TIAIFT pipeline is unaffected."""
        result = self._dispatch("readiness")
        assert result["status"] == "readiness_checked"
        assert result["ready"] is True
        assert result["sources"] == 6


# ═══════════════════════════════════════════════════════════════
#  Section 14 — AI Upload EventType Tests
# ═══════════════════════════════════════════════════════════════


class TestAUEventTypes(unittest.TestCase):
    def test_au_event_types_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        au_events = [e for e in EventType if e.value.startswith("au.")]
        assert len(au_events) == 6

    def test_au_event_values(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.AU_INGEST.value == "au.ingest"
        assert EventType.AU_ANALYZE.value == "au.analyze"
        assert EventType.AU_SIGNAL.value == "au.signal"
        assert EventType.AU_ENTITY.value == "au.entity"
        assert EventType.AU_NARRATIVE.value == "au.narrative"
        assert EventType.AU_BRIEF.value == "au.brief"

    def test_total_event_types_with_au(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert len(EventType) == 71

    def test_agent_role_updated(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        catalyst = next(a for a in ALL_AGENTS if a.codename == "yt")
        assert "AI Upload" in catalyst.name or "Strategic" in catalyst.name
        assert len(catalyst.capabilities) >= 14
        assert any("AI Upload" in c for c in catalyst.capabilities)


if __name__ == "__main__":
    unittest.main()
