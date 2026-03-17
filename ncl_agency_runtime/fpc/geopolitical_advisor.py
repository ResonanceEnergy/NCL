"""Geopolitical Advisor Module -- Jiang Xueqin Framework.

Integrates Jiang Xueqin's geopolitical analysis methodology into the
Future Predictor Council as a trusted advisor for geopolitical commentary,
with an ongoing data pipeline for signal collection, assessment, and
strategic advisory generation.

Jiang Xueqin Analytical Principles:
  1. Innovation-over-imitation -- measure a nation's true capacity to innovate
  2. Education-as-predictor -- education pipelines shape long-term geopolitical power
  3. Bridge perspectives -- synthesize Eastern and Western viewpoints
  4. Structural-over-surface -- root-cause systemic analysis, not headline chasing
  5. Data-driven narrative -- marry qualitative insight with quantitative signals
  6. Long-horizon thinking -- geopolitical shifts unfold over decades, not quarters

Components:
  - GeopoliticalLens     -- 6 analytical lenses for multi-dimensional assessment
  - SignalCollector      -- Ingest geopolitical signals with source credibility
  - NarrativeEngine      -- Transform raw signals into structured advisories
  - GeopoliticalPipeline -- Ongoing collection -> scoring -> trend -> advisory
  - StrategicAssessment  -- Multi-lens risk/opportunity scoring
  - AdvisoryBoard        -- Trusted advisor registry with track record

Architecture follows the same patterns as unit_8200_doctrine.py.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

# ── Enums ──────────────────────────────────────────────────────

class GeopoliticalLens(StrEnum):
    """Six analytical lenses from Jiang Xueqin's framework."""

    INNOVATION_ECOSYSTEM = "innovation_ecosystem"
    EDUCATION_PIPELINE = "education_pipeline"
    STRATEGIC_COMPETITION = "strategic_competition"
    TRADE_SUPPLY_CHAIN = "trade_supply_chain"
    TECHNOLOGY_SOVEREIGNTY = "technology_sovereignty"
    CULTURAL_DIPLOMACY = "cultural_diplomacy"


class SignalStrength(StrEnum):
    """Signal strength classification for geopolitical events."""

    NOISE = "noise"           # Background chatter, no actionable value
    WEAK = "weak"             # Emerging pattern, needs confirmation
    MODERATE = "moderate"     # Confirmed trend, worth monitoring
    STRONG = "strong"         # Clear signal, requires action planning
    CRITICAL = "critical"     # Inflection point, immediate advisory needed


class AdvisoryTier(StrEnum):
    """Advisory urgency classification."""

    ROUTINE = "routine"       # Regular cycle reporting
    ELEVATED = "elevated"     # Heightened attention recommended
    URGENT = "urgent"         # Immediate strategic review needed
    FLASH = "flash"           # Emergency advisory -- decision required now


class Region(StrEnum):
    """Major geopolitical regions for signal tagging."""

    CHINA = "china"
    USA = "usa"
    EU = "eu"
    ASIA_PACIFIC = "asia_pacific"
    MIDDLE_EAST = "middle_east"
    GLOBAL = "global"


# ── Data Contracts ─────────────────────────────────────────────

@dataclass
class GeopoliticalSignal:
    """A single geopolitical signal ingested from a source."""

    signal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = ""
    region: Region = Region.GLOBAL
    lens: GeopoliticalLens = GeopoliticalLens.STRATEGIC_COMPETITION
    headline: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    strength: SignalStrength = SignalStrength.WEAK
    credibility: float = 0.5        # 0.0 - 1.0 source credibility
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.source}:{self.headline}:{self.region}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class StrategicAssessment:
    """Multi-lens geopolitical risk/opportunity assessment."""

    assessment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    region: Region = Region.GLOBAL
    lens_scores: dict[str, float] = field(default_factory=dict)
    overall_risk: float = 0.0
    overall_opportunity: float = 0.0
    confidence: float = 0.0
    signal_count: int = 0
    horizon_years: int = 5
    narrative: str = ""
    recommendations: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def compute_composite(self) -> float:
        """Compute composite score: opportunity-weighted, risk-adjusted."""
        if not self.lens_scores:
            return 0.0
        avg = sum(self.lens_scores.values()) / len(self.lens_scores)
        # Risk dampens, opportunity amplifies
        composite = avg * (1.0 + self.overall_opportunity) / (1.0 + self.overall_risk)
        return min(1.0, max(0.0, composite))


@dataclass
class AdvisoryNote:
    """A structured advisory from the geopolitical advisor."""

    note_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tier: AdvisoryTier = AdvisoryTier.ROUTINE
    region: Region = Region.GLOBAL
    title: str = ""
    analysis: str = ""
    lenses_applied: list[str] = field(default_factory=list)
    key_signals: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)


