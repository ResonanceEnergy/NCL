"""AI Upload Intelligence Engine — Strategic AI News & Analysis Pipeline.

Ingests YouTube video metadata from the AI Upload channel (and similar
AI-news channels), classifies content by strategic type (model releases,
company news, safety discussions, geopolitical shifts, AGI progress),
extracts named entities (companies, models, researchers, institutions),
detects strategic signals, tracks evolving narratives, and routes
intelligence to the appropriate NCL agent, division, and NCC Triad pillar.

Complementary to the TIAIFT tool-discovery pipeline:
  - TIAIFT (youtube_intelligence.py) = "Which AI tools exist and what do they do?"
  - AI Upload (this module) = "What is happening in AI and what does it mean?"
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from .youtube_intelligence import (
    PillarMapping,
    RoutingTarget,
    VideoEntry,
)

# ── Enums ───────────────────────────────────────────────────────


class ContentType(StrEnum):
    """AI Upload content classification taxonomy."""

    MODEL_RELEASE = "model_release"          # New model launch, benchmarks, demos
    COMPANY_NEWS = "company_news"            # Funding, acquisitions, leadership changes
    RESEARCH_PAPER = "research_paper"        # Papers, breakthroughs, novel techniques
    SAFETY_ALIGNMENT = "safety_alignment"    # AI safety, alignment, existential risk
    AGI_PROGRESS = "agi_progress"            # AGI timelines, milestones, debates
    MARKET_ANALYSIS = "market_analysis"      # Valuations, market size, competition
    GEOPOLITICAL = "geopolitical"            # US-China, EU AI Act, sovereignty
    EXPERT_OPINION = "expert_opinion"        # Interviews, predictions, thought leaders
    INDUSTRY_TREND = "industry_trend"        # Broader patterns, adoption curves
    REGULATION = "regulation"               # Laws, governance, policy, compliance


class EntityType(StrEnum):
    """Named entity types in AI news coverage."""

    COMPANY = "company"                # OpenAI, Anthropic, Google, Meta
    AI_MODEL = "ai_model"              # GPT-5, Claude 4, Gemini Ultra
    RESEARCHER = "researcher"          # Sam Altman, Dario Amodei, etc.
    INSTITUTION = "institution"        # MIT, Stanford, MIRI, NIST
    REGULATION_ENTITY = "regulation"   # EU AI Act, Executive Order


class SignalType(StrEnum):
    """Strategic intelligence signal types."""

    CAPABILITY_LEAP = "capability_leap"        # New AI capability threshold
    COMPETITIVE_SHIFT = "competitive_shift"    # Market/landscape change
    RISK_ALERT = "risk_alert"                  # Safety/alignment concern
    INVESTMENT_SIGNAL = "investment_signal"     # Funding/commercial opportunity
    REGULATORY_CHANGE = "regulatory_change"    # Policy/legal/governance shift
    TALENT_MOVEMENT = "talent_movement"        # Key hire/departure
    PARTNERSHIP = "partnership"                # Strategic alliance/merger
    PARADIGM_INDICATOR = "paradigm_indicator"  # Evidence toward AGI/paradigm shift


class UrgencyLevel(StrEnum):
    """How urgently this intelligence needs routing."""

    FLASH = "flash"            # Immediate executive attention
    PRIORITY = "priority"      # Same-day routing required
    STANDARD = "standard"      # Normal processing cadence
    ARCHIVE = "archive"        # Low urgency, store for reference


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class EntityMention:
    """A named entity mentioned in AI Upload content."""

    name: str
    entity_type: EntityType
    is_primary: bool  # Primary subject vs passing mention
    context: str = ""  # Snippet of surrounding context


@dataclass
class StrategicSignal:
    """A distilled strategic signal for NCL decision-making."""

    signal_id: str
    signal_type: SignalType
    urgency: UrgencyLevel
    title: str
    summary: str
    entities: list[EntityMention]
    source_video_id: str
    confidence: float
    target_division: RoutingTarget
    target_pillar: PillarMapping
    target_agents: list[str]


@dataclass
class AnalyzedContent:
    """A video after content analysis and entity extraction."""

    video: VideoEntry
    content_type: ContentType
    entities: list[EntityMention]
    signals: list[StrategicSignal]
    urgency: UrgencyLevel
    confidence: float
    keywords_matched: list[str] = field(default_factory=list)


@dataclass
class ContentSignalRule:
    """Routing rule for a content type."""

    content_type: ContentType
    division: RoutingTarget
    pillar: PillarMapping
    primary_agents: list[str]
    signal_types: list[SignalType]
    keywords: list[str]


@dataclass
class IntelligenceBrief:
    """Summary intelligence brief from AI Upload analysis."""

    total_analyzed: int
    total_signals: int
    flash_signals: int
    priority_signals: int
    content_breakdown: dict[str, int]
    signal_breakdown: dict[str, int]
    top_entities: list[str]
    active_narratives: int
    generated_at: float


@dataclass
class NarrativeThread:
    """An evolving narrative tracked across multiple videos."""

    thread_id: str
    title: str
    content_type: ContentType
    video_ids: list[str]
    entities: list[str]
    signal_count: int
    first_seen: float
    last_updated: float


# ── Routing Table ───────────────────────────────────────────────

CONTENT_SIGNAL_ROUTING: list[ContentSignalRule] = [
    ContentSignalRule(
        content_type=ContentType.MODEL_RELEASE,
        division=RoutingTarget.RESEARCH,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["ai", "wp"],  # BEACON + WOLFRAM
        signal_types=[SignalType.CAPABILITY_LEAP, SignalType.COMPETITIVE_SHIFT],
        keywords=["released", "launched", "benchmark", "state of the art",
                  "new model", "demo", "gpt", "claude", "gemini", "llama",
                  "o1", "o3", "sonnet", "opus", "haiku"],
    ),
    ContentSignalRule(
        content_type=ContentType.COMPANY_NEWS,
        division=RoutingTarget.STRATEGY,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["sa", "ab"],  # NEXUS + VAULT
        signal_types=[SignalType.COMPETITIVE_SHIFT, SignalType.INVESTMENT_SIGNAL],
        keywords=["openai", "anthropic", "google", "meta", "microsoft",
                  "nvidia", "raised", "acquired", "valued", "funding",
                  "ipo", "ceo", "layoff", "restructure"],
    ),
    ContentSignalRule(
        content_type=ContentType.RESEARCH_PAPER,
        division=RoutingTarget.RESEARCH,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["sb", "ai"],  # CORTEX + BEACON
        signal_types=[SignalType.CAPABILITY_LEAP, SignalType.PARADIGM_INDICATOR],
        keywords=["paper", "research", "arxiv", "breakthrough", "novel",
                  "technique", "architecture", "transformer", "attention",
                  "training", "scaling", "emergent"],
    ),
    ContentSignalRule(
        content_type=ContentType.SAFETY_ALIGNMENT,
        division=RoutingTarget.INTELLIGENCE,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["nc", "sg"],  # SENTINEL + CIPHER
        signal_types=[SignalType.RISK_ALERT, SignalType.PARADIGM_INDICATOR],
        keywords=["safety", "alignment", "existential", "risk", "guardrails",
                  "jailbreak", "red team", "responsible", "ethics",
                  "superintelligence", "control", "containment"],
    ),
    ContentSignalRule(
        content_type=ContentType.AGI_PROGRESS,
        division=RoutingTarget.STRATEGY,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["wp", "sa"],  # WOLFRAM + NEXUS
        signal_types=[SignalType.PARADIGM_INDICATOR, SignalType.CAPABILITY_LEAP],
        keywords=["agi", "artificial general intelligence", "human-level",
                  "singularity", "consciousness", "reasoning", "planning",
                  "self-improvement", "recursive", "milestone"],
    ),
    ContentSignalRule(
        content_type=ContentType.MARKET_ANALYSIS,
        division=RoutingTarget.FINANCE,
        pillar=PillarMapping.AAC_BANK,
        primary_agents=["ab", "fo"],  # VAULT + BEHEMOTH
        signal_types=[SignalType.INVESTMENT_SIGNAL, SignalType.COMPETITIVE_SHIFT],
        keywords=["market", "valuation", "billion", "trillion", "revenue",
                  "stock", "growth", "market share", "competition",
                  "disruption", "adoption", "enterprise"],
    ),
    ContentSignalRule(
        content_type=ContentType.GEOPOLITICAL,
        division=RoutingTarget.INTELLIGENCE,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["jx", "nc"],  # MANDARIN + SENTINEL
        signal_types=[SignalType.COMPETITIVE_SHIFT, SignalType.REGULATORY_CHANGE],
        keywords=["china", "us", "europe", "sovereignty", "chip",
                  "export control", "geopolitical", "arms race",
                  "national security", "ai race", "sanctions"],
    ),
    ContentSignalRule(
        content_type=ContentType.EXPERT_OPINION,
        division=RoutingTarget.KNOWLEDGE,
        pillar=PillarMapping.NCL_BRAIN,
        primary_agents=["sb", "ai"],  # CORTEX + BEACON
        signal_types=[SignalType.PARADIGM_INDICATOR],
        keywords=["interview", "prediction", "opinion", "thinks",
                  "believes", "expert", "insider", "former",
                  "keynote", "podcast", "debate"],
    ),
    ContentSignalRule(
        content_type=ContentType.INDUSTRY_TREND,
        division=RoutingTarget.INNOVATION,
        pillar=PillarMapping.BIT_RAGE_SYSTEMS,
        primary_agents=["ai", "ne"],  # BEACON + ORACLE
        signal_types=[SignalType.COMPETITIVE_SHIFT, SignalType.PARADIGM_INDICATOR],
        keywords=["trend", "shift", "movement", "adoption", "wave",
                  "future", "next", "emerging", "paradigm",
                  "disrupting", "replacing", "automating"],
    ),
    ContentSignalRule(
        content_type=ContentType.REGULATION,
        division=RoutingTarget.INTELLIGENCE,
        pillar=PillarMapping.NCC_COMMAND,
        primary_agents=["nc", "sg"],  # SENTINEL + CIPHER
        signal_types=[SignalType.REGULATORY_CHANGE, SignalType.RISK_ALERT],
        keywords=["regulation", "law", "act", "policy", "compliance",
                  "ban", "restrict", "mandate", "governance",
                  "executive order", "legislation", "framework"],
    ),
]


# ── Engine Classes ──────────────────────────────────────────────


class EntityExtractor:
    """Extracts named entities (companies, models, researchers) from video content."""

    KNOWN_COMPANIES: ClassVar[dict[str, str]] = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "deepmind": "DeepMind",
        "meta": "Meta",
        "microsoft": "Microsoft",
        "nvidia": "NVIDIA",
        "apple": "Apple",
        "amazon": "Amazon",
        "xai": "xAI",
        "mistral ai": "Mistral AI",
        "stability ai": "Stability AI",
        "cohere": "Cohere",
        "inflection": "Inflection AI",
        "hugging face": "Hugging Face",
        "character.ai": "Character.AI",
        "perplexity": "Perplexity AI",
        "midjourney": "Midjourney Inc.",
        "runway": "Runway",
        "eleven labs": "ElevenLabs",
        "adobe": "Adobe",
        "salesforce": "Salesforce",
        "databricks": "Databricks",
        "scale ai": "Scale AI",
    }

    KNOWN_MODELS: ClassVar[dict[str, str]] = {
        "gpt-4": "GPT-4",
        "gpt-4o": "GPT-4o",
        "gpt-5": "GPT-5",
        "o1": "o1",
        "o3": "o3",
        "claude": "Claude",
        "claude 3": "Claude 3",
        "claude 4": "Claude 4",
        "sonnet": "Sonnet",
        "opus": "Opus",
        "haiku": "Haiku",
        "gemini": "Gemini",
        "gemini ultra": "Gemini Ultra",
        "gemini 2": "Gemini 2",
        "llama": "Llama",
        "llama 4": "Llama 4",
        "mistral": "Mistral",
        "phi": "Phi",
        "falcon": "Falcon",
        "sora": "Sora",
        "dall-e": "DALL-E",
        "stable diffusion": "Stable Diffusion",
        "midjourney": "Midjourney",
        "copilot": "Copilot",
        "devin": "Devin",
    }

    KNOWN_RESEARCHERS: ClassVar[dict[str, str]] = {
        "sam altman": "Sam Altman",
        "dario amodei": "Dario Amodei",
        "demis hassabis": "Demis Hassabis",
        "yann lecun": "Yann LeCun",
        "ilya sutskever": "Ilya Sutskever",
        "jensen huang": "Jensen Huang",
        "satya nadella": "Satya Nadella",
        "mark zuckerberg": "Mark Zuckerberg",
        "elon musk": "Elon Musk",
        "sundar pichai": "Sundar Pichai",
        "andrej karpathy": "Andrej Karpathy",
        "geoffrey hinton": "Geoffrey Hinton",
        "yoshua bengio": "Yoshua Bengio",
        "fei-fei li": "Fei-Fei Li",
    }

    def extract(self, video: VideoEntry) -> list[EntityMention]:
        """Extract named entities from video title, description, and tags."""
        searchable = " ".join([
            video.title.lower(),
            video.description.lower(),
            " ".join(video.tags).lower(),
            video.transcript_snippet.lower(),
        ])

        entities: list[EntityMention] = []
        found: set[str] = set()

        for key, display in self.KNOWN_COMPANIES.items():
            if key in searchable and key not in found:
                found.add(key)
                entities.append(EntityMention(
                    name=display,
                    entity_type=EntityType.COMPANY,
                    is_primary=key in video.title.lower(),
                ))

        for key, display in self.KNOWN_MODELS.items():
            if key in searchable and key not in found:
                found.add(key)
                entities.append(EntityMention(
                    name=display,
                    entity_type=EntityType.AI_MODEL,
                    is_primary=key in video.title.lower(),
                ))

        for key, display in self.KNOWN_RESEARCHERS.items():
            if key in searchable and key not in found:
                found.add(key)
                entities.append(EntityMention(
                    name=display,
                    entity_type=EntityType.RESEARCHER,
                    is_primary=key in video.title.lower(),
                ))

        return entities


class ContentAnalyzer:
    """Classifies AI Upload video content by strategic content type."""

    def __init__(self) -> None:
        self._routing_index: dict[ContentType, ContentSignalRule] = {
            r.content_type: r for r in CONTENT_SIGNAL_ROUTING
        }
        self._analyzed: list[AnalyzedContent] = []

    def analyze(self, video: VideoEntry, entities: list[EntityMention]) -> ContentType:
        """Determine the primary content type from video metadata and entities."""
        searchable = f"{video.title} {video.description}".lower()
        best_score = 0
        best_type = ContentType.INDUSTRY_TREND  # Default

        for rule in CONTENT_SIGNAL_ROUTING:
            score = sum(1 for kw in rule.keywords if kw in searchable)
            # Bonus for entity alignment
            if rule.content_type == ContentType.COMPANY_NEWS:
                score += sum(1 for e in entities if e.entity_type == EntityType.COMPANY and e.is_primary)
            elif rule.content_type == ContentType.MODEL_RELEASE:
                score += sum(1 for e in entities if e.entity_type == EntityType.AI_MODEL and e.is_primary)
            elif rule.content_type == ContentType.EXPERT_OPINION:
                score += sum(1 for e in entities if e.entity_type == EntityType.RESEARCHER and e.is_primary)

            if score > best_score:
                best_score = score
                best_type = rule.content_type

        return best_type

    def content_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ac in self._analyzed:
            key = ac.content_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts


class SignalDetector:
    """Detects strategic signals from analyzed content."""

    def __init__(self) -> None:
        self._routing_index: dict[ContentType, ContentSignalRule] = {
            r.content_type: r for r in CONTENT_SIGNAL_ROUTING
        }
        self._signals: list[StrategicSignal] = []

    def detect(
        self, video: VideoEntry, content_type: ContentType,
        entities: list[EntityMention],
    ) -> list[StrategicSignal]:
        """Detect strategic signals from a classified video."""
        rule = self._routing_index.get(content_type)
        if not rule:
            return []

        urgency = self._assess_urgency(video, content_type, entities)
        confidence = self._compute_confidence(video, rule)
        signals: list[StrategicSignal] = []

        for signal_type in rule.signal_types:
            sig_id = hashlib.sha256(
                f"{video.video_id}:{signal_type.value}".encode(),
            ).hexdigest()[:12]

            signals.append(StrategicSignal(
                signal_id=f"au-{sig_id}",
                signal_type=signal_type,
                urgency=urgency,
                title=video.title,
                summary=video.description[:200] if video.description else "",
                entities=entities,
                source_video_id=video.video_id,
                confidence=confidence,
                target_division=rule.division,
                target_pillar=rule.pillar,
                target_agents=rule.primary_agents,
            ))

        self._signals.extend(signals)
        return signals

    def _assess_urgency(
        self, video: VideoEntry, content_type: ContentType,
        entities: list[EntityMention],
    ) -> UrgencyLevel:
        """Assess urgency based on content type, engagement, and content signals."""
        score = 0

        # Engagement urgency
        if video.view_count > 500_000:
            score += 3
        elif video.view_count > 100_000:
            score += 2
        elif video.view_count > 10_000:
            score += 1

        # Content type urgency
        flash_types = {ContentType.SAFETY_ALIGNMENT, ContentType.AGI_PROGRESS}
        priority_types = {ContentType.MODEL_RELEASE, ContentType.REGULATION,
                         ContentType.GEOPOLITICAL}
        if content_type in flash_types:
            score += 3
        elif content_type in priority_types:
            score += 2

        # Keyword urgency
        title_lower = video.title.lower()
        flash_words = ["breaking", "urgent", "emergency", "just happened",
                       "agi achieved", "superintelligence"]
        priority_words = ["just released", "announced", "breaking news",
                          "exclusive", "leaked", "confirmed"]
        if any(w in title_lower for w in flash_words):
            score += 3
        elif any(w in title_lower for w in priority_words):
            score += 2

        # Primary entities boost urgency
        if any(e.is_primary for e in entities):
            score += 1

        if score >= 7:
            return UrgencyLevel.FLASH
        if score >= 4:
            return UrgencyLevel.PRIORITY
        if score >= 2:
            return UrgencyLevel.STANDARD
        return UrgencyLevel.ARCHIVE

    def _compute_confidence(self, video: VideoEntry, rule: ContentSignalRule) -> float:
        """Compute detection confidence 0.0-1.0."""
        searchable = f"{video.title} {video.description}".lower()
        if not rule.keywords:
            return 0.3
        matches = sum(1 for kw in rule.keywords if kw in searchable)
        return min(1.0, round(0.35 + (matches * 0.08), 2))

    @property
    def signal_count(self) -> int:
        return len(self._signals)

    def signal_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sig in self._signals:
            key = sig.signal_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts


class NarrativeTracker:
    """Tracks evolving narratives across multiple AI Upload videos."""

    def __init__(self) -> None:
        self._threads: dict[str, NarrativeThread] = {}
        self._entity_frequency: dict[str, int] = {}

    def track(self, analyzed: AnalyzedContent) -> str:
        """Track an analyzed video, binding it to a narrative thread.

        Returns the thread_id.
        """
        thread_key = self._find_thread_key(analyzed)
        now = time.time()

        if thread_key in self._threads:
            thread = self._threads[thread_key]
            thread.video_ids.append(analyzed.video.video_id)
            thread.signal_count += len(analyzed.signals)
            thread.last_updated = now
        else:
            self._threads[thread_key] = NarrativeThread(
                thread_id=thread_key,
                title=f"{analyzed.content_type.value}: {analyzed.video.title[:50]}",
                content_type=analyzed.content_type,
                video_ids=[analyzed.video.video_id],
                entities=[e.name for e in analyzed.entities if e.is_primary],
                signal_count=len(analyzed.signals),
                first_seen=now,
                last_updated=now,
            )

        # Track entity frequency
        for entity in analyzed.entities:
            self._entity_frequency[entity.name] = (
                self._entity_frequency.get(entity.name, 0) + 1
            )

        return thread_key

    def _find_thread_key(self, analyzed: AnalyzedContent) -> str:
        """Identify the narrative thread for this content."""
        primary_entities = [e.name for e in analyzed.entities if e.is_primary]
        key_parts = [analyzed.content_type.value]
        if primary_entities:
            key_parts.append(primary_entities[0].lower().replace(" ", "_"))
        raw = ":".join(key_parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:10]

    @property
    def active_threads(self) -> int:
        return len(self._threads)

    def top_entities(self, top_n: int = 10) -> list[tuple[str, int]]:
        """Return top-N most mentioned entities."""
        return sorted(
            self._entity_frequency.items(), key=lambda x: x[1], reverse=True,
        )[:top_n]

    def threads_list(self) -> list[dict[str, Any]]:
        return [
            {
                "thread_id": t.thread_id,
                "title": t.title,
                "content_type": t.content_type.value,
                "video_count": len(t.video_ids),
                "signal_count": t.signal_count,
            }
            for t in self._threads.values()
        ]

    def narrative_report(self) -> dict[str, Any]:
        return {
            "active_threads": self.active_threads,
            "top_entities": self.top_entities(5),
            "total_entities_tracked": len(self._entity_frequency),
            "threads": self.threads_list(),
        }


class StrategicRouter:
    """Routes strategic signals to target NCL agents."""

    CALLSIGN_MAP: ClassVar[dict[str, str]] = {
        "mc": "ATLAS", "ds": "SCRIBE", "be": "TEMPO", "ne": "ORACLE",
        "fo": "BEHEMOTH", "xe": "LANTERN", "cs": "RAVEN", "mo": "FORGE",
        "so": "FORGE", "dx": "PIXEL", "ir": "MINDGATE", "ss": "PHOENIX",
        "sp": "NAVIGATOR", "es": "SANCTUM", "em": "WATCHTOWER",
        "ux": "MUSE", "an": "COUNCILOR", "hr": "NIGHTFALL",
        "rt": "SPECTRE", "si": "BRIDGE", "wp": "WOLFRAM",
        "nc": "SENTINEL", "ab": "VAULT", "sa": "NEXUS",
        "sg": "CIPHER", "rd": "AEGIS", "jx": "MANDARIN",
        "sb": "CORTEX", "ai": "BEACON", "xf": "HERALD", "yt": "CATALYST",
    }

    def __init__(self) -> None:
        self._routed: list[dict[str, Any]] = []
        self._agent_queues: dict[str, list[str]] = {}

    def route(self, signal: StrategicSignal) -> dict[str, Any]:
        """Route a strategic signal to the target agent."""
        primary = signal.target_agents[0] if signal.target_agents else "sb"
        callsign = self.CALLSIGN_MAP.get(primary, primary.upper())
        dispatch = {
            "signal_id": signal.signal_id,
            "agent_codename": primary,
            "agent_callsign": callsign,
            "division": signal.target_division.value,
            "pillar": signal.target_pillar.value,
            "signal_type": signal.signal_type.value,
            "urgency": signal.urgency.value,
            "video_id": signal.source_video_id,
        }
        self._routed.append(dispatch)
        if primary not in self._agent_queues:
            self._agent_queues[primary] = []
        self._agent_queues[primary].append(signal.signal_id)
        return dispatch

    def agent_queue(self, codename: str) -> dict[str, Any]:
        queue = self._agent_queues.get(codename, [])
        return {
            "agent_codename": codename,
            "agent_callsign": self.CALLSIGN_MAP.get(codename, codename.upper()),
            "queued_signals": len(queue),
            "signal_ids": queue,
        }

    def routing_summary(self) -> dict[str, Any]:
        by_agent: dict[str, int] = {}
        by_urgency: dict[str, int] = {}
        for entry in self._routed:
            by_agent[entry["agent_codename"]] = by_agent.get(entry["agent_codename"], 0) + 1
            by_urgency[entry["urgency"]] = by_urgency.get(entry["urgency"], 0) + 1
        return {
            "total_routed": len(self._routed),
            "agents_targeted": len(by_agent),
            "by_agent": by_agent,
            "by_urgency": by_urgency,
        }


class BriefGenerator:
    """Generates strategic intelligence briefs."""

    def generate(
        self,
        analyzer: ContentAnalyzer,
        detector: SignalDetector,
        tracker: NarrativeTracker,
    ) -> IntelligenceBrief:
        flash_count = sum(
            1 for sig in detector._signals if sig.urgency == UrgencyLevel.FLASH
        )
        priority_count = sum(
            1 for sig in detector._signals if sig.urgency == UrgencyLevel.PRIORITY
        )
        return IntelligenceBrief(
            total_analyzed=len(analyzer._analyzed),
            total_signals=detector.signal_count,
            flash_signals=flash_count,
            priority_signals=priority_count,
            content_breakdown=analyzer.content_counts(),
            signal_breakdown=detector.signal_breakdown(),
            top_entities=[e[0] for e in tracker.top_entities(5)],
            active_narratives=tracker.active_threads,
            generated_at=time.time(),
        )


# ── Unified Engine ──────────────────────────────────────────────


class AIUploadEngine:
    """Unified engine: analyze → extract entities → detect signals → track → route."""

    def __init__(self) -> None:
        self.entity_extractor = EntityExtractor()
        self.content_analyzer = ContentAnalyzer()
        self.signal_detector = SignalDetector()
        self.narrative_tracker = NarrativeTracker()
        self.strategic_router = StrategicRouter()
        self.brief_gen = BriefGenerator()
        self._seen: set[str] = set()

    def analyze_video(self, video: VideoEntry) -> dict[str, Any]:
        """Analyze a video for content type and entities."""
        entities = self.entity_extractor.extract(video)
        content_type = self.content_analyzer.analyze(video, entities)
        return {
            "status": "analyzed",
            "video_id": video.video_id,
            "content_type": content_type.value,
            "entities_found": len(entities),
            "entities": [{"name": e.name, "type": e.entity_type.value,
                         "primary": e.is_primary} for e in entities],
        }

    def detect_signals(self, video: VideoEntry) -> dict[str, Any]:
        """Extract entities, analyze content, and detect strategic signals."""
        entities = self.entity_extractor.extract(video)
        content_type = self.content_analyzer.analyze(video, entities)
        signals = self.signal_detector.detect(video, content_type, entities)
        return {
            "status": "signals_detected",
            "video_id": video.video_id,
            "content_type": content_type.value,
            "signals_found": len(signals),
            "signals": [{"id": s.signal_id, "type": s.signal_type.value,
                        "urgency": s.urgency.value} for s in signals],
        }

    def full_pipeline(self, video: VideoEntry) -> dict[str, Any]:
        """Run the complete pipeline: deduplicate → analyze → signal → track → route."""
        fp = hashlib.sha256(
            f"{video.video_id}:{video.channel_name}:{video.title[:60]}".encode(),
        ).hexdigest()[:16]
        if fp in self._seen:
            return {"status": "duplicate_skipped", "video_id": video.video_id}
        self._seen.add(fp)

        entities = self.entity_extractor.extract(video)
        content_type = self.content_analyzer.analyze(video, entities)
        signals = self.signal_detector.detect(video, content_type, entities)

        analyzed = AnalyzedContent(
            video=video,
            content_type=content_type,
            entities=entities,
            signals=signals,
            urgency=signals[0].urgency if signals else UrgencyLevel.ARCHIVE,
            confidence=signals[0].confidence if signals else 0.3,
        )
        self.content_analyzer._analyzed.append(analyzed)
        thread_id = self.narrative_tracker.track(analyzed)

        # Route all signals
        dispatches = []
        for sig in signals:
            dispatch = self.strategic_router.route(sig)
            dispatches.append(dispatch)

        return {
            "status": "routed",
            "video_id": video.video_id,
            "content_type": content_type.value,
            "entities_found": len(entities),
            "signals_found": len(signals),
            "urgency": analyzed.urgency.value,
            "confidence": analyzed.confidence,
            "thread_id": thread_id,
            "dispatches": len(dispatches),
            "target_agents": list({d["agent_codename"] for d in dispatches}),
        }

    def generate_brief(self) -> dict[str, Any]:
        """Generate an intelligence brief."""
        brief = self.brief_gen.generate(
            self.content_analyzer, self.signal_detector, self.narrative_tracker,
        )
        return {
            "status": "brief_generated",
            "total_analyzed": brief.total_analyzed,
            "total_signals": brief.total_signals,
            "flash_signals": brief.flash_signals,
            "priority_signals": brief.priority_signals,
            "content_breakdown": brief.content_breakdown,
            "signal_breakdown": brief.signal_breakdown,
            "top_entities": brief.top_entities,
            "active_narratives": brief.active_narratives,
            "generated_at": brief.generated_at,
        }

    def narrative_report(self) -> dict[str, Any]:
        """Get current narrative tracking report."""
        return self.narrative_tracker.narrative_report()

    def routing_summary(self) -> dict[str, Any]:
        """Get signal routing summary."""
        return self.strategic_router.routing_summary()

    def agent_queue(self, codename: str) -> dict[str, Any]:
        """Get the signal queue for a specific agent."""
        return self.strategic_router.agent_queue(codename)

    def operational_readiness(self) -> dict[str, Any]:
        """Report operational readiness."""
        return {
            "ready": True,
            "engine": "AIUploadEngine",
            "channel": "AI Upload",
            "content_types": len(ContentType),
            "entity_types": len(EntityType),
            "signal_types": len(SignalType),
            "urgency_levels": len(UrgencyLevel),
            "routing_rules": len(CONTENT_SIGNAL_ROUTING),
            "known_companies": len(EntityExtractor.KNOWN_COMPANIES),
            "known_models": len(EntityExtractor.KNOWN_MODELS),
            "known_researchers": len(EntityExtractor.KNOWN_RESEARCHERS),
            "divisions": len(RoutingTarget),
            "pillars": len(PillarMapping),
        }
