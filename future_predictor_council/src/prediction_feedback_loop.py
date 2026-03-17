"""Prediction Feedback Loop — Unified Signal Aggregation & Council Integration.

This is the CORE engine that:
1. Aggregates signals from ALL platform intelligence scrapers
2. Feeds unified signals to the FuturePredictorCouncil
3. Records predictions and tracks accuracy over time
4. Bidirectional loop: predictions inform scraper priorities,
   new signals refine predictions

Implements the continuous learning cycle:
   Collect → Aggregate → Predict → Verify → Learn → Adjust → Repeat
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

_FPC_ROOT = Path(__file__).resolve().parent.parent


# ── Enums ───────────────────────────────────────────────────────


class Platform(StrEnum):
    GITHUB = "github"
    X_TWITTER = "x_twitter"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    SUBSTACK = "substack"
    GOOGLE_TRENDS = "google_trends"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    DISCORD = "discord"


class SignalStrength(StrEnum):
    NOISE = "noise"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    OVERWHELMING = "overwhelming"


class TrendPhase(StrEnum):
    SEED = "seed"           # Just appearing (1 platform)
    EMERGING = "emerging"   # Appearing on 2-3 platforms
    RISING = "rising"       # 4-5 platforms, growing volume
    PEAKING = "peaking"     # Most platforms, high volume
    DECLINING = "declining"  # Volume dropping
    SATURATED = "saturated"  # Everywhere, no novelty left


class PredictionOutcome(StrEnum):
    PENDING = "pending"
    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"
    EXPIRED = "expired"


class DomainCategory(StrEnum):
    AI_TECHNOLOGY = "ai_technology"
    FINANCE = "finance"
    GEOPOLITICS = "geopolitics"
    SCIENCE = "science"
    CULTURE = "culture"
    ENERGY = "energy"
    HEALTH = "health"
    SECURITY = "security"
    ENTREPRENEURSHIP = "entrepreneurship"
    GENERAL = "general"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class UnifiedSignal:
    """A signal normalized across all platforms."""

    signal_id: str
    platform: Platform
    domain: DomainCategory
    title: str
    summary: str
    strength: SignalStrength
    source_url: str = ""
    collected_at: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.platform}:{self.title[:60]}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.collected_at:
            self.collected_at = datetime.now(UTC).isoformat()


@dataclass
class TrendCluster:
    """A cluster of related signals across platforms — a detected trend."""

    cluster_id: str
    topic: str
    domain: DomainCategory
    phase: TrendPhase
    platforms: list[Platform]
    signal_count: int
    signals: list[str]  # signal fingerprints
    first_seen: str = ""
    last_seen: str = ""
    velocity: float = 0.0  # signals per hour
    cross_platform_score: float = 0.0  # 0-1, higher = more platforms
    prediction_id: str = ""  # Link to generated prediction


@dataclass
class PredictionRecord:
    """A prediction made by the council, tracked for accuracy."""

    prediction_id: str
    topic: str
    domain: DomainCategory
    prediction_text: str
    confidence: float
    horizon: str  # "short", "medium", "long"
    source_cluster_id: str
    platforms_at_prediction: list[Platform]
    created_at: str = ""
    expires_at: str = ""
    outcome: PredictionOutcome = PredictionOutcome.PENDING
    outcome_notes: str = ""
    accuracy_score: float = 0.0


@dataclass
class FeedbackCycleReport:
    """Report from one complete feedback cycle."""

    cycle_id: str
    timestamp: str
    signals_collected: int
    trends_detected: int
    predictions_made: int
    predictions_verified: int
    accuracy_rate: float
    top_trends: list[str]
    platform_coverage: dict[str, int]
    domain_coverage: dict[str, int]
    learning_adjustments: list[str]


# ── Signal Normalizer ───────────────────────────────────────────


class SignalNormalizer:
    """Normalize platform-specific signals into UnifiedSignal format."""

    # Map platform-specific domain names to our unified DomainCategory
    DOMAIN_MAP: ClassVar[dict[str, DomainCategory]] = {
        # GitHub domains
        "ai_ml": DomainCategory.AI_TECHNOLOGY,
        "web_frameworks": DomainCategory.AI_TECHNOLOGY,
        "devtools": DomainCategory.AI_TECHNOLOGY,
        "data_science": DomainCategory.SCIENCE,
        "security": DomainCategory.SECURITY,
        # Reddit domains
        "artificial_intelligence": DomainCategory.AI_TECHNOLOGY,
        "machine_learning": DomainCategory.AI_TECHNOLOGY,
        "technology": DomainCategory.AI_TECHNOLOGY,
        "programming": DomainCategory.AI_TECHNOLOGY,
        "crypto": DomainCategory.FINANCE,
        "futurism": DomainCategory.SCIENCE,
        # Substack domains
        "ai_technology": DomainCategory.AI_TECHNOLOGY,
        # Google Trends categories
        "business": DomainCategory.FINANCE,
        "entertainment": DomainCategory.CULTURE,
        "sports": DomainCategory.CULTURE,
        "politics": DomainCategory.GEOPOLITICS,
        # X/Twitter domains
        "finance_markets": DomainCategory.FINANCE,
        "science_research": DomainCategory.SCIENCE,
        "security_intelligence": DomainCategory.SECURITY,
        "philosophy_wisdom": DomainCategory.CULTURE,
        "health_longevity": DomainCategory.HEALTH,
        "personal_brand": DomainCategory.CULTURE,
        "operations_productivity": DomainCategory.AI_TECHNOLOGY,
        "creative_media": DomainCategory.CULTURE,
        # TikTok domains
        "ai_tech": DomainCategory.AI_TECHNOLOGY,
        "education": DomainCategory.SCIENCE,
        "culture_trends": DomainCategory.CULTURE,
        "creator_economy": DomainCategory.ENTREPRENEURSHIP,
        "health_wellness": DomainCategory.HEALTH,
        "health_fitness": DomainCategory.HEALTH,
        # Instagram domains
        "art_design": DomainCategory.CULTURE,
        "lifestyle": DomainCategory.CULTURE,
        "news_politics": DomainCategory.GEOPOLITICS,
    }

    @classmethod
    def normalize_domain(cls, raw_domain: str) -> DomainCategory:
        """Map any platform's domain string to DomainCategory."""
        key = raw_domain.lower().replace(" ", "_")
        if key in cls.DOMAIN_MAP:
            return cls.DOMAIN_MAP[key]
        # Try direct match
        try:
            return DomainCategory(key)
        except ValueError:
            return DomainCategory.GENERAL

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("signal_id", ""),
            platform=Platform.GITHUB,
            domain=cls.normalize_domain(data.get("domain", "general")),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            strength=SignalStrength.MODERATE,
            source_url=data.get("url", ""),
            raw_metadata=data,
        )

    @classmethod
    def from_reddit(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("post_id", ""),
            platform=Platform.REDDIT,
            domain=cls.normalize_domain(data.get("domain", "general")),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            strength=SignalStrength.MODERATE,
            source_url=data.get("url", ""),
            raw_metadata=data,
        )

    @classmethod
    def from_substack(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("article_id", ""),
            platform=Platform.SUBSTACK,
            domain=cls.normalize_domain(data.get("domain", "general")),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            strength=SignalStrength.MODERATE,
            source_url=data.get("url", ""),
            raw_metadata=data,
        )

    @classmethod
    def from_google_trends(cls, data: dict[str, Any]) -> UnifiedSignal:
        volume_map = {"low": SignalStrength.WEAK, "moderate": SignalStrength.MODERATE,
                      "high": SignalStrength.STRONG, "massive": SignalStrength.OVERWHELMING}
        return UnifiedSignal(
            signal_id=data.get("trend_id", ""),
            platform=Platform.GOOGLE_TRENDS,
            domain=cls.normalize_domain(data.get("category", "general")),
            title=data.get("query", ""),
            summary=data.get("news_headline", ""),
            strength=volume_map.get(data.get("volume", "low"), SignalStrength.MODERATE),
            raw_metadata=data,
        )

    @classmethod
    def from_tiktok(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("signal_id", ""),
            platform=Platform.TIKTOK,
            domain=cls.normalize_domain(data.get("domain", "general")),
            title=data.get("hashtag", ""),
            summary=data.get("description", ""),
            strength=SignalStrength.MODERATE,
            raw_metadata=data,
        )

    @classmethod
    def from_instagram(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("signal_id", ""),
            platform=Platform.INSTAGRAM,
            domain=cls.normalize_domain(data.get("domain", "general")),
            title=data.get("source", ""),
            summary=data.get("description", ""),
            strength=SignalStrength.WEAK,
            raw_metadata=data,
        )

    @classmethod
    def from_x(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("post_id", ""),
            platform=Platform.X_TWITTER,
            domain=cls.normalize_domain(data.get("domain", "general")),
            title=data.get("content", "")[:120],
            summary=data.get("content", ""),
            strength=SignalStrength.MODERATE,
            raw_metadata=data,
        )

    @classmethod
    def from_youtube(cls, data: dict[str, Any]) -> UnifiedSignal:
        return UnifiedSignal(
            signal_id=data.get("video_id", ""),
            platform=Platform.YOUTUBE,
            domain=cls.normalize_domain(data.get("category", "general")),
            title=data.get("title", ""),
            summary=data.get("description", ""),
            strength=SignalStrength.MODERATE,
            source_url=data.get("url", ""),
            raw_metadata=data,
        )


