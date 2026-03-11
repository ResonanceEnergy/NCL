"""YouTube Intelligence Engine — "There Is An AI For That" Channel Pipeline.

Ingests YouTube video metadata from the TIAIFT channel (and similar AI-focused
channels), classifies each video by AI tool category, extracts tool mentions
and capabilities, scores relevance and impact, and routes intelligence to the
appropriate NCL agent, division, and NCC Triad pillar.

Covers: video ingestion, tool extraction, category classification, impact
scoring, agent routing, digest generation, and trend tracking.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

# ── Enums ───────────────────────────────────────────────────────


class VideoSource(StrEnum):
    """Origin channel / source type."""

    TIAIFT = "there_is_an_ai_for_that"  # Primary channel
    AI_UPLOAD = "ai_upload"  # AI Upload — strategic AI news & analysis
    SUBSCRIBER_FEED = "subscriber_feed"  # Subscribed channel uploads
    RECOMMENDED = "recommended"  # YT algorithm recommendations
    PLAYLIST = "playlist"  # Curated playlist content
    SEARCH = "search"  # Manual / automated search results


class ToolCategory(StrEnum):
    """AI tool category taxonomy — maps to TIAIFT coverage areas."""

    TEXT_GENERATION = "text_generation"  # ChatGPT, Claude, Gemini, etc.
    IMAGE_GENERATION = "image_generation"  # Midjourney, DALL-E, Stable Diffusion
    VIDEO_GENERATION = "video_generation"  # Sora, Runway, Pika, Kling
    AUDIO_GENERATION = "audio_generation"  # ElevenLabs, Suno, Udio
    CODE_ASSISTANT = "code_assistant"  # Copilot, Cursor, Devin, Replit
    PRODUCTIVITY = "productivity"  # Notion AI, Gamma, Tome, Beautiful.ai
    RESEARCH = "research"  # Perplexity, Elicit, Consensus, SciSpace
    AUTOMATION = "automation"  # Zapier AI, Make, n8n, Agent builders
    DESIGN = "design"  # Canva AI, Figma AI, Looka, Brandmark
    DATA_ANALYSIS = "data_analysis"  # Julius, ChatGPT ADA, Tableau AI
    MARKETING = "marketing"  # Jasper, Copy.ai, AdCreative, HubSpot AI
    MULTI_MODAL = "multi_modal"  # GPT-4o, Gemini Pro, multi-capability
    AGENT_FRAMEWORK = "agent_framework"  # AutoGPT, CrewAI, LangGraph, OpenAI Agents
    OPEN_SOURCE = "open_source"  # Llama, Mistral, Phi, open-weight models
    GENERAL = "general"  # Catch-all / overview / comparison


class ImpactLevel(StrEnum):
    """Assessed impact of the tool or announcement."""

    PARADIGM_SHIFT = "paradigm_shift"  # Industry-changing (new GPT, Sora launch)
    HIGH = "high"  # Major tool release / significant capability
    MODERATE = "moderate"  # Useful update or new entrant
    LOW = "low"  # Minor feature or niche tool
    NOISE = "noise"  # Rehashed content, clickbait


class RoutingTarget(StrEnum):
    """NCL division for routing."""

    RESEARCH = "research"  # NCL Brain — deep analysis
    INNOVATION = "innovation"  # Super Agency — new opportunities
    OPERATIONS = "operations"  # Digital Labour — workflow automation
    INTELLIGENCE = "intelligence"  # NCC Command — strategic intel
    KNOWLEDGE = "knowledge"  # NCL Brain — knowledge base
    COMMUNICATIONS = "communications"  # Super Agency — content/brand
    FINANCE = "finance"  # AAC Bank — commercial potential
    STRATEGY = "strategy"  # NCC Command — strategic decisions


class PillarMapping(StrEnum):
    """NCC Triad pillar mapping."""

    NCL_BRAIN = "ncl_brain"
    AAC_BANK = "aac_bank"
    SUPER_AGENCY = "super_agency"
    NCC_COMMAND = "ncc_command"
    DIGITAL_LABOUR = "digital_labour"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class VideoEntry:
    """A single YouTube video with metadata."""

    video_id: str
    title: str
    channel_name: str
    description: str
    source: VideoSource
    published_at: str = ""
    duration_seconds: int = 0
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    tags: list[str] = field(default_factory=list)
    transcript_snippet: str = ""
    thumbnail_url: str = ""
    url: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.video_id}:{self.channel_name}:{self.title[:60]}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ToolMention:
    """An AI tool mentioned or featured in a video."""

    tool_name: str
    category: ToolCategory
    is_primary: bool  # Primary subject vs passing mention
    capabilities: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class ClassifiedVideo:
    """A video after classification and tool extraction."""

    video: VideoEntry
    category: ToolCategory
    impact: ImpactLevel
    tools: list[ToolMention]
    confidence: float
    routing_target: RoutingTarget
    pillar: PillarMapping
    target_agents: list[str]
    keywords_matched: list[str] = field(default_factory=list)


@dataclass
class CategoryRule:
    """Routing rule for a tool category."""

    category: ToolCategory
    division: RoutingTarget
    pillar: PillarMapping
    primary_agents: list[str]
    keywords: list[str]


@dataclass
class VideoDigest:
    """Summary digest of processed videos."""

    total_ingested: int
    total_classified: int
    total_routed: int
    duplicates_skipped: int
    category_breakdown: dict[str, int]
    impact_breakdown: dict[str, int]
    top_tools: list[str]
    generated_at: float


@dataclass
class AgentDispatch:
    """A dispatch of classified videos to a target agent."""

    dispatch_id: str
    agent_codename: str
    agent_callsign: str
    division: RoutingTarget
    pillar: PillarMapping
    video_ids: list[str]


# ── Routing Table ───────────────────────────────────────────────

CATEGORY_ROUTING: list[CategoryRule] = [
    CategoryRule(
        category=ToolCategory.TEXT_GENERATION,
        division=RoutingTarget.RESEARCH,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["ai", "sb"],  # BEACON + CORTEX
        keywords=["chatgpt", "claude", "gemini", "llm", "language model", "gpt",
                  "text generation", "chat", "prompt", "conversation"],
    ),
    CategoryRule(
        category=ToolCategory.IMAGE_GENERATION,
        division=RoutingTarget.COMMUNICATIONS,
        pillar=PillarMapping.SUPER_AGENCY,
        primary_agents=["ux", "dx"],  # MUSE + creative
        keywords=["midjourney", "dall-e", "stable diffusion", "image generation",
                  "ai art", "text to image", "flux", "ideogram"],
    ),
    CategoryRule(
        category=ToolCategory.VIDEO_GENERATION,
        division=RoutingTarget.COMMUNICATIONS,
        pillar=PillarMapping.SUPER_AGENCY,
        primary_agents=["ux", "ai"],  # MUSE + BEACON
        keywords=["sora", "runway", "pika", "kling", "video generation",
                  "text to video", "ai video", "luma"],
    ),
    CategoryRule(
        category=ToolCategory.AUDIO_GENERATION,
        division=RoutingTarget.COMMUNICATIONS,
        pillar=PillarMapping.SUPER_AGENCY,
        primary_agents=["ux", "sb"],  # MUSE + CORTEX
        keywords=["elevenlabs", "suno", "udio", "ai music", "text to speech",
                  "voice clone", "audio generation", "ai voice"],
    ),
    CategoryRule(
        category=ToolCategory.CODE_ASSISTANT,
        division=RoutingTarget.OPERATIONS,
        pillar=PillarMapping.DIGITAL_LABOUR,
        primary_agents=["so", "dx"],  # Launch squadron ops + dev
        keywords=["copilot", "cursor", "devin", "replit", "code assistant",
                  "ai coding", "programming", "developer tool", "ide"],
    ),
    CategoryRule(
        category=ToolCategory.PRODUCTIVITY,
        division=RoutingTarget.OPERATIONS,
        pillar=PillarMapping.DIGITAL_LABOUR,
        primary_agents=["so", "hr"],  # Ops + NIGHTFALL
        keywords=["notion", "gamma", "beautiful.ai", "productivity",
                  "presentation", "document", "workspace", "tome"],
    ),
    CategoryRule(
        category=ToolCategory.RESEARCH,
        division=RoutingTarget.RESEARCH,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["ds", "sb"],  # Data Scientist + CORTEX
        keywords=["perplexity", "elicit", "consensus", "research",
                  "academic", "paper", "citation", "literature"],
    ),
    CategoryRule(
        category=ToolCategory.AUTOMATION,
        division=RoutingTarget.OPERATIONS,
        pillar=PillarMapping.DIGITAL_LABOUR,
        primary_agents=["so", "ai"],  # Ops + BEACON
        keywords=["zapier", "make", "n8n", "automation", "workflow",
                  "integration", "no-code", "low-code", "agent builder"],
    ),
    CategoryRule(
        category=ToolCategory.DESIGN,
        division=RoutingTarget.COMMUNICATIONS,
        pillar=PillarMapping.SUPER_AGENCY,
        primary_agents=["ux", "dx"],  # MUSE + creative
        keywords=["canva", "figma", "looka", "design", "brand",
                  "logo", "ui", "ux", "graphic", "template"],
    ),
    CategoryRule(
        category=ToolCategory.DATA_ANALYSIS,
        division=RoutingTarget.RESEARCH,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["ds", "fo"],  # Data Scientist + Forecaster
        keywords=["julius", "tableau", "data analysis", "analytics",
                  "visualization", "spreadsheet", "csv", "dashboard"],
    ),
    CategoryRule(
        category=ToolCategory.MARKETING,
        division=RoutingTarget.INNOVATION,
        pillar=PillarMapping.SUPER_AGENCY,
        primary_agents=["ne", "dx"],  # Network + creative
        keywords=["jasper", "copy.ai", "adcreative", "marketing",
                  "seo", "copywriting", "ad", "content marketing"],
    ),
    CategoryRule(
        category=ToolCategory.MULTI_MODAL,
        division=RoutingTarget.INTELLIGENCE,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["ai", "wp"],  # BEACON + WOLFRAM
        keywords=["gpt-4o", "gemini pro", "multi-modal", "multimodal",
                  "vision", "omni", "all-in-one"],
    ),
    CategoryRule(
        category=ToolCategory.AGENT_FRAMEWORK,
        division=RoutingTarget.STRATEGY,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["ai", "sa"],  # BEACON + NEXUS
        keywords=["autogpt", "crewai", "langgraph", "agent", "agentic",
                  "multi-agent", "swarm", "autonomous", "openai agents"],
    ),
    CategoryRule(
        category=ToolCategory.OPEN_SOURCE,
        division=RoutingTarget.RESEARCH,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["ai", "ds"],  # BEACON + Data Scientist
        keywords=["llama", "mistral", "phi", "open source", "open-source",
                  "open weight", "huggingface", "ollama", "local"],
    ),
    CategoryRule(
        category=ToolCategory.GENERAL,
        division=RoutingTarget.KNOWLEDGE,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["sb"],  # CORTEX
        keywords=[],
    ),
]


# ── Engine Classes ──────────────────────────────────────────────


class VideoCollector:
    """Ingests YouTube video entries with deduplication."""

    def __init__(self) -> None:
        self._videos: list[VideoEntry] = []
        self._seen: set[str] = set()
        self._duplicates = 0

    def ingest(self, video: VideoEntry) -> dict[str, Any]:
        if video.fingerprint in self._seen:
            self._duplicates += 1
            return {"ingested": False, "reason": "duplicate", "fingerprint": video.fingerprint}
        self._seen.add(video.fingerprint)
        self._videos.append(video)
        return {"ingested": True, "video_id": video.video_id, "fingerprint": video.fingerprint}

    @property
    def count(self) -> int:
        return len(self._videos)

    @property
    def duplicate_count(self) -> int:
        return self._duplicates


class ToolExtractor:
    """Extracts AI tool mentions from video metadata."""

    # Map of known tool name patterns to categories
    KNOWN_TOOLS: ClassVar[dict[str, ToolCategory]] = {
        "chatgpt": ToolCategory.TEXT_GENERATION,
        "claude": ToolCategory.TEXT_GENERATION,
        "gemini": ToolCategory.TEXT_GENERATION,
        "gpt-4": ToolCategory.TEXT_GENERATION,
        "gpt-5": ToolCategory.TEXT_GENERATION,
        "llama": ToolCategory.OPEN_SOURCE,
        "mistral": ToolCategory.OPEN_SOURCE,
        "midjourney": ToolCategory.IMAGE_GENERATION,
        "dall-e": ToolCategory.IMAGE_GENERATION,
        "stable diffusion": ToolCategory.IMAGE_GENERATION,
        "flux": ToolCategory.IMAGE_GENERATION,
        "sora": ToolCategory.VIDEO_GENERATION,
        "runway": ToolCategory.VIDEO_GENERATION,
        "pika": ToolCategory.VIDEO_GENERATION,
        "elevenlabs": ToolCategory.AUDIO_GENERATION,
        "suno": ToolCategory.AUDIO_GENERATION,
        "copilot": ToolCategory.CODE_ASSISTANT,
        "cursor": ToolCategory.CODE_ASSISTANT,
        "devin": ToolCategory.CODE_ASSISTANT,
        "replit": ToolCategory.CODE_ASSISTANT,
        "perplexity": ToolCategory.RESEARCH,
        "notion": ToolCategory.PRODUCTIVITY,
        "zapier": ToolCategory.AUTOMATION,
        "canva": ToolCategory.DESIGN,
        "figma": ToolCategory.DESIGN,
        "jasper": ToolCategory.MARKETING,
        "autogpt": ToolCategory.AGENT_FRAMEWORK,
        "crewai": ToolCategory.AGENT_FRAMEWORK,
        "langgraph": ToolCategory.AGENT_FRAMEWORK,
    }

    def extract(self, video: VideoEntry) -> list[ToolMention]:
        """Extract tool mentions from title, description, tags, and transcript."""
        searchable = " ".join([
            video.title.lower(),
            video.description.lower(),
            " ".join(video.tags).lower(),
            video.transcript_snippet.lower(),
        ])

        tools: list[ToolMention] = []
        found_names: set[str] = set()

        for tool_name, category in self.KNOWN_TOOLS.items():
            if tool_name in searchable and tool_name not in found_names:
                found_names.add(tool_name)
                # Primary if in title
                is_primary = tool_name in video.title.lower()
                tools.append(ToolMention(
                    tool_name=tool_name,
                    category=category,
                    is_primary=is_primary,
                ))

        return tools


class VideoClassifier:
    """Classifies videos by AI tool category, impact, and routing target."""

    def __init__(self) -> None:
        self._routing_index: dict[ToolCategory, CategoryRule] = {
            r.category: r for r in CATEGORY_ROUTING
        }
        self._classified: list[ClassifiedVideo] = []

    def classify(self, video: VideoEntry, tools: list[ToolMention]) -> ClassifiedVideo:
        """Classify a video based on extracted tools and content analysis."""
        category = self._determine_category(video, tools)
        impact = self._assess_impact(video, tools)
        rule = self._routing_index.get(category, self._routing_index[ToolCategory.GENERAL])
        confidence = self._compute_confidence(video, category)
        keywords = self._matched_keywords(video, rule)

        classified = ClassifiedVideo(
            video=video,
            category=category,
            impact=impact,
            tools=tools,
            confidence=confidence,
            routing_target=rule.division,
            pillar=rule.pillar,
            target_agents=rule.primary_agents,
            keywords_matched=keywords,
        )
        self._classified.append(classified)
        return classified

    def _determine_category(self, video: VideoEntry, tools: list[ToolMention]) -> ToolCategory:
        """Determine primary tool category from tools or keyword analysis."""
        # If we have primary tools, use the most common category
        primary_tools = [t for t in tools if t.is_primary]
        if primary_tools:
            return primary_tools[0].category

        # If we have any tools, use the first
        if tools:
            return tools[0].category

        # Fallback to keyword analysis
        searchable = f"{video.title} {video.description}".lower()
        best_score = 0
        best_category = ToolCategory.GENERAL

        for rule in CATEGORY_ROUTING:
            if not rule.keywords:
                continue
            score = sum(1 for kw in rule.keywords if kw in searchable)
            if score > best_score:
                best_score = score
                best_category = rule.category

        return best_category

    def _assess_impact(self, video: VideoEntry, tools: list[ToolMention]) -> ImpactLevel:
        """Score impact based on engagement, recency, and tool significance."""
        score = 0

        # Engagement signals
        if video.view_count > 500_000:
            score += 3
        elif video.view_count > 100_000:
            score += 2
        elif video.view_count > 10_000:
            score += 1

        if video.like_count > 10_000:
            score += 2
        elif video.like_count > 1_000:
            score += 1

        if video.comment_count > 500:
            score += 1

        # Content signals
        title_lower = video.title.lower()
        paradigm_words = ["revolutionary", "game changer", "completely new",
                         "breakthrough", "just launched", "first ever"]
        if any(w in title_lower for w in paradigm_words):
            score += 2

        # Primary tool features score higher
        if any(t.is_primary for t in tools):
            score += 1

        if score >= 7:
            return ImpactLevel.PARADIGM_SHIFT
        if score >= 5:
            return ImpactLevel.HIGH
        if score >= 3:
            return ImpactLevel.MODERATE
        if score >= 1:
            return ImpactLevel.LOW
        return ImpactLevel.NOISE

    def _compute_confidence(self, video: VideoEntry, category: ToolCategory) -> float:
        """Compute classification confidence 0.0-1.0."""
        if category == ToolCategory.GENERAL:
            return 0.3
        searchable = f"{video.title} {video.description}".lower()
        rule = self._routing_index.get(category)
        if not rule or not rule.keywords:
            return 0.4
        matches = sum(1 for kw in rule.keywords if kw in searchable)
        return min(1.0, round(0.4 + (matches * 0.1), 2))

    def _matched_keywords(self, video: VideoEntry, rule: CategoryRule) -> list[str]:
        """Return which keywords matched."""
        searchable = f"{video.title} {video.description}".lower()
        return [kw for kw in rule.keywords if kw in searchable]

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cv in self._classified:
            key = cv.category.value
            counts[key] = counts.get(key, 0) + 1
        return counts


class ImpactFilter:
    """Filters videos below an impact threshold."""

    def __init__(self, min_impact: ImpactLevel = ImpactLevel.LOW) -> None:
        self._min_impact = min_impact
        self._impact_rank = {
            ImpactLevel.NOISE: 0,
            ImpactLevel.LOW: 1,
            ImpactLevel.MODERATE: 2,
            ImpactLevel.HIGH: 3,
            ImpactLevel.PARADIGM_SHIFT: 4,
        }
        self._passed: list[ClassifiedVideo] = []
        self._filtered: list[ClassifiedVideo] = []

    def apply(self, classified: ClassifiedVideo) -> bool:
        rank = self._impact_rank.get(classified.impact, 0)
        threshold = self._impact_rank.get(self._min_impact, 1)
        if rank >= threshold:
            self._passed.append(classified)
            return True
        self._filtered.append(classified)
        return False

    @property
    def passed_count(self) -> int:
        return len(self._passed)

    @property
    def filtered_count(self) -> int:
        return len(self._filtered)

    def stats(self) -> dict[str, Any]:
        return {
            "passed": self.passed_count,
            "filtered": self.filtered_count,
            "min_impact": self._min_impact.value,
        }


class VideoRouter:
    """Routes classified videos to target agents."""

    CALLSIGN_MAP: ClassVar[dict[str, str]] = {
        "mc": "PRIME", "ds": "LENS", "be": "PULSE", "ne": "WEB",
        "fo": "HORIZON", "xe": "SPARK", "cs": "AEGIS", "mo": "COMPASS",
        "so": "FORGE", "dx": "PIXEL", "ir": "MINDGATE", "ss": "PHOENIX",
        "sp": "NAVIGATOR", "es": "SANCTUM", "em": "WATCHTOWER",
        "ux": "MUSE", "an": "COUNCILOR", "hr": "NIGHTFALL",
        "rt": "SPECTRE", "si": "BRIDGE", "wp": "WOLFRAM",
        "nc": "SENTINEL", "ab": "VAULT", "sa": "NEXUS",
        "sg": "CIPHER", "rd": "AEGIS", "jx": "MANDARIN",
        "sb": "CORTEX", "ai": "BEACON", "xf": "HERALD", "yt": "CATALYST",
    }

    def __init__(self) -> None:
        self._dispatches: list[AgentDispatch] = []
        self._agent_queues: dict[str, list[str]] = {}

    def route(self, classified: ClassifiedVideo) -> AgentDispatch:
        primary = classified.target_agents[0] if classified.target_agents else "sb"
        callsign = self.CALLSIGN_MAP.get(primary, primary.upper())
        dispatch = AgentDispatch(
            dispatch_id=f"yd-{classified.video.fingerprint[:8]}-{primary}",
            agent_codename=primary,
            agent_callsign=callsign,
            division=classified.routing_target,
            pillar=classified.pillar,
            video_ids=[classified.video.video_id],
        )
        self._dispatches.append(dispatch)
        if primary not in self._agent_queues:
            self._agent_queues[primary] = []
        self._agent_queues[primary].append(classified.video.video_id)
        return dispatch

    def agent_queue(self, codename: str) -> dict[str, Any]:
        queue = self._agent_queues.get(codename, [])
        return {
            "agent_codename": codename,
            "agent_callsign": self.CALLSIGN_MAP.get(codename, codename.upper()),
            "queued_videos": len(queue),
            "video_ids": queue,
        }

    def routing_summary(self) -> dict[str, Any]:
        summary: dict[str, int] = {}
        for dispatch in self._dispatches:
            key = dispatch.agent_codename
            summary[key] = summary.get(key, 0) + 1
        return {
            "total_dispatches": len(self._dispatches),
            "agents_targeted": len(summary),
            "dispatch_counts": summary,
        }


class TrendTracker:
    """Tracks AI tool trends over time from video data."""

    def __init__(self) -> None:
        self._tool_mentions: dict[str, int] = {}
        self._category_frequency: dict[str, int] = {}
        self._recent_launches: list[dict[str, Any]] = []

    def track(self, classified: ClassifiedVideo) -> None:
        """Record a classified video for trend tracking."""
        for tool in classified.tools:
            self._tool_mentions[tool.tool_name] = (
                self._tool_mentions.get(tool.tool_name, 0) + 1
            )
        cat = classified.category.value
        self._category_frequency[cat] = self._category_frequency.get(cat, 0) + 1

        if classified.impact in (ImpactLevel.HIGH, ImpactLevel.PARADIGM_SHIFT):
            self._recent_launches.append({
                "video_id": classified.video.video_id,
                "title": classified.video.title,
                "category": classified.category.value,
                "impact": classified.impact.value,
                "tools": [t.tool_name for t in classified.tools],
            })

    def trending_tools(self, top_n: int = 10) -> list[tuple[str, int]]:
        """Return top-N most mentioned tools."""
        sorted_tools = sorted(
            self._tool_mentions.items(), key=lambda x: x[1], reverse=True,
        )
        return sorted_tools[:top_n]

    def hot_categories(self) -> dict[str, int]:
        return dict(self._category_frequency)

    def recent_launches(self) -> list[dict[str, Any]]:
        return list(self._recent_launches)

    def trend_report(self) -> dict[str, Any]:
        return {
            "total_tools_tracked": len(self._tool_mentions),
            "trending": self.trending_tools(5),
            "hot_categories": self.hot_categories(),
            "recent_high_impact": len(self._recent_launches),
        }


class DigestGenerator:
    """Generates a summary digest of processed YouTube intelligence."""

    def generate(
        self,
        collector: VideoCollector,
        classifier: VideoClassifier,
        impact_filter: ImpactFilter,
        tracker: TrendTracker,
    ) -> VideoDigest:
        return VideoDigest(
            total_ingested=collector.count,
            total_classified=len(classifier.category_counts()),
            total_routed=impact_filter.passed_count,
            duplicates_skipped=collector.duplicate_count,
            category_breakdown=classifier.category_counts(),
            impact_breakdown=impact_filter.stats(),
            top_tools=[t[0] for t in tracker.trending_tools(5)],
            generated_at=time.time(),
        )


# ── Unified Engine ──────────────────────────────────────────────


class YouTubeIntelligenceEngine:
    """Unified engine: ingest → extract → classify → filter → route → track."""

    def __init__(self, min_impact: ImpactLevel = ImpactLevel.LOW) -> None:
        self.collector = VideoCollector()
        self.extractor = ToolExtractor()
        self.classifier = VideoClassifier()
        self.impact_filter = ImpactFilter(min_impact)
        self.router = VideoRouter()
        self.tracker = TrendTracker()
        self.digest_gen = DigestGenerator()

    def ingest_video(self, video: VideoEntry) -> dict[str, Any]:
        """Ingest a video entry."""
        result = self.collector.ingest(video)
        return {"status": "ingested", **result}

    def extract_tools(self, video: VideoEntry) -> dict[str, Any]:
        """Extract tool mentions from a video."""
        tools = self.extractor.extract(video)
        return {
            "status": "extracted",
            "video_id": video.video_id,
            "tools_found": len(tools),
            "tools": [{"name": t.tool_name, "category": t.category.value, "primary": t.is_primary} for t in tools],
        }

    def classify_video(self, video: VideoEntry) -> dict[str, Any]:
        """Extract tools and classify a video."""
        tools = self.extractor.extract(video)
        classified = self.classifier.classify(video, tools)
        return {
            "status": "classified",
            "video_id": video.video_id,
            "category": classified.category.value,
            "impact": classified.impact.value,
            "confidence": classified.confidence,
            "tools": len(tools),
            "routing_target": classified.routing_target.value,
        }

    def filter_video(self, classified: ClassifiedVideo) -> dict[str, Any]:
        """Apply impact filter to a classified video."""
        passed = self.impact_filter.apply(classified)
        return {
            "status": "filtered",
            "video_id": classified.video.video_id,
            "passed": passed,
            "impact": classified.impact.value,
        }

    def route_video(self, classified: ClassifiedVideo) -> dict[str, Any]:
        """Route a classified video to target agents."""
        dispatch = self.router.route(classified)
        return {
            "status": "routed",
            "dispatch_id": dispatch.dispatch_id,
            "agent_codename": dispatch.agent_codename,
            "agent_callsign": dispatch.agent_callsign,
            "division": dispatch.division.value,
            "pillar": dispatch.pillar.value,
            "video_ids": dispatch.video_ids,
        }

    def full_pipeline(self, video: VideoEntry) -> dict[str, Any]:
        """Run the complete pipeline: ingest → extract → classify → filter → route → track."""
        ingest_result = self.collector.ingest(video)
        if not ingest_result.get("ingested", False):
            return {"status": "duplicate_skipped", **ingest_result}

        tools = self.extractor.extract(video)
        classified = self.classifier.classify(video, tools)
        self.tracker.track(classified)
        passed = self.impact_filter.apply(classified)

        if not passed:
            return {
                "status": "filtered_out",
                "video_id": video.video_id,
                "category": classified.category.value,
                "impact": classified.impact.value,
                "reason": "below_impact_threshold",
            }

        dispatch = self.router.route(classified)
        return {
            "status": "routed",
            "video_id": video.video_id,
            "category": classified.category.value,
            "impact": classified.impact.value,
            "confidence": classified.confidence,
            "division": classified.routing_target.value,
            "pillar": classified.pillar.value,
            "target_agents": classified.target_agents,
            "dispatch_id": dispatch.dispatch_id,
        }

    def generate_digest(self) -> dict[str, Any]:
        """Generate a digest of all processed videos."""
        digest = self.digest_gen.generate(
            self.collector, self.classifier, self.impact_filter, self.tracker,
        )
        return {
            "status": "digest_generated",
            "total_ingested": digest.total_ingested,
            "total_classified": digest.total_classified,
            "total_routed": digest.total_routed,
            "duplicates_skipped": digest.duplicates_skipped,
            "category_breakdown": digest.category_breakdown,
            "top_tools": digest.top_tools,
            "generated_at": digest.generated_at,
        }

    def agent_queue(self, codename: str) -> dict[str, Any]:
        """Get the dispatch queue for a specific agent."""
        return self.router.agent_queue(codename)

    def trend_report(self) -> dict[str, Any]:
        """Get current AI tool trend report."""
        return self.tracker.trend_report()

    def routing_summary(self) -> dict[str, Any]:
        """Get routing dispatch summary."""
        return self.router.routing_summary()

    def operational_readiness(self) -> dict[str, Any]:
        """Report operational readiness."""
        return {
            "ready": True,
            "engine": "YouTubeIntelligenceEngine",
            "channels": ["There Is An AI For That", "AI Upload"],
            "routing_rules": len(CATEGORY_ROUTING),
            "categories": len(ToolCategory),
            "impact_levels": len(ImpactLevel),
            "sources": len(VideoSource),
            "pillars": len(PillarMapping),
            "divisions": len(RoutingTarget),
            "known_tools": len(ToolExtractor.KNOWN_TOOLS),
        }