@dataclass
class TrendLine:
    """A tracked geopolitical trend over time."""

    trend_id: str = ""
    lens: GeopoliticalLens = GeopoliticalLens.STRATEGIC_COMPETITION
    region: Region = Region.GLOBAL
    description: str = ""
    data_points: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    direction: str = "stable"  # rising, falling, stable, volatile
    momentum: float = 0.0


# ── Signal Collector ───────────────────────────────────────────

class SignalCollector:
    """Ingest and classify geopolitical signals with credibility scoring.

    Applies Jiang Xueqin's principle: data-driven narrative requires
    rigorous source evaluation before analysis begins.
    """

    # Source credibility baselines (can be adjusted via calibrate)
    SOURCE_CREDIBILITY: ClassVar[dict[str, float]] = {
        "academic": 0.85,
        "government": 0.75,
        "think_tank": 0.80,
        "news_wire": 0.70,
        "social_media": 0.30,
        "insider": 0.65,
        "satellite": 0.90,
        "trade_data": 0.88,
        "patent_filing": 0.92,
        "education_stats": 0.87,
    }

    def __init__(self) -> None:
        self.signals: list[GeopoliticalSignal] = []
        self._fingerprints: set[str] = set()
        self.collection_stats: dict[str, int] = {}

    def ingest(
        self,
        source: str,
        region: Region,
        lens: GeopoliticalLens,
        headline: str,
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> GeopoliticalSignal:
        """Ingest a geopolitical signal with auto-credibility scoring."""
        credibility = self._score_credibility(source)
        strength = self._classify_strength(content or {}, credibility)

        signal = GeopoliticalSignal(
            source=source,
            region=region,
            lens=lens,
            headline=headline,
            content=content or {},
            strength=strength,
            credibility=credibility,
            tags=tags or [],
        )

        # Deduplicate by fingerprint
        if signal.fingerprint in self._fingerprints:
            return signal
        self._fingerprints.add(signal.fingerprint)

        self.signals.append(signal)
        self.collection_stats[source] = self.collection_stats.get(source, 0) + 1
        return signal

    def _score_credibility(self, source: str) -> float:
        """Score source credibility using baseline + heuristics."""
        source_lower = source.lower()
        for key, score in self.SOURCE_CREDIBILITY.items():
            if key in source_lower:
                return score
        return 0.5  # Default for unknown sources

    def _classify_strength(
        self,
        content: dict[str, Any],
        credibility: float,
    ) -> SignalStrength:
        """Classify signal strength from content + credibility."""
        # Count signal indicators
        indicators = 0
        if content.get("quantitative_data"):
            indicators += 2
        if content.get("confirmed"):
            indicators += 2
        if content.get("multiple_sources"):
            indicators += 1
        if content.get("policy_change"):
            indicators += 2
        if content.get("inflection_point"):
            indicators += 3
        if content.get("structural_shift"):
            indicators += 2

        # Credibility multiplier
        weighted = indicators * credibility

        if weighted >= 4.0:
            return SignalStrength.CRITICAL
        if weighted >= 2.5:
            return SignalStrength.STRONG
        if weighted >= 1.5:
            return SignalStrength.MODERATE
        if weighted >= 0.5:
            return SignalStrength.WEAK
        return SignalStrength.NOISE

    def signals_by_lens(self, lens: GeopoliticalLens) -> list[GeopoliticalSignal]:
        """Get all signals for a specific analytical lens."""
        return [s for s in self.signals if s.lens == lens]

    def signals_by_region(self, region: Region) -> list[GeopoliticalSignal]:
        """Get all signals for a specific region."""
        return [s for s in self.signals if s.region == region]

    def strong_signals(self) -> list[GeopoliticalSignal]:
        """Get signals at STRONG or CRITICAL strength."""
        return [
            s for s in self.signals
            if s.strength in (SignalStrength.STRONG, SignalStrength.CRITICAL)
        ]

    def summary(self) -> dict[str, Any]:
        """Collection summary statistics."""
        by_strength: dict[str, int] = {}
        by_region: dict[str, int] = {}
        for s in self.signals:
            by_strength[s.strength.value] = by_strength.get(s.strength.value, 0) + 1
            by_region[s.region.value] = by_region.get(s.region.value, 0) + 1

        return {
            "total_signals": len(self.signals),
            "by_strength": by_strength,
            "by_region": by_region,
            "sources": dict(self.collection_stats),
            "avg_credibility": (
                sum(s.credibility for s in self.signals) / len(self.signals)
                if self.signals else 0.0
            ),
        }


# ── Narrative Engine ───────────────────────────────────────────

class NarrativeEngine:
    """Transform signals into structured narratives.

    Follows Jiang Xueqin's bridging methodology: synthesize Eastern
    and Western viewpoints into a coherent structural narrative
    that goes beyond surface-level commentary.
    """

    # Jiang Xueqin's analytical principles
    PRINCIPLES: ClassVar[list[str]] = [
        "innovation_over_imitation",
        "education_as_predictor",
        "bridge_perspectives",
        "structural_over_surface",
        "data_driven_narrative",
        "long_horizon_thinking",
    ]

    def __init__(self) -> None:
        self.narratives: list[dict[str, Any]] = []

    def build_narrative(
        self,
        signals: list[GeopoliticalSignal],
        region: Region = Region.GLOBAL,
        horizon_years: int = 5,
    ) -> dict[str, Any]:
        """Build a structured analytical narrative from signals.

        Applies the bridge-perspectives principle: identifies tensions
        between different viewpoints and synthesizes them.
        """
        if not signals:
            return {
                "status": "insufficient_data",
                "signal_count": 0,
                "narrative": "No signals available for analysis.",
            }

        # Group signals by lens
        by_lens: dict[str, list[GeopoliticalSignal]] = {}
        for sig in signals:
            by_lens.setdefault(sig.lens.value, []).append(sig)

        # Score each lens
        lens_analysis: dict[str, dict[str, Any]] = {}
        for lens_name, lens_signals in by_lens.items():
            avg_cred = sum(s.credibility for s in lens_signals) / len(lens_signals)
            strong = sum(
                1 for s in lens_signals
                if s.strength in (SignalStrength.STRONG, SignalStrength.CRITICAL)
            )
            lens_analysis[lens_name] = {
                "signal_count": len(lens_signals),
                "avg_credibility": round(avg_cred, 3),
                "strong_signals": strong,
                "coverage": round(len(lens_signals) / len(signals), 3),
            }

        # Identify tensions (conflicting signals in same lens)
        tensions = self._find_tensions(signals)

        # Compute narrative confidence
        avg_cred_all = sum(s.credibility for s in signals) / len(signals)
        lens_coverage = len(by_lens) / len(GeopoliticalLens)
        confidence = min(1.0, avg_cred_all * (0.5 + 0.5 * lens_coverage))

        narrative = {
            "status": "narrative_built",
            "region": region.value,
            "signal_count": len(signals),
            "lens_coverage": len(by_lens),
            "total_lenses": len(GeopoliticalLens),
            "lens_analysis": lens_analysis,
            "tensions": tensions,
            "confidence": round(confidence, 3),
            "horizon_years": horizon_years,
            "principles_applied": list(self.PRINCIPLES),
        }

        self.narratives.append(narrative)
        return narrative

    def _find_tensions(self, signals: list[GeopoliticalSignal]) -> list[dict[str, Any]]:
        """Identify tensions between signals (bridge-perspectives principle)."""
        tensions: list[dict[str, Any]] = []

        # Group by lens and look for conflicting strength + tags
        by_lens: dict[str, list[GeopoliticalSignal]] = {}
        for sig in signals:
            by_lens.setdefault(sig.lens.value, []).append(sig)

        for lens_name, lens_signals in by_lens.items():
            if len(lens_signals) < 2:
                continue

            # Look for signals with opposing tags
            positive_tags = {"growth", "opportunity", "cooperation", "reform", "innovation"}
            negative_tags = {"decline", "risk", "conflict", "stagnation", "restriction"}

            has_positive = any(
                set(s.tags) & positive_tags for s in lens_signals
            )
            has_negative = any(
                set(s.tags) & negative_tags for s in lens_signals
            )

            if has_positive and has_negative:
                tensions.append({
                    "lens": lens_name,
                    "type": "opposing_signals",
                    "signal_count": len(lens_signals),
                    "note": f"Conflicting indicators in {lens_name} -- requires deeper structural analysis",
                })

        return tensions

    def apply_structural_filter(
        self,
        signals: list[GeopoliticalSignal],
    ) -> list[GeopoliticalSignal]:
        """Filter for structural signals over surface noise.

        Jiang Xueqin principle: structural-over-surface analysis.
        Only retain signals that indicate systemic/structural dynamics.
        """
        structural_indicators = {
            "policy_change", "structural_shift", "education_reform",
            "innovation_metrics", "demographic_shift", "institutional_change",
            "trade_rebalance", "technology_transfer", "curriculum_reform",
        }

        return [
            s for s in signals
            if (
                s.strength in (SignalStrength.STRONG, SignalStrength.CRITICAL)
                or any(k in s.content for k in structural_indicators)
                or set(s.tags) & structural_indicators
            )
        ]


# ── Geopolitical Pipeline ─────────────────────────────────────

class GeopoliticalPipeline:
    """Ongoing data pipeline for geopolitical intelligence.

    Implements the full cycle:
      Collect -> Score -> Analyze -> Trend -> Advise

    This is the 'ongoing data pipeline' requested for continuous
    geopolitical monitoring and advisory generation.
    """

    def __init__(self) -> None:
        self.collector = SignalCollector()
        self.narrative = NarrativeEngine()
        self.trends: dict[str, TrendLine] = {}
        self.advisories: list[AdvisoryNote] = []
        self._cycle_count = 0

    def collect(
        self,
        source: str,
        region: Region,
        lens: GeopoliticalLens,
        headline: str,
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> GeopoliticalSignal:
        """Stage 1 -- Collect a geopolitical signal into the pipeline."""
        return self.collector.ingest(
            source=source,
            region=region,
            lens=lens,
            headline=headline,
            content=content,
            tags=tags,
        )

    def analyze(self, region: Region = Region.GLOBAL) -> dict[str, Any]:
        """Stage 2 -- Analyze collected signals into a narrative."""
        signals = (
            self.collector.signals_by_region(region)
            if region != Region.GLOBAL
            else self.collector.signals
        )

        # Apply structural filter (Jiang Xueqin: structural-over-surface)
        structural = self.narrative.apply_structural_filter(signals)

        return self.narrative.build_narrative(
            structural if structural else signals,
            region=region,
        )

    def track_trend(
        self,
        trend_id: str,
        lens: GeopoliticalLens,
        region: Region,
        description: str,
        data_point: float,
    ) -> TrendLine:
        """Stage 3 -- Track a geopolitical trend over time."""
        if trend_id not in self.trends:
            self.trends[trend_id] = TrendLine(
                trend_id=trend_id,
                lens=lens,
                region=region,
                description=description,
            )

        trend = self.trends[trend_id]
        trend.data_points.append(data_point)
        trend.timestamps.append(time.time())

        # Update direction if enough data
        if len(trend.data_points) >= 3:
            trend.direction, trend.momentum = self._compute_direction(trend.data_points)

        return trend

    def _compute_direction(self, data: list[float]) -> tuple[str, float]:
        """Compute trend direction and momentum from data points."""
        if len(data) < 2:
            return "stable", 0.0

        recent = data[-3:]
        diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        avg_diff = sum(diffs) / len(diffs)

        # Compute momentum as normalized change rate
        scale = max(abs(d) for d in data) if data else 1.0
        if scale == 0:
            scale = 1.0
        momentum = avg_diff / scale

        # Classify direction
        if abs(momentum) < 0.02:
            direction = "stable"
        elif all(d > 0 for d in diffs):
            direction = "rising"
        elif all(d < 0 for d in diffs):
            direction = "falling"
        else:
            direction = "volatile"

        return direction, round(momentum, 4)

    def generate_advisory(
        self,
        region: Region = Region.GLOBAL,
        title: str = "",
    ) -> AdvisoryNote:
        """Stage 4 -- Generate a structured advisory note."""
        signals = (
            self.collector.signals_by_region(region)
            if region != Region.GLOBAL
            else self.collector.signals
        )

        strong = self.collector.strong_signals()
        strong_in_region = [s for s in strong if s.region == region or region == Region.GLOBAL]

        # Determine tier based on signal strength distribution
        tier = self._classify_tier(signals)

        # Collect unique lenses
        lenses = sorted({s.lens.value for s in signals})

        # Pull key signal IDs
        key_ids = [s.signal_id for s in strong_in_region[:5]]

        # Generate recommendations based on active trends
        recommendations = self._generate_recommendations(region)

        # Compute confidence from signals
        confidence = 0.0
        if signals:
            avg_cred = sum(s.credibility for s in signals) / len(signals)
            strong_ratio = len(strong_in_region) / len(signals) if signals else 0.0
            confidence = round(min(1.0, avg_cred * (0.5 + 0.5 * strong_ratio)), 3)

        advisory = AdvisoryNote(
            tier=tier,
            region=region,
            title=title or f"Geopolitical Advisory: {region.value.upper()}",
            analysis=f"Based on {len(signals)} signals across {len(lenses)} lenses",
            lenses_applied=lenses,
            key_signals=key_ids,
            recommendations=recommendations,
            confidence=confidence,
        )

        self.advisories.append(advisory)
        return advisory

    def _classify_tier(self, signals: list[GeopoliticalSignal]) -> AdvisoryTier:
        """Classify advisory tier from signal distribution."""
        if not signals:
            return AdvisoryTier.ROUTINE

        critical = sum(1 for s in signals if s.strength == SignalStrength.CRITICAL)
        strong = sum(1 for s in signals if s.strength == SignalStrength.STRONG)

        if critical >= 2:
            return AdvisoryTier.FLASH
        if critical >= 1 or strong >= 3:
            return AdvisoryTier.URGENT
        if strong >= 1:
            return AdvisoryTier.ELEVATED
        return AdvisoryTier.ROUTINE

    def _generate_recommendations(self, region: Region) -> list[str]:
        """Generate recommendations from active trends."""
        recs: list[str] = []
        for trend in self.trends.values():
            if trend.region != region and region != Region.GLOBAL:
                continue
            if trend.direction == "rising" and trend.momentum > 0.05:
                recs.append(f"Monitor accelerating trend: {trend.description}")
            elif trend.direction == "falling" and trend.momentum < -0.05:
                recs.append(f"Investigate declining trend: {trend.description}")
            elif trend.direction == "volatile":
                recs.append(f"Volatility alert: {trend.description}")
        return recs

    def run_cycle(self) -> dict[str, Any]:
        """Run a full pipeline cycle: analyze + assess + trend + advise."""
        self._cycle_count += 1

        # Collect summary
        collection = self.collector.summary()

        # Build narrative for all regions with signals
        active_regions = sorted({s.region for s in self.collector.signals})
        narratives: dict[str, Any] = {}
        for region in active_regions:
            narratives[region.value] = self.analyze(region)

        # Generate advisories for active regions
        cycle_advisories: list[dict[str, Any]] = []
        for region in active_regions:
            advisory = self.generate_advisory(region)
            cycle_advisories.append({
                "region": region.value,
                "tier": advisory.tier.value,
                "confidence": advisory.confidence,
            })

        return {
            "cycle": self._cycle_count,
            "status": "cycle_complete",
            "collection": collection,
            "narratives_built": len(narratives),
            "advisories_generated": len(cycle_advisories),
            "advisories": cycle_advisories,
            "active_trends": len(self.trends),
        }

    def pipeline_health(self) -> dict[str, Any]:
        """Report pipeline health and coverage."""
        all_lenses = set(GeopoliticalLens)
        covered_lenses = {s.lens for s in self.collector.signals}
        all_regions = set(Region) - {Region.GLOBAL}
        covered_regions = {s.region for s in self.collector.signals} - {Region.GLOBAL}

        return {
            "status": "healthy" if self.collector.signals else "starved",
            "total_signals": len(self.collector.signals),
            "cycles_run": self._cycle_count,
            "advisories_issued": len(self.advisories),
            "lens_coverage": len(covered_lenses) / len(all_lenses) if all_lenses else 0.0,
            "region_coverage": len(covered_regions) / len(all_regions) if all_regions else 0.0,
            "active_trends": len(self.trends),
            "covered_lenses": sorted(ln.value for ln in covered_lenses),
            "covered_regions": sorted(r.value for r in covered_regions),
        }


# ── Advisory Board ─────────────────────────────────────────────

class AdvisoryBoard:
    """Trusted advisor registry with track record and credibility.

    Jiang Xueqin is the founding advisor. Additional advisors can be
    registered with their areas of expertise and credibility scores.
    """

    def __init__(self) -> None:
        self.advisors: dict[str, dict[str, Any]] = {}
        self.advisory_log: list[dict[str, Any]] = []

        # Register Jiang Xueqin as founding trusted advisor
        self.register_advisor(
            advisor_id="jiang_xueqin",
            name="Jiang Xueqin",
            role="Geopolitical Commentator & Education Reform Analyst",
            expertise=[
                "China innovation ecosystem",
                "Education-driven geopolitical forecasting",
                "US-China strategic competition",
                "Eastern-Western perspective bridging",
                "Structural systemic analysis",
                "Technology sovereignty dynamics",
            ],
            credibility=0.92,
            regions=[Region.CHINA, Region.USA, Region.ASIA_PACIFIC, Region.GLOBAL],
            lenses=[
                GeopoliticalLens.INNOVATION_ECOSYSTEM,
                GeopoliticalLens.EDUCATION_PIPELINE,
                GeopoliticalLens.STRATEGIC_COMPETITION,
                GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY,
            ],
        )

    def register_advisor(
        self,
        advisor_id: str,
        name: str,
        role: str,
        expertise: list[str] | None = None,
        credibility: float = 0.5,
        regions: list[Region] | None = None,
        lenses: list[GeopoliticalLens] | None = None,
    ) -> dict[str, Any]:
        """Register a trusted advisor on the board."""
        advisor = {
            "advisor_id": advisor_id,
            "name": name,
            "role": role,
            "expertise": expertise or [],
            "credibility": credibility,
            "regions": [r.value for r in (regions or [])],
            "lenses": [ln.value for ln in (lenses or [])],
            "advisories_issued": 0,
            "registered_at": time.time(),
        }
        self.advisors[advisor_id] = advisor
        return advisor

    def get_advisor(self, advisor_id: str) -> dict[str, Any] | None:
        """Look up an advisor by ID."""
        return self.advisors.get(advisor_id)

    def consult(
        self,
        advisor_id: str,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consult an advisor -- log the consultation and return guidance."""
        advisor = self.advisors.get(advisor_id)
        if advisor is None:
            return {"status": "advisor_not_found", "advisor_id": advisor_id}

        # Log the consultation
        entry = {
            "advisor_id": advisor_id,
            "question": question,
            "context": context or {},
            "timestamp": time.time(),
            "expertise_match": self._expertise_match(advisor, question),
        }
        self.advisory_log.append(entry)
        advisor["advisories_issued"] = advisor.get("advisories_issued", 0) + 1

        return {
            "status": "consulted",
            "advisor": advisor["name"],
            "credibility": advisor["credibility"],
            "expertise_match": entry["expertise_match"],
            "expertise": advisor["expertise"],
            "regions": advisor["regions"],
            "lenses": advisor["lenses"],
        }

    def _expertise_match(self, advisor: dict[str, Any], question: str) -> float:
        """Compute how well an advisor's expertise matches the question."""
        q_lower = question.lower()
        expertise = advisor.get("expertise", [])
        if not expertise:
            return 0.0

        matches = sum(
            1 for exp in expertise
            if any(word in q_lower for word in exp.lower().split())
        )
        return round(matches / len(expertise), 3)

    def board_summary(self) -> dict[str, Any]:
        """Summary of the advisory board."""
        return {
            "total_advisors": len(self.advisors),
            "total_consultations": len(self.advisory_log),
            "advisors": [
                {
                    "name": a["name"],
                    "role": a["role"],
                    "credibility": a["credibility"],
                    "advisories_issued": a["advisories_issued"],
                }
                for a in self.advisors.values()
            ],
        }


# ── Strategic Assessment Engine ────────────────────────────────

class AssessmentEngine:
    """Multi-lens strategic assessment with risk/opportunity scoring.

    Applies Jiang Xueqin's long-horizon thinking: assessments consider
    structural dynamics over 5-10 year horizons, not quarterly noise.
    """

    # Risk factors by lens (structural indicators)
    RISK_WEIGHTS: ClassVar[dict[str, float]] = {
        "innovation_ecosystem": 0.20,
        "education_pipeline": 0.20,
        "strategic_competition": 0.15,
        "trade_supply_chain": 0.15,
        "technology_sovereignty": 0.20,
        "cultural_diplomacy": 0.10,
    }

    def __init__(self) -> None:
        self.assessments: list[StrategicAssessment] = []

    def assess(
        self,
        signals: list[GeopoliticalSignal],
        region: Region = Region.GLOBAL,
        horizon_years: int = 5,
    ) -> StrategicAssessment:
        """Run a full multi-lens strategic assessment."""
        if not signals:
            assessment = StrategicAssessment(
                region=region,
                horizon_years=horizon_years,
                narrative="Insufficient signals for assessment.",
            )
            self.assessments.append(assessment)
            return assessment

        # Score each lens
        lens_scores: dict[str, float] = {}
        for lens in GeopoliticalLens:
            lens_signals = [s for s in signals if s.lens == lens]
            if lens_signals:
                lens_scores[lens.value] = self._score_lens(lens_signals)
            else:
                lens_scores[lens.value] = 0.0

        # Compute risk and opportunity
        risk = self._compute_risk(signals, lens_scores)
        opportunity = self._compute_opportunity(signals, lens_scores)

        # Confidence from signal quality
        avg_cred = sum(s.credibility for s in signals) / len(signals)
        lens_coverage = sum(1 for v in lens_scores.values() if v > 0.0) / len(GeopoliticalLens)
        confidence = round(min(1.0, avg_cred * (0.5 + 0.5 * lens_coverage)), 3)

        # Generate recommendations
        recs = self._recommendations(lens_scores, risk, opportunity)

        assessment = StrategicAssessment(
            region=region,
            lens_scores=lens_scores,
            overall_risk=round(risk, 3),
            overall_opportunity=round(opportunity, 3),
            confidence=confidence,
            signal_count=len(signals),
            horizon_years=horizon_years,
            narrative=f"Assessment across {sum(1 for v in lens_scores.values() if v > 0)} active lenses",
            recommendations=recs,
        )
        self.assessments.append(assessment)
        return assessment

    def _score_lens(self, signals: list[GeopoliticalSignal]) -> float:
        """Score a single lens from its signals. 0.0 - 1.0."""
        if not signals:
            return 0.0

        weights = {
            SignalStrength.CRITICAL: 1.0,
            SignalStrength.STRONG: 0.8,
            SignalStrength.MODERATE: 0.5,
            SignalStrength.WEAK: 0.2,
            SignalStrength.NOISE: 0.05,
        }

        total = sum(
            weights.get(s.strength, 0.1) * s.credibility
            for s in signals
        )
        # Normalize: diminishing returns past ~5 signals
        normalized = total / (total + 2.0) if total > 0 else 0.0
        return round(normalized, 3)

    def _compute_risk(
        self,
        signals: list[GeopoliticalSignal],
        lens_scores: dict[str, float],
    ) -> float:
        """Compute overall risk score."""
        risk_tags = {"risk", "decline", "conflict", "restriction", "stagnation", "sanction"}
        risk_signals = [s for s in signals if set(s.tags) & risk_tags]
        risk_ratio = len(risk_signals) / len(signals) if signals else 0.0

        # Weighted lens risk
        weighted_risk = sum(
            lens_scores.get(lens, 0.0) * self.RISK_WEIGHTS.get(lens, 0.1)
            for lens in lens_scores
        )

        return min(1.0, risk_ratio * 0.5 + weighted_risk * 0.5)

    def _compute_opportunity(
        self,
        signals: list[GeopoliticalSignal],
        lens_scores: dict[str, float],
    ) -> float:
        """Compute overall opportunity score."""
        opp_tags = {"growth", "opportunity", "cooperation", "innovation", "reform"}
        opp_signals = [s for s in signals if set(s.tags) & opp_tags]
        opp_ratio = len(opp_signals) / len(signals) if signals else 0.0

        # Higher lens coverage = more opportunity for insight
        coverage = sum(1 for v in lens_scores.values() if v > 0) / len(GeopoliticalLens)

        return min(1.0, opp_ratio * 0.5 + coverage * 0.5)

    def _recommendations(
        self,
        lens_scores: dict[str, float],
        risk: float,
        opportunity: float,
    ) -> list[str]:
        """Generate strategic recommendations."""
        recs: list[str] = []

        # Identify blind spots (lenses with no data)
        blind_spots = [name for name, v in lens_scores.items() if v == 0.0]
        if blind_spots:
            recs.append(f"Coverage gap: collect signals for {', '.join(blind_spots[:3])}")

        # Risk-based recommendations
        if risk > 0.6:
            recs.append("Elevated risk profile -- recommend defensive positioning")
        elif risk > 0.3:
            recs.append("Moderate risk -- maintain monitoring cadence")

        # Opportunity-based
        if opportunity > 0.5:
            recs.append("Opportunity window detected -- evaluate strategic entry points")

        # Education lens (Jiang Xueqin specialty)
        edu_score = lens_scores.get("education_pipeline", 0.0)
        if edu_score > 0.5:
            recs.append("Education pipeline signals strong -- long-term competitive dynamics shifting")

        return recs


# ── Unified Advisor Engine ─────────────────────────────────────

class JiangXueqinAdvisor:
    """Unified geopolitical advisor engine -- Jiang Xueqin Framework.

    Combines all components into a single entry point:
      - AdvisoryBoard (trusted advisor registry)
      - GeopoliticalPipeline (ongoing data collection)
      - AssessmentEngine (multi-lens strategic analysis)

    Call initialize() to set up the pre-seeded analytical framework.
    """

    # Jiang Xueqin's 6 core lessons
    LESSONS: ClassVar[list[dict[str, str]]] = [
        {
            "id": "L1",
            "name": "innovation_over_imitation",
            "lesson": (
                "A nation that copies will always trail. True competitive "
                "advantage comes from building original innovation ecosystems."
            ),
        },
        {
            "id": "L2",
            "name": "education_as_predictor",
            "lesson": (
                "Education reforms predict geopolitical shifts 10-20 years out. "
                "Track curriculum changes, not just GDP numbers."
            ),
        },
        {
            "id": "L3",
            "name": "bridge_perspectives",
            "lesson": (
                "East and West see through different lenses. The analyst who "
                "bridges both sets gains asymmetric insight."
            ),
        },
        {
            "id": "L4",
            "name": "structural_over_surface",
            "lesson": (
                "Headlines are noise. Structural dynamics -- institutions, "
                "demographics, education pipelines -- are the true signal."
            ),
        },
        {
            "id": "L5",
            "name": "data_driven_narrative",
            "lesson": (
                "Qualitative insight without quantitative backing is opinion. "
                "Quantitative data without narrative is trivia. Combine both."
            ),
        },
        {
            "id": "L6",
            "name": "long_horizon_thinking",
            "lesson": (
                "Geopolitical shifts unfold over decades. Short-termism blinds "
                "analysts to the structural transformations already underway."
            ),
        },
    ]

    def __init__(self) -> None:
        self.board = AdvisoryBoard()
        self.pipeline = GeopoliticalPipeline()
        self.assessment = AssessmentEngine()
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the advisor framework with pre-seeded context."""
        self._initialized = True

        # Pre-seed key geopolitical trends to monitor
        self._seed_trends()

        return {
            "status": "initialized",
            "advisor": "Jiang Xueqin",
            "lessons": len(self.LESSONS),
            "lenses": len(GeopoliticalLens),
            "regions": len(Region) - 1,  # Exclude GLOBAL
            "trends_seeded": len(self.pipeline.trends),
            "board_advisors": len(self.board.advisors),
        }

    def _seed_trends(self) -> None:
        """Seed initial geopolitical trends for monitoring."""
        seed_data = [
            ("china_innovation_index", GeopoliticalLens.INNOVATION_ECOSYSTEM,
             Region.CHINA, "China innovation output (patents, R&D spend)"),
            ("education_reform_momentum", GeopoliticalLens.EDUCATION_PIPELINE,
             Region.CHINA, "China education reform impact on STEM pipeline"),
            ("us_china_tech_decoupling", GeopoliticalLens.TECHNOLOGY_SOVEREIGNTY,
             Region.GLOBAL, "US-China technology decoupling trajectory"),
            ("supply_chain_diversification", GeopoliticalLens.TRADE_SUPPLY_CHAIN,
             Region.ASIA_PACIFIC, "Regional supply chain diversification index"),
            ("cultural_soft_power", GeopoliticalLens.CULTURAL_DIPLOMACY,
             Region.GLOBAL, "Soft power influence metrics"),
        ]

        for trend_id, lens, region, desc in seed_data:
            self.pipeline.track_trend(trend_id, lens, region, desc, 0.5)

    def score_lessons(self, context: dict[str, Any]) -> dict[str, Any]:
        """Score how well the current context applies Jiang Xueqin's lessons.

        context should contain boolean keys matching lesson names:
          - innovation_over_imitation
          - education_as_predictor
          - bridge_perspectives
          - structural_over_surface
          - data_driven_narrative
          - long_horizon_thinking
        """
        met: list[str] = []
        violated: list[str] = []

        for lesson in self.LESSONS:
            key = lesson["name"]
            if context.get(key):
                met.append(key)
            else:
                violated.append(key)

        score = len(met) / len(self.LESSONS) if self.LESSONS else 0.0

        # Grade: S (1.0), A (>=0.8), B (>=0.6), C (>=0.4), D (>=0.2), F (<0.2)
        if score >= 1.0:
            grade = "S"
        elif score >= 0.8:
            grade = "A"
        elif score >= 0.6:
            grade = "B"
        elif score >= 0.4:
            grade = "C"
        elif score >= 0.2:
            grade = "D"
        else:
            grade = "F"

        return {
            "score": round(score, 3),
            "grade": grade,
            "lessons_met": met,
            "lessons_violated": violated,
            "total_lessons": len(self.LESSONS),
        }

    def consult_advisor(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consult Jiang Xueqin directly on a geopolitical question."""
        return self.board.consult("jiang_xueqin", question, context)

    def ingest_signal(
        self,
        source: str,
        region: str | Region,
        lens: str | GeopoliticalLens,
        headline: str,
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ingest a geopolitical signal into the pipeline."""
        if isinstance(region, str):
            region = Region(region)
        if isinstance(lens, str):
            lens = GeopoliticalLens(lens)

        signal = self.pipeline.collect(
            source=source,
            region=region,
            lens=lens,
            headline=headline,
            content=content,
            tags=tags,
        )
        return {
            "status": "signal_ingested",
            "signal_id": signal.signal_id,
            "strength": signal.strength.value,
            "credibility": signal.credibility,
            "region": signal.region.value,
            "lens": signal.lens.value,
        }

    def strategic_assessment(
        self,
        region: str | Region = Region.GLOBAL,
        horizon_years: int = 5,
    ) -> dict[str, Any]:
        """Run a full strategic assessment for a region."""
        if isinstance(region, str):
            region = Region(region)

        signals = (
            self.pipeline.collector.signals_by_region(region)
            if region != Region.GLOBAL
            else self.pipeline.collector.signals
        )

        result = self.assessment.assess(signals, region, horizon_years)
        return {
            "status": "assessed",
            "assessment_id": result.assessment_id,
            "region": result.region.value,
            "lens_scores": result.lens_scores,
            "overall_risk": result.overall_risk,
            "overall_opportunity": result.overall_opportunity,
            "composite": result.compute_composite(),
            "confidence": result.confidence,
            "signal_count": result.signal_count,
            "horizon_years": result.horizon_years,
            "recommendations": result.recommendations,
        }

    def run_pipeline_cycle(self) -> dict[str, Any]:
        """Run a full pipeline cycle -- the ongoing data pipeline."""
        return self.pipeline.run_cycle()

    def operational_readiness(self) -> dict[str, Any]:
        """Assess operational readiness of the advisory system."""
        health = self.pipeline.pipeline_health()
        board = self.board.board_summary()

        # Compute readiness score (7 components)
        checks = [
            self._initialized,
            health["total_signals"] > 0,
            health["cycles_run"] > 0,
            health["lens_coverage"] > 0.3,
            health["region_coverage"] > 0.2,
            len(self.pipeline.trends) > 0,
            board["total_advisors"] > 0,
        ]
        readiness = sum(checks) / len(checks)

        if readiness >= 0.85:
            status = "OPERATIONAL"
        elif readiness >= 0.6:
            status = "DEGRADED"
        elif readiness >= 0.3:
            status = "LIMITED"
        else:
            status = "NOT_READY"

        return {
            "status": status,
            "readiness_score": round(readiness, 3),
            "initialized": self._initialized,
            "components": {
                "pipeline": health["status"],
                "signals": health["total_signals"],
                "trends": health["active_trends"],
                "lens_coverage": round(health["lens_coverage"], 3),
                "region_coverage": round(health["region_coverage"], 3),
                "advisors": board["total_advisors"],
                "advisories_issued": health["advisories_issued"],
            },
        }