# ── Trend Detector ──────────────────────────────────────────────


class TrendDetector:
    """Detect cross-platform trends by clustering related signals."""

    def __init__(self) -> None:
        self._clusters: dict[str, TrendCluster] = {}

    def detect(self, signals: list[UnifiedSignal]) -> list[TrendCluster]:
        """Detect trend clusters from normalized signals."""
        # Group by domain + keyword overlap
        topic_groups: dict[str, list[UnifiedSignal]] = {}

        for signal in signals:
            # Extract key terms from title for grouping
            key_terms = self._extract_key_terms(signal.title)
            for term in key_terms:
                group_key = f"{signal.domain}:{term}"
                if group_key not in topic_groups:
                    topic_groups[group_key] = []
                topic_groups[group_key].append(signal)

        clusters: list[TrendCluster] = []
        for group_key, group_signals in topic_groups.items():
            if len(group_signals) < 2:
                continue  # Need at least 2 signals for a trend

            domain_str, topic = group_key.split(":", 1)
            platforms = list({s.platform for s in group_signals})
            phase = self._assess_phase(len(platforms), len(group_signals))

            cluster = TrendCluster(
                cluster_id=hashlib.sha256(group_key.encode()).hexdigest()[:16],
                topic=topic,
                domain=DomainCategory(domain_str),
                phase=phase,
                platforms=platforms,
                signal_count=len(group_signals),
                signals=[s.fingerprint for s in group_signals],
                first_seen=min(s.collected_at for s in group_signals),
                last_seen=max(s.collected_at for s in group_signals),
                cross_platform_score=len(platforms) / len(Platform),
            )
            clusters.append(cluster)
            self._clusters[cluster.cluster_id] = cluster

        # Sort by cross-platform score descending
        clusters.sort(key=lambda c: c.cross_platform_score, reverse=True)
        return clusters

    @staticmethod
    def _extract_key_terms(title: str) -> list[str]:
        """Extract significant terms from a title for clustering."""
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be",
                      "been", "being", "have", "has", "had", "do", "does",
                      "did", "will", "would", "could", "should", "may",
                      "might", "shall", "can", "for", "and", "nor", "but",
                      "or", "yet", "so", "at", "by", "from", "in", "into",
                      "of", "on", "to", "with", "its", "it", "this", "that",
                      "these", "those", "my", "your", "his", "her", "our",
                      "not", "no", "if", "how", "what", "when", "where",
                      "who", "why", "all", "each", "every", "both", "few",
                      "more", "most", "some", "any", "new", "just", "now"}
        words = title.lower().split()
        terms = [w.strip(".,!?#@()[]{}\"'") for w in words
                 if len(w) > 2 and w.lower() not in stop_words]
        return terms[:5]  # Max 5 key terms

    @staticmethod
    def _assess_phase(platform_count: int, signal_count: int) -> TrendPhase:
        """Assess trend phase based on platform spread and signal volume."""
        if platform_count >= 6 and signal_count >= 20:
            return TrendPhase.SATURATED
        if platform_count >= 5 and signal_count >= 15:
            return TrendPhase.PEAKING
        if platform_count >= 4:
            return TrendPhase.RISING
        if platform_count >= 2:
            return TrendPhase.EMERGING
        return TrendPhase.SEED


