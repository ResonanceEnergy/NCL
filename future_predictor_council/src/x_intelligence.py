"""X (Twitter) Intelligence Engine — Feed, Likes & Reposts Pipeline.

Ingests an X account's timeline (feed, likes, reposts), classifies each
item by content domain, urgency, and engagement type, then routes the
intelligence to the appropriate NCL agency / agent / division.

Routing taxonomy maps content to the 30-agent council, the NCC Triad
pillars (NCL-Brain, AAC-Bank, BRS), and functional divisions
(Intelligence, Strategy, Operations, Research, Governance).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar
from xml.etree import ElementTree

try:
    from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP as _CANONICAL_CALLSIGN_MAP
except ImportError:
    _CANONICAL_CALLSIGN_MAP = {}

# ── Enums ───────────────────────────────────────────────────────

class EngagementType(StrEnum):
    """How the account interacted with the content."""

    ORIGINAL = "original"      # User's own post
    LIKE = "like"              # Liked someone else's post
    REPOST = "repost"          # Retweeted / reposted
    REPLY = "reply"            # Replied to a thread
    QUOTE = "quote"            # Quote-tweeted
    BOOKMARK = "bookmark"      # Bookmarked for later


class ContentDomain(StrEnum):
    """Primary content classification domain."""

    AI_TECHNOLOGY = "ai_technology"
    FINANCE_MARKETS = "finance_markets"
    GEOPOLITICS = "geopolitics"
    SCIENCE_RESEARCH = "science_research"
    ENTREPRENEURSHIP = "entrepreneurship"
    SECURITY_INTELLIGENCE = "security_intelligence"
    PHILOSOPHY_WISDOM = "philosophy_wisdom"
    HEALTH_LONGEVITY = "health_longevity"
    PERSONAL_BRAND = "personal_brand"
    OPERATIONS_PRODUCTIVITY = "operations_productivity"
    CREATIVE_MEDIA = "creative_media"
    GENERAL = "general"


class UrgencyLevel(StrEnum):
    """How time-sensitive the content is."""

    ARCHIVE = "archive"        # No urgency — reference material
    LOW = "low"                # Interesting but not time-sensitive
    MEDIUM = "medium"          # Should be processed within 24h
    HIGH = "high"              # Needs attention within hours
    FLASH = "flash"            # Immediate action required


class RoutingDivision(StrEnum):
    """Functional division within the NCL agency structure."""

    INTELLIGENCE = "intelligence"    # SIGINT, analysis, threat detection
    STRATEGY = "strategy"            # High-level planning, doctrine
    OPERATIONS = "operations"        # Execution, task dispatch, workflow
    RESEARCH = "research"            # Deep analysis, forecasting, models
    GOVERNANCE = "governance"        # Compliance, audit, policy
    FINANCE = "finance"              # Markets, portfolio, trading signals
    KNOWLEDGE = "knowledge"          # Learning, second brain, memory
    COMMUNICATIONS = "communications"  # Brand, outreach, content
    INNOVATION = "innovation"        # Moonshots, exponential tech, R&D


class PillarTarget(StrEnum):
    """NCC Triad pillar routing target."""

    NCL_BRAIN = "ncl_brain"                # Cognitive augmentation (NCL)
    AAC_BANK = "aac_bank"                  # Algorithmic Asset Command
    BIT_RAGE_SYSTEMS = "bit_rage_systems"   # Agent workforce + autonomous workers
    NCC_COMMAND = "ncc_command"            # Cross-pillar coordination


class SignalQuality(StrEnum):
    """Quality / reliability of the signal."""

    NOISE = "noise"            # Low-quality, ignore
    WEAK = "weak"              # Potentially useful, needs verification
    MODERATE = "moderate"      # Decent signal, standard processing
    STRONG = "strong"          # High-quality, prioritise
    VERIFIED = "verified"      # Cross-referenced, confirmed


# ── Dataclasses ─────────────────────────────────────────────────

@dataclass
class XPost:
    """A single X post (tweet) with metadata."""

    post_id: str
    author_handle: str
    author_name: str
    content: str
    engagement_type: EngagementType
    timestamp: str = ""
    url: str = ""
    media_urls: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    like_count: int = 0
    repost_count: int = 0
    reply_count: int = 0
    view_count: int = 0
    language: str = "en"
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.post_id}:{self.author_handle}:{self.content[:80]}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ClassifiedPost:
    """An X post after classification and routing assignment."""

    post: XPost
    domain: ContentDomain
    urgency: UrgencyLevel
    quality: SignalQuality
    division: RoutingDivision
    pillar: PillarTarget
    target_agents: list[str]  # Agent codenames
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
    classified_at: float = field(default_factory=time.time)


@dataclass
class RoutingRule:
    """Maps a content domain to its routing targets."""

    domain: ContentDomain
    division: RoutingDivision
    pillar: PillarTarget
    primary_agents: list[str]   # Agent codenames to notify
    secondary_agents: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class FeedDigest:
    """Summary of a batch of processed X feed items."""

    digest_id: str
    date: str
    total_processed: int
    by_engagement: dict[str, int]
    by_domain: dict[str, int]
    by_urgency: dict[str, int]
    by_division: dict[str, int]
    by_pillar: dict[str, int]
    top_posts: list[str]  # post_ids of highest-quality items
    routed_count: int
    filtered_count: int
    quality_distribution: dict[str, int]
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentDispatch:
    """Record of content dispatched to a specific agent."""

    dispatch_id: str
    agent_codename: str
    agent_callsign: str
    post_ids: list[str]
    domain: ContentDomain
    urgency: UrgencyLevel
    division: RoutingDivision
    pillar: PillarTarget
    dispatched_at: float = field(default_factory=time.time)


# ── Routing Table ───────────────────────────────────────────────

# Domain → (Division, Pillar, Primary Agents, Secondary Agents, Keywords)
# Agent codenames from the 30-agent council
# Keywords loaded from canonical registry: _config/topics_registry.json

# Map ContentDomain → registry domain names for keyword loading
_DOMAIN_REGISTRY_MAP: dict[str, list[str]] = {
    "ai_technology": ["ai_technology"],
    "finance_markets": ["finance_markets"],
    "geopolitics": ["geopolitics"],
    "science_research": ["science_research"],
    "entrepreneurship": ["entrepreneurship"],
    "security_intelligence": ["security_intelligence"],
    "philosophy_wisdom": ["philosophy_wisdom"],
    "health_longevity": ["health_longevity"],
    "personal_brand": ["personal_brand"],
    "operations_productivity": ["operations_productivity"],
    "creative_media": ["creative_media"],
}

_ROUTING_KEYWORDS_LOADED = False


def _load_routing_keywords() -> dict[str, list[str]]:
    """Load keywords from canonical registry, keyed by ContentDomain value."""
    from .topics_registry import get_keywords_mapped
    return get_keywords_mapped(_DOMAIN_REGISTRY_MAP)


ROUTING_TABLE: list[RoutingRule] = [
    RoutingRule(
        domain=ContentDomain.AI_TECHNOLOGY,
        division=RoutingDivision.RESEARCH,
        pillar=PillarTarget.NCL_BRAIN,
        primary_agents=["ai", "ds"],   # BEACON (AI Daily Brief), DataScience
        secondary_agents=["wp", "sb"],  # WOLFRAM, CORTEX (Second Brain)
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.FINANCE_MARKETS,
        division=RoutingDivision.FINANCE,
        pillar=PillarTarget.AAC_BANK,
        primary_agents=["fo", "ne"],   # Forecasting, Network
        secondary_agents=["mc", "an"],  # MissionControl, COUNCILOR
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.GEOPOLITICS,
        division=RoutingDivision.STRATEGY,
        pillar=PillarTarget.NCC_COMMAND,
        primary_agents=["jx", "nc"],   # MANDARIN (Geopolitical), SENTINEL (NCC)
        secondary_agents=["sg", "rd"],  # CIPHER, AEGIS (Unit 8200)
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.SCIENCE_RESEARCH,
        division=RoutingDivision.RESEARCH,
        pillar=PillarTarget.NCL_BRAIN,
        primary_agents=["wp", "ds"],   # WOLFRAM, DataScience
        secondary_agents=["sb", "ai"],  # CORTEX, BEACON
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.ENTREPRENEURSHIP,
        division=RoutingDivision.INNOVATION,
        pillar=PillarTarget.BIT_RAGE_SYSTEMS,
        primary_agents=["ai", "sa"],   # BEACON (exponential), NEXUS (BRS)
        secondary_agents=["ux", "sp"],  # MUSE, NAVIGATOR
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.SECURITY_INTELLIGENCE,
        division=RoutingDivision.INTELLIGENCE,
        pillar=PillarTarget.NCC_COMMAND,
        primary_agents=["sg", "rd"],   # CIPHER, AEGIS (Unit 8200)
        secondary_agents=["nc", "em"],  # SENTINEL, WATCHTOWER
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.PHILOSOPHY_WISDOM,
        division=RoutingDivision.KNOWLEDGE,
        pillar=PillarTarget.NCL_BRAIN,
        primary_agents=["sb", "an"],   # CORTEX (Second Brain), COUNCILOR
        secondary_agents=["ir", "ux"],  # MINDGATE, MUSE
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.HEALTH_LONGEVITY,
        division=RoutingDivision.RESEARCH,
        pillar=PillarTarget.NCL_BRAIN,
        primary_agents=["ai", "sb"],   # BEACON (longevity), CORTEX
        secondary_agents=["wp", "es"],  # WOLFRAM, SANCTUM
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.PERSONAL_BRAND,
        division=RoutingDivision.COMMUNICATIONS,
        pillar=PillarTarget.BIT_RAGE_SYSTEMS,
        primary_agents=["ux", "dx"],   # MUSE, DevEx
        secondary_agents=["sb", "si"],  # CORTEX, BRIDGE
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.OPERATIONS_PRODUCTIVITY,
        division=RoutingDivision.OPERATIONS,
        pillar=PillarTarget.BIT_RAGE_SYSTEMS,
        primary_agents=["so", "hr"],   # SysOps, NIGHTFALL
        secondary_agents=["rt", "es"],  # SPECTRE, SANCTUM
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.CREATIVE_MEDIA,
        division=RoutingDivision.COMMUNICATIONS,
        pillar=PillarTarget.BIT_RAGE_SYSTEMS,
        primary_agents=["ux", "sb"],   # MUSE, CORTEX
        secondary_agents=["si", "dx"],  # BRIDGE, DevEx
        keywords=[],  # loaded from registry
    ),
    RoutingRule(
        domain=ContentDomain.GENERAL,
        division=RoutingDivision.KNOWLEDGE,
        pillar=PillarTarget.NCL_BRAIN,
        primary_agents=["sb"],         # CORTEX (Second Brain captures everything)
        secondary_agents=["mc"],       # MissionControl
        keywords=[],                   # Catch-all — stays empty
    ),
]


def _ensure_routing_keywords() -> None:
    """Populate ROUTING_TABLE keywords from registry on first use."""
    global _ROUTING_KEYWORDS_LOADED
    if _ROUTING_KEYWORDS_LOADED:
        return
    kw_map = _load_routing_keywords()
    for rule in ROUTING_TABLE:
        domain_key = rule.domain.value
        if domain_key in kw_map and not rule.keywords:
            rule.keywords = kw_map[domain_key]
    _ROUTING_KEYWORDS_LOADED = True


# ── Engine Classes ──────────────────────────────────────────────

class FeedCollector:
    """Collects and deduplicates X feed items."""

    def __init__(self) -> None:
        self._posts: dict[str, XPost] = {}
        self._seen: set[str] = set()

    def ingest(self, post: XPost) -> dict[str, Any]:
        """Ingest a post, deduplicating by fingerprint."""
        if post.fingerprint in self._seen:
            return {"ingested": False, "reason": "duplicate", "fingerprint": post.fingerprint}
        self._seen.add(post.fingerprint)
        self._posts[post.post_id] = post
        return {"ingested": True, "post_id": post.post_id, "fingerprint": post.fingerprint}

    def get(self, post_id: str) -> XPost | None:
        return self._posts.get(post_id)

    def by_engagement(self, engagement_type: EngagementType) -> list[XPost]:
        return [p for p in self._posts.values() if p.engagement_type == engagement_type]

    @property
    def count(self) -> int:
        return len(self._posts)

    def engagement_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for post in self._posts.values():
            key = post.engagement_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def stats(self) -> dict[str, Any]:
        return {
            "total_posts": self.count,
            "unique_fingerprints": len(self._seen),
            "engagement_breakdown": self.engagement_counts(),
        }


class ContentClassifier:
    """Classifies posts by domain, urgency, and signal quality."""

    def __init__(self) -> None:
        self._classified: dict[str, ClassifiedPost] = {}
        self._routing_index: dict[ContentDomain, RoutingRule] = {
            rule.domain: rule for rule in ROUTING_TABLE
        }

    def classify(self, post: XPost) -> ClassifiedPost:
        """Classify a post and assign routing targets."""
        domain = self._detect_domain(post)
        urgency = self._assess_urgency(post)
        quality = self._assess_quality(post)
        rule = self._routing_index.get(domain, self._routing_index[ContentDomain.GENERAL])

        classified = ClassifiedPost(
            post=post,
            domain=domain,
            urgency=urgency,
            quality=quality,
            division=rule.division,
            pillar=rule.pillar,
            target_agents=list(rule.primary_agents),
            tags=list(post.hashtags),
            confidence=self._compute_confidence(post, domain),
            rationale=f"Domain={domain.value}, matched routing rule",
        )
        self._classified[post.post_id] = classified
        return classified

    def _detect_domain(self, post: XPost) -> ContentDomain:
        """Match post content against routing table keywords."""
        _ensure_routing_keywords()
        content_lower = post.content.lower()
        tags_lower = {h.lower() for h in post.hashtags}
        best_domain = ContentDomain.GENERAL
        best_score = 0

        for rule in ROUTING_TABLE:
            if not rule.keywords:
                continue
            score = 0
            for kw in rule.keywords:
                kw_lower = kw.lower()
                if kw_lower in content_lower:
                    score += 2
                if kw_lower in tags_lower:
                    score += 1
            if score > best_score:
                best_score = score
                best_domain = rule.domain
        return best_domain

    def _assess_urgency(self, post: XPost) -> UrgencyLevel:
        """Assess urgency based on engagement metrics and content signals."""
        content_lower = post.content.lower()
        flash_words = {"breaking", "urgent", "critical", "emergency", "alert"}
        if any(w in content_lower for w in flash_words):
            return UrgencyLevel.FLASH

        total_engagement = post.like_count + post.repost_count + post.reply_count
        if total_engagement > 10000 or post.view_count > 1000000:
            return UrgencyLevel.HIGH
        if total_engagement > 1000 or post.view_count > 100000:
            return UrgencyLevel.MEDIUM
        if total_engagement > 100:
            return UrgencyLevel.LOW
        return UrgencyLevel.ARCHIVE

    def _assess_quality(self, post: XPost) -> SignalQuality:
        """Score signal quality based on content length, engagement, and structure."""
        score = 0
        if len(post.content) > 200:
            score += 1
        if post.hashtags:
            score += 1
        if post.like_count > 500:
            score += 1
        if post.repost_count > 100:
            score += 1
        if post.mentions:
            score += 1

        if score >= 4:
            return SignalQuality.VERIFIED
        if score >= 3:
            return SignalQuality.STRONG
        if score >= 2:
            return SignalQuality.MODERATE
        if score >= 1:
            return SignalQuality.WEAK
        return SignalQuality.NOISE

    def _compute_confidence(self, post: XPost, domain: ContentDomain) -> float:
        """Compute classification confidence 0.0-1.0."""
        if domain == ContentDomain.GENERAL:
            return 0.3
        content_lower = post.content.lower()
        rule = self._routing_index.get(domain)
        if not rule or not rule.keywords:
            return 0.4
        matches = sum(1 for kw in rule.keywords if kw.lower() in content_lower)
        return min(1.0, round(0.4 + (matches * 0.1), 2))

    def domain_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cp in self._classified.values():
            key = cp.domain.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def urgency_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cp in self._classified.values():
            key = cp.urgency.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def stats(self) -> dict[str, Any]:
        return {
            "total_classified": len(self._classified),
            "domain_breakdown": self.domain_counts(),
            "urgency_breakdown": self.urgency_counts(),
        }


class ContentFilter:
    """Filters posts by quality threshold, skipping noise."""

    def __init__(self, min_quality: SignalQuality = SignalQuality.WEAK) -> None:
        self._min_quality = min_quality
        self._quality_rank = {
            SignalQuality.NOISE: 0,
            SignalQuality.WEAK: 1,
            SignalQuality.MODERATE: 2,
            SignalQuality.STRONG: 3,
            SignalQuality.VERIFIED: 4,
        }
        self._passed: list[ClassifiedPost] = []
        self._filtered: list[ClassifiedPost] = []

    def apply(self, classified: ClassifiedPost) -> bool:
        """Return True if post passes the quality filter."""
        rank = self._quality_rank.get(classified.quality, 0)
        threshold = self._quality_rank.get(self._min_quality, 1)
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
            "min_quality": self._min_quality.value,
        }


class AgentRouter:
    """Routes classified posts to target agents based on routing rules."""

    def __init__(self) -> None:
        self._dispatches: list[AgentDispatch] = []
        self._agent_queue: dict[str, list[str]] = {}  # codename → [post_ids]

    def route(self, classified: ClassifiedPost) -> AgentDispatch:
        """Create a dispatch record routing this post to target agents."""
        dispatch = AgentDispatch(
            dispatch_id=f"XD-{uuid.uuid4().hex[:8]}",
            agent_codename=classified.target_agents[0] if classified.target_agents else "mc",
            agent_callsign=self._resolve_callsign(
                classified.target_agents[0] if classified.target_agents else "mc"
            ),
            post_ids=[classified.post.post_id],
            domain=classified.domain,
            urgency=classified.urgency,
            division=classified.division,
            pillar=classified.pillar,
        )
        self._dispatches.append(dispatch)

        # Queue for each target agent
        for codename in classified.target_agents:
            if codename not in self._agent_queue:
                self._agent_queue[codename] = []
            self._agent_queue[codename].append(classified.post.post_id)

        return dispatch

    def _resolve_callsign(self, codename: str) -> str:
        """Resolve agent codename to canonical callsign."""
        return _CANONICAL_CALLSIGN_MAP.get(codename, codename.upper())

    def queue_for(self, agent_codename: str) -> list[str]:
        """Get queued post IDs for an agent."""
        return self._agent_queue.get(agent_codename, [])

    def division_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self._dispatches:
            key = d.division.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def pillar_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self._dispatches:
            key = d.pillar.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def stats(self) -> dict[str, Any]:
        return {
            "total_dispatches": len(self._dispatches),
            "agents_with_queue": len(self._agent_queue),
            "division_breakdown": self.division_counts(),
            "pillar_breakdown": self.pillar_counts(),
        }


class DigestGenerator:
    """Generates summary digests from processed feed batches."""

    def generate(
        self,
        collector: FeedCollector,
        classifier: ContentClassifier,
        content_filter: ContentFilter,
        router: AgentRouter,
    ) -> FeedDigest:
        """Build a feed digest from the current processing state."""
        return FeedDigest(
            digest_id=f"XFD-{uuid.uuid4().hex[:8]}",
            date=time.strftime("%Y-%m-%d"),
            total_processed=collector.count,
            by_engagement=collector.engagement_counts(),
            by_domain=classifier.domain_counts(),
            by_urgency=classifier.urgency_counts(),
            by_division=router.division_counts(),
            by_pillar=router.pillar_counts(),
            top_posts=[],
            routed_count=router.stats()["total_dispatches"],
            filtered_count=content_filter.filtered_count,
            quality_distribution={},
            confidence=0.85,
        )


# ── Unified Engine ──────────────────────────────────────────────

class XIntelligenceEngine:
    """Unified X intelligence pipeline.

    Workflow: Ingest → Classify → Filter → Route → Digest
    """

    def __init__(self, min_quality: SignalQuality = SignalQuality.WEAK) -> None:
        self.collector = FeedCollector()
        self.classifier = ContentClassifier()
        self.content_filter = ContentFilter(min_quality)
        self.router = AgentRouter()
        self.digest_gen = DigestGenerator()

    def ingest_post(self, post: XPost) -> dict[str, Any]:
        """Ingest a single post into the pipeline."""
        result = self.collector.ingest(post)
        if not result["ingested"]:
            return result
        return {**result, "status": "ingested"}

    def classify_post(self, post: XPost) -> dict[str, Any]:
        """Classify a post and return its routing assignment."""
        classified = self.classifier.classify(post)
        return {
            "status": "classified",
            "post_id": post.post_id,
            "domain": classified.domain.value,
            "urgency": classified.urgency.value,
            "quality": classified.quality.value,
            "division": classified.division.value,
            "pillar": classified.pillar.value,
            "target_agents": classified.target_agents,
            "confidence": classified.confidence,
        }

    def filter_post(self, classified: ClassifiedPost) -> dict[str, Any]:
        """Apply quality filter to a classified post."""
        passed = self.content_filter.apply(classified)
        return {
            "status": "filtered",
            "post_id": classified.post.post_id,
            "passed": passed,
            "quality": classified.quality.value,
        }

    def route_post(self, classified: ClassifiedPost) -> dict[str, Any]:
        """Route a classified post to target agents."""
        dispatch = self.router.route(classified)
        return {
            "status": "routed",
            "dispatch_id": dispatch.dispatch_id,
            "agent_codename": dispatch.agent_codename,
            "agent_callsign": dispatch.agent_callsign,
            "division": dispatch.division.value,
            "pillar": dispatch.pillar.value,
            "post_ids": dispatch.post_ids,
        }

    def full_pipeline(self, post: XPost) -> dict[str, Any]:
        """Run the complete pipeline: ingest → classify → filter → route."""
        ingest_result = self.ingest_post(post)
        if not ingest_result.get("ingested", False):
            return {**ingest_result, "status": "duplicate_skipped"}

        classified = self.classifier.classify(post)
        passed = self.content_filter.apply(classified)

        if not passed:
            return {
                "status": "filtered_out",
                "post_id": post.post_id,
                "domain": classified.domain.value,
                "quality": classified.quality.value,
                "reason": "below_quality_threshold",
            }

        dispatch = self.router.route(classified)
        return {
            "status": "routed",
            "post_id": post.post_id,
            "domain": classified.domain.value,
            "urgency": classified.urgency.value,
            "quality": classified.quality.value,
            "division": classified.division.value,
            "pillar": classified.pillar.value,
            "target_agents": classified.target_agents,
            "dispatch_id": dispatch.dispatch_id,
            "confidence": classified.confidence,
        }

    def generate_digest(self) -> dict[str, Any]:
        """Generate a feed digest from all processed data."""
        digest = self.digest_gen.generate(
            self.collector, self.classifier, self.content_filter, self.router,
        )
        return {
            "status": "digest_generated",
            "digest_id": digest.digest_id,
            "date": digest.date,
            "total_processed": digest.total_processed,
            "routed_count": digest.routed_count,
            "filtered_count": digest.filtered_count,
            "by_domain": digest.by_domain,
            "by_division": digest.by_division,
            "by_pillar": digest.by_pillar,
        }

    def agent_queue(self, codename: str) -> dict[str, Any]:
        """Get queued items for a specific agent."""
        queue = self.router.queue_for(codename)
        return {
            "status": "queue_retrieved",
            "agent_codename": codename,
            "queued_posts": len(queue),
            "post_ids": queue,
        }

    def routing_summary(self) -> dict[str, Any]:
        """Summary of all routing decisions."""
        return {
            "status": "routing_summary",
            "collector": self.collector.stats(),
            "classifier": self.classifier.stats(),
            "filter": self.content_filter.stats(),
            "router": self.router.stats(),
        }

    def operational_readiness(self) -> dict[str, Any]:
        """Check if the X intelligence engine is operational."""
        return {
            "ready": True,
            "engines": [
                "FeedCollector",
                "ContentClassifier",
                "ContentFilter",
                "AgentRouter",
                "DigestGenerator",
            ],
            "routing_rules": len(ROUTING_TABLE),
            "domains": len(ContentDomain),
            "divisions": len(RoutingDivision),
            "pillars": len(PillarTarget),
            "engagement_types": len(EngagementType),
        }


# ── RSS Feed Scraper ────────────────────────────────────────────

_logger = logging.getLogger(__name__)
_FPC_ROOT = Path(__file__).resolve().parent.parent


class XFeedScraper:
    """Collect X/Twitter posts via public RSS proxy endpoints.

    Uses nitter-style RSS feeds or any RSS proxy that mirrors
    X timelines. Falls back to curated RSS search feeds.
    No API key required.
    """

    # Curated high-signal accounts to monitor
    TRACKED_ACCOUNTS: ClassVar[list[str]] = [
        "elonmusk", "sama", "AndrewYNg", "ylecun",
        "kabore", "lexfridman", "naval", "balaboronline",
        "peterthiel", "chaaboroughgh",
    ]

    # Public nitter instances (rotate if one goes down)
    NITTER_INSTANCES: ClassVar[list[str]] = [
        "nitter.net",
        "nitter.unixfox.eu",
    ]

    def __init__(self, accounts: list[str] | None = None,
                 cache_dir: Path | None = None) -> None:
        self._accounts = accounts or self.TRACKED_ACCOUNTS
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "x_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._engine = XIntelligenceEngine()
        self._last_request: float = 0.0
        self._rate_limit_s: float = 5.0

    def collect_and_process(self) -> dict[str, Any]:
        """Scrape tracked accounts and run through full pipeline."""
        total_ingested = 0
        for account in self._accounts:
            posts = self._fetch_account_rss(account)
            for post in posts:
                result = self._engine.full_pipeline(post)
                if result.get("status") == "routed":
                    total_ingested += 1

        digest = self._engine.generate_digest()
        self._cache_digest(digest)
        return {
            "total_scraped": total_ingested,
            "digest": digest,
            "routing": self._engine.routing_summary(),
        }

    def _fetch_account_rss(self, account: str) -> list[XPost]:
        """Try nitter RSS feeds for a given account."""
        posts: list[XPost] = []
        for instance in self.NITTER_INSTANCES:
            url = f"https://{instance}/{account}/rss"
            try:
                self._rate_limit()
                req = urllib.request.Request(
                    url, headers={"User-Agent": "NCL-FPC/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    xml_data = resp.read()
                    root = ElementTree.fromstring(xml_data)

                    for item in root.iter("item"):
                        title_el = item.find("title")
                        link_el = item.find("link")
                        desc_el = item.find("description")
                        pub_date_el = item.find("pubDate")

                        content = ""
                        if desc_el is not None and desc_el.text:
                            content = desc_el.text[:500]
                        elif title_el is not None and title_el.text:
                            content = title_el.text

                        link = link_el.text if link_el is not None and link_el.text else ""

                        posts.append(XPost(
                            post_id=hashlib.sha256(link.encode()).hexdigest()[:16],
                            author_handle=account,
                            author_name=account,
                            content=content,
                            engagement_type=EngagementType.ORIGINAL,
                            timestamp=pub_date_el.text if pub_date_el is not None and pub_date_el.text else "",
                            url=link,
                        ))
                    break  # Success — stop trying other instances
            except Exception as exc:
                _logger.debug("Nitter %s/%s failed: %s", instance, account, exc)
                continue

        return posts[:10]

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: dict[str, Any]) -> None:
        cache_file = self._cache_dir / f"x_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            cache_file.write_text(
                json.dumps(digest, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            _logger.warning("Failed to cache X digest: %s", exc)