# ── Prediction Tracker ──────────────────────────────────────────


class PredictionTracker:
    """Track predictions and measure accuracy over time."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or (_FPC_ROOT / "data" / "predictions")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, PredictionRecord] = {}
        self._load_existing()

    def record_prediction(self, cluster: TrendCluster,
                          prediction_text: str,
                          confidence: float,
                          horizon: str = "medium") -> PredictionRecord:
        """Record a new prediction from a trend cluster."""
        pred_id = hashlib.sha256(
            f"{cluster.cluster_id}:{prediction_text[:50]}".encode()
        ).hexdigest()[:16]

        record = PredictionRecord(
            prediction_id=pred_id,
            topic=cluster.topic,
            domain=cluster.domain,
            prediction_text=prediction_text,
            confidence=confidence,
            horizon=horizon,
            source_cluster_id=cluster.cluster_id,
            platforms_at_prediction=list(cluster.platforms),
            created_at=datetime.now(UTC).isoformat(),
        )
        self._records[pred_id] = record
        self._persist()
        return record

    def verify_prediction(self, prediction_id: str,
                          outcome: PredictionOutcome,
                          notes: str = "",
                          accuracy: float = 0.0) -> PredictionRecord | None:
        """Update a prediction with its outcome."""
        record = self._records.get(prediction_id)
        if record is None:
            return None
        record.outcome = outcome
        record.outcome_notes = notes
        record.accuracy_score = accuracy
        self._persist()
        return record

    def accuracy_report(self) -> dict[str, Any]:
        """Generate accuracy statistics."""
        total = len(self._records)
        if total == 0:
            return {"total": 0, "accuracy": 0.0}

        outcomes: dict[str, int] = {}
        for rec in self._records.values():
            outcomes[rec.outcome.value] = outcomes.get(rec.outcome.value, 0) + 1

        resolved = sum(v for k, v in outcomes.items()
                       if k not in ("pending", "expired"))
        correct = outcomes.get("correct", 0) + outcomes.get("partially_correct", 0) * 0.5

        return {
            "total": total,
            "outcomes": outcomes,
            "resolved": resolved,
            "accuracy": round(correct / max(resolved, 1), 3),
            "pending": outcomes.get("pending", 0),
        }

    def _load_existing(self) -> None:
        """Load existing predictions from disk."""
        pred_file = self._data_dir / "predictions.json"
        if pred_file.exists():
            try:
                data = json.loads(pred_file.read_text(encoding="utf-8"))
                for item in data.get("predictions", []):
                    rec = PredictionRecord(
                        prediction_id=item["prediction_id"],
                        topic=item["topic"],
                        domain=DomainCategory(item.get("domain", "general")),
                        prediction_text=item["prediction_text"],
                        confidence=item.get("confidence", 0.5),
                        horizon=item.get("horizon", "medium"),
                        source_cluster_id=item.get("source_cluster_id", ""),
                        platforms_at_prediction=[Platform(p) for p in item.get("platforms_at_prediction", [])],
                        created_at=item.get("created_at", ""),
                        outcome=PredictionOutcome(item.get("outcome", "pending")),
                        outcome_notes=item.get("outcome_notes", ""),
                        accuracy_score=item.get("accuracy_score", 0.0),
                    )
                    self._records[rec.prediction_id] = rec
            except Exception as exc:
                logger.warning("Failed to load predictions: %s", exc)

    def _persist(self) -> None:
        """Save all predictions to disk."""
        pred_file = self._data_dir / "predictions.json"
        try:
            pred_file.write_text(
                json.dumps({
                    "predictions": [asdict(r) for r in self._records.values()],
                    "updated_at": datetime.now(UTC).isoformat(),
                }, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist predictions: %s", exc)


# ── Feedback Controller ─────────────────────────────────────────


class FeedbackController:
    """Adjust scraper priorities based on prediction accuracy and trends."""

    def __init__(self) -> None:
        self._platform_weights: dict[Platform, float] = {p: 1.0 for p in Platform}
        self._domain_weights: dict[DomainCategory, float] = {d: 1.0 for d in DomainCategory}

    def adjust_from_accuracy(self, tracker: PredictionTracker) -> list[str]:
        """Adjust weights based on prediction accuracy by platform/domain."""
        adjustments: list[str] = []
        for rec in tracker._records.values():
            if rec.outcome == PredictionOutcome.CORRECT:
                # Boost platforms that contributed to correct predictions
                for plat in rec.platforms_at_prediction:
                    old = self._platform_weights[plat]
                    self._platform_weights[plat] = min(2.0, old + 0.1)
                    adjustments.append(f"{plat}: weight {old:.1f} → {self._platform_weights[plat]:.1f}")
            elif rec.outcome == PredictionOutcome.INCORRECT:
                for plat in rec.platforms_at_prediction:
                    old = self._platform_weights[plat]
                    self._platform_weights[plat] = max(0.3, old - 0.05)

        return adjustments

    def adjust_from_trends(self, clusters: list[TrendCluster]) -> list[str]:
        """Boost domains and platforms where trends are emerging."""
        adjustments: list[str] = []
        for cluster in clusters:
            if cluster.phase in (TrendPhase.SEED, TrendPhase.EMERGING):
                old = self._domain_weights[cluster.domain]
                self._domain_weights[cluster.domain] = min(2.0, old + 0.15)
                adjustments.append(
                    f"Domain {cluster.domain} boosted for emerging trend '{cluster.topic}'")
        return adjustments

    @property
    def platform_priorities(self) -> dict[str, float]:
        return {p.value: round(w, 2) for p, w in
                sorted(self._platform_weights.items(), key=lambda x: x[1], reverse=True)}

    @property
    def domain_priorities(self) -> dict[str, float]:
        return {d.value: round(w, 2) for d, w in
                sorted(self._domain_weights.items(), key=lambda x: x[1], reverse=True)}


# ── Master Feedback Loop ────────────────────────────────────────


class PredictionFeedbackLoop:
    """The master feedback loop coordinating all platform intelligence.

    Cycle: Collect → Normalize → Cluster → Predict → Verify → Adjust → Repeat
    """

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or (_FPC_ROOT / "data")
        self._normalizer = SignalNormalizer()
        self._detector = TrendDetector()
        self._tracker = PredictionTracker(self._data_dir / "predictions")
        self._feedback = FeedbackController()
        self._cycle_count = 0

    def run_cycle(self) -> FeedbackCycleReport:
        """Execute one complete feedback cycle."""
        self._cycle_count += 1
        cycle_id = f"FPC-CYCLE-{self._cycle_count:04d}"
        logger.info("Starting feedback cycle %s", cycle_id)

        # Phase 1: Collect signals from all platform caches
        signals = self._collect_all_cached_signals()
        logger.info("Collected %d signals from caches", len(signals))

        # Phase 2: Detect cross-platform trends
        clusters = self._detector.detect(signals)
        logger.info("Detected %d trend clusters", len(clusters))

        # Phase 3: Generate predictions for significant trends
        predictions_made = 0
        for cluster in clusters:
            if cluster.phase in (TrendPhase.EMERGING, TrendPhase.RISING):
                pred_text = self._generate_prediction_text(cluster)
                self._tracker.record_prediction(
                    cluster=cluster,
                    prediction_text=pred_text,
                    confidence=cluster.cross_platform_score,
                    horizon="medium" if cluster.phase == TrendPhase.EMERGING else "short",
                )
                predictions_made += 1

        # Phase 4: Verify past predictions
        verified = self._auto_verify_predictions(clusters)

        # Phase 5: Adjust weights based on feedback
        adjustments: list[str] = []
        adjustments.extend(self._feedback.adjust_from_accuracy(self._tracker))
        adjustments.extend(self._feedback.adjust_from_trends(clusters))

        # Build report
        platform_coverage: dict[str, int] = {}
        domain_coverage: dict[str, int] = {}
        for sig in signals:
            platform_coverage[sig.platform.value] = platform_coverage.get(sig.platform.value, 0) + 1
            domain_coverage[sig.domain.value] = domain_coverage.get(sig.domain.value, 0) + 1

        accuracy = self._tracker.accuracy_report()

        report = FeedbackCycleReport(
            cycle_id=cycle_id,
            timestamp=datetime.now(UTC).isoformat(),
            signals_collected=len(signals),
            trends_detected=len(clusters),
            predictions_made=predictions_made,
            predictions_verified=verified,
            accuracy_rate=accuracy.get("accuracy", 0.0),
            top_trends=[c.topic for c in clusters[:10]],
            platform_coverage=platform_coverage,
            domain_coverage=domain_coverage,
            learning_adjustments=adjustments,
        )

        self._cache_report(report)
        logger.info("Cycle %s complete: %d signals, %d trends, %d predictions",
                     cycle_id, len(signals), len(clusters), predictions_made)
        return report

    def _collect_all_cached_signals(self) -> list[UnifiedSignal]:
        """Read cached data from all platform scrapers."""
        signals: list[UnifiedSignal] = []

        platform_loaders: dict[str, tuple[str, Any]] = {
            "github_cache": ("github", self._normalizer.from_github),
            "reddit_cache": ("posts", self._normalizer.from_reddit),
            "substack_cache": ("articles", self._normalizer.from_substack),
            "gtrends_cache": ("signals", self._normalizer.from_google_trends),
            "tiktok_cache": ("signals", self._normalizer.from_tiktok),
            "instagram_cache": ("signals", self._normalizer.from_instagram),
            "x_cache": ("posts", self._normalizer.from_x),
        }

        for cache_name, (items_key, converter) in platform_loaders.items():
            cache_dir = self._data_dir / cache_name
            if not cache_dir.exists():
                continue
            for cache_file in sorted(cache_dir.glob("*.json"))[-3:]:  # Last 3 days
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    items = data.get(items_key, data.get("articles", data.get("signals", [])))
                    for item in items:
                        try:
                            signals.append(converter(item))
                        except Exception:
                            logger.debug("Skipping malformed item in %s", cache_file)
                            continue
                except Exception as exc:
                    logger.debug("Failed to load %s: %s", cache_file, exc)

        return signals

    def _generate_prediction_text(self, cluster: TrendCluster) -> str:
        """Generate a prediction statement from a trend cluster."""
        platform_list = ", ".join(p.value for p in cluster.platforms[:3])
        phase_desc = {
            TrendPhase.SEED: "just beginning to surface",
            TrendPhase.EMERGING: "gaining traction across multiple platforms",
            TrendPhase.RISING: "rapidly growing in visibility",
            TrendPhase.PEAKING: "reaching peak attention",
        }
        desc = phase_desc.get(cluster.phase, "evolving")
        return (
            f"Trend '{cluster.topic}' in {cluster.domain.value} is {desc}. "
            f"Detected across {len(cluster.platforms)} platforms ({platform_list}) "
            f"with {cluster.signal_count} signals. "
            f"Cross-platform score: {cluster.cross_platform_score:.2f}. "
            f"Expected to {'accelerate' if cluster.phase in (TrendPhase.SEED, TrendPhase.EMERGING) else 'stabilize'} "
            f"in the near term."
        )

    def _auto_verify_predictions(self, current_clusters: list[TrendCluster]) -> int:
        """Auto-verify past predictions against current trend data."""
        verified = 0
        current_topics = {c.topic.lower() for c in current_clusters}

        for rec in self._tracker._records.values():
            if rec.outcome != PredictionOutcome.PENDING:
                continue
            # Check if the topic is still trending
            if rec.topic.lower() in current_topics:
                self._tracker.verify_prediction(
                    rec.prediction_id,
                    PredictionOutcome.CORRECT,
                    notes="Topic still trending in current cycle",
                    accuracy=0.8,
                )
                verified += 1

        return verified

    def get_priorities(self) -> dict[str, Any]:
        """Get current platform and domain priorities for scraper tuning."""
        return {
            "platform_priorities": self._feedback.platform_priorities,
            "domain_priorities": self._feedback.domain_priorities,
            "accuracy": self._tracker.accuracy_report(),
        }

    def _cache_report(self, report: FeedbackCycleReport) -> None:
        report_dir = self._data_dir / "feedback_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"cycle_{report.cycle_id}.json"
        try:
            report_file.write_text(
                json.dumps(asdict(report), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to cache cycle report: %s", exc)
