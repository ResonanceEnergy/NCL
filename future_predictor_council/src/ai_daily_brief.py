"""AI Daily Brief & Exponential Intelligence Engine.

Integrates two leading AI/technology intelligence sources:

1. **The AI Daily Brief: Artificial Intelligence** (Nathaniel Whittemore / NLW)
   — Daily AI news analysis covering policy, safety, industry moves, model
   releases, regulation, business impact, and geopolitics of AI.

2. **Peter H. Diamandis** — Exponential technologies, abundance mindset,
   6 D's of Exponentials, longevity, XPRIZE, Singularity University,
   Massively Transformative Purpose (MTP), and metatrend analysis.

The engine captures, analyzes, and synthesizes intelligence from both
channels into actionable briefings for the Future Predictor Council.

Key Frameworks Integrated:
- NLW's AI Signal Taxonomy (policy / safety / industry / models / regulation)
- Diamandis 6 D's of Exponentials (Digitize → Deceptive → Disruptive →
  Demonetize → Dematerialize → Democratize)
- Abundance Thinking (fixed-pie vs abundance mindset)
- Convergence Analysis (AI + Robotics + Biotech + Nanotech + Networks)
- Metatrend Tracking (20-year macro forces)
- Moonshot / 10x Thinking (10x improvement over 10% improvement)
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ── Enums ──────────────────────────────────────────────────────


class BriefingCategory(StrEnum):
    """AI Daily Brief signal categories (NLW taxonomy)."""

    AI_POLICY = "ai_policy"
    AI_SAFETY = "ai_safety"
    AI_INDUSTRY = "ai_industry"
    AI_MODELS = "ai_models"
    AI_REGULATION = "ai_regulation"
    AI_BUSINESS = "ai_business"
    AI_GEOPOLITICS = "ai_geopolitics"
    AI_RESEARCH = "ai_research"
    AI_OPEN_SOURCE = "ai_open_source"
    AI_ETHICS = "ai_ethics"


class ExponentialStage(StrEnum):
    """Diamandis 6 D's of Exponentials."""

    DIGITIZED = "digitized"
    DECEPTIVE = "deceptive"
    DISRUPTIVE = "disruptive"
    DEMONETIZED = "demonetized"
    DEMATERIALIZED = "dematerialized"
    DEMOCRATIZED = "democratized"


class TechnologyDomain(StrEnum):
    """Convergent technology domains (Diamandis framework)."""

    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"
    ROBOTICS = "robotics"
    BIOTECHNOLOGY = "biotechnology"
    NANOTECHNOLOGY = "nanotechnology"
    NETWORKS_COMPUTING = "networks_computing"
    THREE_D_PRINTING = "three_d_printing"
    AUGMENTED_REALITY = "augmented_reality"
    BLOCKCHAIN = "blockchain"
    QUANTUM_COMPUTING = "quantum_computing"
    LONGEVITY = "longevity"


class InsightTier(StrEnum):
    """Insight urgency / impact classification."""

    BACKGROUND = "background"
    NOTABLE = "notable"
    SIGNIFICANT = "significant"
    BREAKTHROUGH = "breakthrough"
    PARADIGM_SHIFT = "paradigm_shift"


class ConvergenceType(StrEnum):
    """How technologies converge."""

    SEQUENTIAL = "sequential"            # One enables the next
    PARALLEL = "parallel"                # Simultaneous advances
    SYNERGISTIC = "synergistic"          # 1 + 1 > 2
    CATALYTIC = "catalytic"              # One accelerates another
    DISRUPTIVE_CONVERGENCE = "disruptive_convergence"  # Combined effect disrupts


class AbundanceDomain(StrEnum):
    """Abundance framework application domains."""

    ENERGY = "energy"
    FOOD = "food"
    WATER = "water"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    INFORMATION = "information"
    TRANSPORTATION = "transportation"
    COMMUNICATION = "communication"


# ── Dataclasses ────────────────────────────────────────────────


@dataclass
class AIBriefing:
    """A single AI Daily Brief intelligence item."""

    briefing_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    source: str = "ai_daily_brief"
    category: BriefingCategory = BriefingCategory.AI_INDUSTRY
    tier: InsightTier = InsightTier.NOTABLE
    headline: str = ""
    analysis: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    implications: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        raw = f"{self.title}|{self.source}|{self.category}|{sorted(self.tags)}"
        self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self.fingerprint


@dataclass
class ExponentialSignal:
    """A technology signal tracked via the 6 D's framework."""

    signal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    technology: TechnologyDomain = TechnologyDomain.ARTIFICIAL_INTELLIGENCE
    stage: ExponentialStage = ExponentialStage.DIGITIZED
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    velocity: float = 0.0          # Rate of progression through stages
    impact_score: float = 0.0      # 0.0 - 1.0
    domains_affected: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def advance_stage(self) -> ExponentialStage:
        """Move to next stage in the 6 D's progression."""
        stages = list(ExponentialStage)
        current_idx = stages.index(self.stage)
        if current_idx < len(stages) - 1:
            self.stage = stages[current_idx + 1]
        return self.stage

    def score_impact(self) -> float:
        """Score based on stage progression and evidence weight."""
        stage_weight = (list(ExponentialStage).index(self.stage) + 1) / 6.0
        evidence_bonus = min(1.0, len(self.evidence) * 0.15)
        self.impact_score = round(
            (stage_weight * 0.6 + evidence_bonus * 0.4), 4,
        )
        return self.impact_score


@dataclass
class ConvergenceEvent:
    """A convergence of multiple technologies creating amplified impact."""

    convergence_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    technologies: list[TechnologyDomain] = field(default_factory=list)
    convergence_type: ConvergenceType = ConvergenceType.PARALLEL
    description: str = ""
    impact_multiplier: float = 1.0
    abundance_potential: float = 0.0
    timeline_years: int = 5
    evidence: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def compute_multiplier(self) -> float:
        """Calculate convergence multiplier."""
        tech_count_bonus = len(self.technologies) * 0.3
        type_weights: dict[str, float] = {
            ConvergenceType.SEQUENTIAL: 1.0,
            ConvergenceType.PARALLEL: 1.2,
            ConvergenceType.SYNERGISTIC: 1.5,
            ConvergenceType.CATALYTIC: 1.8,
            ConvergenceType.DISRUPTIVE_CONVERGENCE: 2.0,
        }
        type_weight = type_weights.get(self.convergence_type, 1.0)
        self.impact_multiplier = round(type_weight + tech_count_bonus, 4)
        return self.impact_multiplier


@dataclass
class AbundanceAssessment:
    """Assessment of abundance potential in a domain."""

    assessment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    domain: AbundanceDomain = AbundanceDomain.INFORMATION
    current_scarcity: float = 0.5        # 0 = abundant, 1 = extreme scarcity
    abundance_trajectory: float = 0.0    # Rate of movement toward abundance
    enabling_technologies: list[TechnologyDomain] = field(default_factory=list)
    barriers: list[str] = field(default_factory=list)
    enablers: list[str] = field(default_factory=list)
    moonshot_ideas: list[str] = field(default_factory=list)
    timeline_years: int = 10
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)

    def abundance_score(self) -> float:
        """Compute abundance score from scarcity and trajectory."""
        base = 1.0 - self.current_scarcity
        tech_bonus = min(0.3, len(self.enabling_technologies) * 0.05)
        return round(min(1.0, base + self.abundance_trajectory + tech_bonus), 4)


@dataclass
class BriefingDigest:
    """Aggregated daily digest from both channels."""

    digest_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    date: str = ""
    briefing_count: int = 0
    exponential_signals: int = 0
    convergences_detected: int = 0
    top_category: str = ""
    key_insights: list[str] = field(default_factory=list)
    abundance_opportunities: list[str] = field(default_factory=list)
    moonshots: list[str] = field(default_factory=list)
    overall_tempo: str = "normal"     # quiet / normal / accelerating / breakneck
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)


@dataclass
class Metatrend:
    """A macro-level trend spanning 10-20+ years (Diamandis metatrends)."""

    trend_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    horizon_years: int = 20
    contributing_technologies: list[TechnologyDomain] = field(default_factory=list)
    momentum: float = 0.0            # -1.0 decelerating to 1.0 accelerating
    evidence_count: int = 0
    implications: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class MoonshotIdea:
    """A 10x improvement idea (Diamandis moonshot thinking)."""

    idea_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    domain: AbundanceDomain = AbundanceDomain.INFORMATION
    current_baseline: str = ""
    ten_x_target: str = ""
    enabling_convergences: list[str] = field(default_factory=list)
    feasibility: float = 0.3
    impact_potential: float = 0.5
    mtp_alignment: float = 0.0       # Alignment with Massively Transformative Purpose
    timestamp: float = field(default_factory=time.time)

    def moonshot_score(self) -> float:
        """Score combining feasibility, impact, and MTP alignment."""
        raw = (self.feasibility * 0.3 + self.impact_potential * 0.4
               + self.mtp_alignment * 0.3)
        return round(min(1.0, raw), 4)


# ── Engine Classes ─────────────────────────────────────────────


class BriefingCollector:
    """Ingest and classify AI Daily Brief signals.

    Implements NLW's AI Signal Taxonomy with deduplication
    and tiered classification.
    """

    def __init__(self) -> None:
        self.briefings: dict[str, AIBriefing] = {}
        self.category_counts: dict[str, int] = {}
        self.fingerprints: set[str] = set()

    def ingest(
        self,
        title: str,
        headline: str,
        category: BriefingCategory,
        analysis: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        tier: InsightTier = InsightTier.NOTABLE,
        source: str = "ai_daily_brief",
    ) -> AIBriefing:
        """Ingest a new briefing signal."""
        briefing = AIBriefing(
            title=title,
            source=source,
            category=category,
            tier=tier,
            headline=headline,
            analysis=analysis,
            content=content or {},
            tags=tags or [],
        )
        fp = briefing.compute_fingerprint()

        # Deduplication
        if fp in self.fingerprints:
            return briefing

        self.fingerprints.add(fp)
        self.briefings[briefing.briefing_id] = briefing
        cat_key = str(category)
        self.category_counts[cat_key] = self.category_counts.get(cat_key, 0) + 1
        return briefing

    def get_by_category(self, category: BriefingCategory) -> list[AIBriefing]:
        """Retrieve briefings filtered by category."""
        return [b for b in self.briefings.values() if b.category == category]

    def get_by_tier(self, tier: InsightTier) -> list[AIBriefing]:
        """Retrieve briefings at or above a given tier."""
        tiers = list(InsightTier)
        min_idx = tiers.index(tier)
        return [b for b in self.briefings.values()
                if tiers.index(b.tier) >= min_idx]

    def top_category(self) -> str:
        """Return the category with most briefings."""
        if not self.category_counts:
            return ""
        return max(self.category_counts, key=self.category_counts.get)  # type: ignore[arg-type]

    def stats(self) -> dict[str, Any]:
        """Summary statistics."""
        return {
            "total_briefings": len(self.briefings),
            "category_distribution": dict(self.category_counts),
            "top_category": self.top_category(),
            "unique_fingerprints": len(self.fingerprints),
        }


class ExponentialTracker:
    """Track technologies through Diamandis's 6 D's progression.

    Each technology moves: Digitized → Deceptive → Disruptive →
    Demonetized → Dematerialized → Democratized.
    """

    def __init__(self) -> None:
        self.signals: dict[str, ExponentialSignal] = {}
        self.stage_history: dict[str, list[tuple[str, float]]] = {}

    def track(
        self,
        technology: TechnologyDomain,
        stage: ExponentialStage,
        description: str = "",
        evidence: list[str] | None = None,
    ) -> ExponentialSignal:
        """Track a new exponential signal."""
        signal = ExponentialSignal(
            technology=technology,
            stage=stage,
            description=description,
            evidence=evidence or [],
        )
        signal.score_impact()
        self.signals[signal.signal_id] = signal

        tech_key = str(technology)
        if tech_key not in self.stage_history:
            self.stage_history[tech_key] = []
        self.stage_history[tech_key].append((str(stage), time.time()))

        return signal

    def get_by_technology(self, tech: TechnologyDomain) -> list[ExponentialSignal]:
        """Get all signals for a technology."""
        return [s for s in self.signals.values() if s.technology == tech]

    def get_by_stage(self, stage: ExponentialStage) -> list[ExponentialSignal]:
        """Get signals at a given stage."""
        return [s for s in self.signals.values() if s.stage == stage]

    def furthest_stage(self, tech: TechnologyDomain) -> ExponentialStage | None:
        """Find the furthest stage reached by a technology."""
        tech_signals = self.get_by_technology(tech)
        if not tech_signals:
            return None
        stages = list(ExponentialStage)
        max_idx = max(stages.index(s.stage) for s in tech_signals)
        return stages[max_idx]

    def velocity(self, tech: TechnologyDomain) -> float:
        """Estimate velocity of progression through stages."""
        history = self.stage_history.get(str(tech), [])
        if len(history) < 2:
            return 0.0
        time_span = history[-1][1] - history[0][1]
        if time_span == 0:
            return 0.0
        return round(len(history) / time_span, 6)

    def stats(self) -> dict[str, Any]:
        """Summary statistics."""
        return {
            "total_signals": len(self.signals),
            "technologies_tracked": len(self.stage_history),
            "stage_distribution": {
                str(stage): len(self.get_by_stage(stage))
                for stage in ExponentialStage
            },
        }


class ConvergenceAnalyzer:
    """Detect and score technology convergences.

    Identifies when multiple technologies converge to create
    amplified impact (Diamandis convergence thesis).
    """

    def __init__(self) -> None:
        self.convergences: dict[str, ConvergenceEvent] = {}

    def detect(
        self,
        technologies: list[TechnologyDomain],
        convergence_type: ConvergenceType = ConvergenceType.PARALLEL,
        description: str = "",
        timeline_years: int = 5,
        evidence: list[str] | None = None,
    ) -> ConvergenceEvent:
        """Record a convergence event."""
        event = ConvergenceEvent(
            technologies=technologies,
            convergence_type=convergence_type,
            description=description,
            timeline_years=timeline_years,
            evidence=evidence or [],
        )
        event.compute_multiplier()
        self.convergences[event.convergence_id] = event
        return event

    def get_by_technology(self, tech: TechnologyDomain) -> list[ConvergenceEvent]:
        """Find convergences involving a specific technology."""
        return [c for c in self.convergences.values() if tech in c.technologies]

    def highest_impact(self, n: int = 5) -> list[ConvergenceEvent]:
        """Return top-N convergences by impact multiplier."""
        sorted_events = sorted(
            self.convergences.values(),
            key=lambda c: c.impact_multiplier,
            reverse=True,
        )
        return sorted_events[:n]

    def stats(self) -> dict[str, Any]:
        """Summary statistics."""
        avg_multiplier = 0.0
        if self.convergences:
            avg_multiplier = round(
                sum(c.impact_multiplier for c in self.convergences.values())
                / len(self.convergences), 4,
            )
        return {
            "total_convergences": len(self.convergences),
            "avg_impact_multiplier": avg_multiplier,
            "type_distribution": {
                str(ct): sum(1 for c in self.convergences.values()
                             if c.convergence_type == ct)
                for ct in ConvergenceType
            },
        }


class AbundanceScorer:
    """Score abundance potential across domains.

    Implements Diamandis's abundance framework: identify where
    technology converts scarcity to abundance.
    """

    def __init__(self) -> None:
        self.assessments: dict[str, AbundanceAssessment] = {}

    def assess(
        self,
        domain: AbundanceDomain,
        current_scarcity: float = 0.5,
        enabling_technologies: list[TechnologyDomain] | None = None,
        barriers: list[str] | None = None,
        enablers: list[str] | None = None,
        moonshot_ideas: list[str] | None = None,
        timeline_years: int = 10,
    ) -> AbundanceAssessment:
        """Create an abundance assessment for a domain."""
        assessment = AbundanceAssessment(
            domain=domain,
            current_scarcity=current_scarcity,
            enabling_technologies=enabling_technologies or [],
            barriers=barriers or [],
            enablers=enablers or [],
            moonshot_ideas=moonshot_ideas or [],
            timeline_years=timeline_years,
        )
        # Compute trajectory from enablers vs barriers ratio
        enabler_weight = len(assessment.enablers)
        barrier_weight = len(assessment.barriers)
        total = enabler_weight + barrier_weight
        if total > 0:
            assessment.abundance_trajectory = round(
                (enabler_weight - barrier_weight) / total * 0.5, 4,
            )
        assessment.confidence = round(min(1.0, total * 0.1), 4)
        self.assessments[assessment.assessment_id] = assessment
        return assessment

    def get_by_domain(self, domain: AbundanceDomain) -> list[AbundanceAssessment]:
        """Get assessments for a domain."""
        return [a for a in self.assessments.values() if a.domain == domain]

    def most_abundant(self) -> AbundanceAssessment | None:
        """Return domain closest to abundance."""
        if not self.assessments:
            return None
        return max(self.assessments.values(), key=lambda a: a.abundance_score())

    def most_scarce(self) -> AbundanceAssessment | None:
        """Return domain with highest scarcity."""
        if not self.assessments:
            return None
        return max(self.assessments.values(), key=lambda a: a.current_scarcity)

    def stats(self) -> dict[str, Any]:
        """Summary statistics."""
        return {
            "total_assessments": len(self.assessments),
            "domains_assessed": len({str(a.domain) for a in self.assessments.values()}),
            "avg_abundance_score": round(
                sum(a.abundance_score() for a in self.assessments.values())
                / max(1, len(self.assessments)), 4,
            ),
        }


class MetatrendEngine:
    """Track macro-level metatrends spanning decades.

    Diamandis identifies 20+ metatrends reshaping civilization.
    This engine monitors their momentum and implications.
    """

    def __init__(self) -> None:
        self.trends: dict[str, Metatrend] = {}

    def register(
        self,
        name: str,
        description: str,
        contributing_technologies: list[TechnologyDomain] | None = None,
        horizon_years: int = 20,
    ) -> Metatrend:
        """Register a new metatrend."""
        trend = Metatrend(
            name=name,
            description=description,
            contributing_technologies=contributing_technologies or [],
            horizon_years=horizon_years,
        )
        self.trends[trend.trend_id] = trend
        return trend

    def add_evidence(self, trend_id: str, implication: str) -> bool:
        """Add evidence / implication to a trend."""
        if trend_id not in self.trends:
            return False
        trend = self.trends[trend_id]
        trend.evidence_count += 1
        trend.implications.append(implication)
        # Adjust momentum based on evidence accumulation
        trend.momentum = round(min(1.0, trend.evidence_count * 0.1), 4)
        return True

    def accelerating(self) -> list[Metatrend]:
        """Return trends with positive momentum."""
        return [t for t in self.trends.values() if t.momentum > 0]

    def by_technology(self, tech: TechnologyDomain) -> list[Metatrend]:
        """Find metatrends involving a technology."""
        return [t for t in self.trends.values()
                if tech in t.contributing_technologies]

    def stats(self) -> dict[str, Any]:
        return {
            "total_trends": len(self.trends),
            "accelerating_count": len(self.accelerating()),
            "avg_momentum": round(
                sum(t.momentum for t in self.trends.values())
                / max(1, len(self.trends)), 4,
            ),
        }


class MoonshotFactory:
    """Generate and score moonshot ideas.

    Applies Diamandis's 10x thinking: aim for 10x improvement
    rather than 10%, which forces rethinking from first principles.
    """

    def __init__(self) -> None:
        self.ideas: dict[str, MoonshotIdea] = {}

    def create(
        self,
        title: str,
        domain: AbundanceDomain,
        current_baseline: str = "",
        ten_x_target: str = "",
        enabling_convergences: list[str] | None = None,
        mtp_alignment: float = 0.5,
    ) -> MoonshotIdea:
        """Create a new moonshot idea."""
        idea = MoonshotIdea(
            title=title,
            domain=domain,
            current_baseline=current_baseline,
            ten_x_target=ten_x_target,
            enabling_convergences=enabling_convergences or [],
            mtp_alignment=mtp_alignment,
        )
        # Feasibility correlates with number of enabling convergences
        idea.feasibility = round(min(1.0, len(idea.enabling_convergences) * 0.2), 4)
        # Impact potential based on domain scarcity gap
        idea.impact_potential = round(min(1.0, 0.3 + mtp_alignment * 0.5), 4)
        self.ideas[idea.idea_id] = idea
        return idea

    def top_moonshots(self, n: int = 5) -> list[MoonshotIdea]:
        """Return top-N moonshots by composite score."""
        return sorted(
            self.ideas.values(),
            key=lambda m: m.moonshot_score(),
            reverse=True,
        )[:n]

    def by_domain(self, domain: AbundanceDomain) -> list[MoonshotIdea]:
        """Get moonshots for a domain."""
        return [m for m in self.ideas.values() if m.domain == domain]

    def stats(self) -> dict[str, Any]:
        return {
            "total_moonshots": len(self.ideas),
            "avg_moonshot_score": round(
                sum(m.moonshot_score() for m in self.ideas.values())
                / max(1, len(self.ideas)), 4,
            ),
            "domains_covered": len({str(m.domain) for m in self.ideas.values()}),
        }


# ── Lessons Learned Integration ────────────────────────────────


# Key lessons distilled from both channels
NLW_LESSONS: list[dict[str, str]] = [
    {
        "lesson": "velocity_matters",
        "source": "AI Daily Brief",
        "insight": (
            "AI development velocity is the primary strategic variable. "
            "Track release cadence, not just capability. Weekly model updates "
            "compound into paradigm shifts within quarters."
        ),
    },
    {
        "lesson": "policy_lags_technology",
        "source": "AI Daily Brief",
        "insight": (
            "Regulation consistently lags AI capability by 12-24 months. "
            "This creates windows of opportunity and risk that the council "
            "must anticipate, not react to."
        ),
    },
    {
        "lesson": "open_source_equalizer",
        "source": "AI Daily Brief",
        "insight": (
            "Open-source AI models democratize capability faster than any "
            "single company can ship. Track Meta/Llama, Mistral, and community "
            "fine-tunes as leading indicators of commoditization."
        ),
    },
    {
        "lesson": "safety_alignment_tension",
        "source": "AI Daily Brief",
        "insight": (
            "The tension between AI acceleration and safety/alignment is "
            "the defining dynamic of the era. Neither side can be ignored; "
            "the council must model both trajectories simultaneously."
        ),
    },
    {
        "lesson": "inference_cost_deflation",
        "source": "AI Daily Brief",
        "insight": (
            "AI inference costs deflate at 10x per 18 months. Applications "
            "that are economically impossible today become trivial within "
            "2-3 years. Price intelligence before capability intelligence."
        ),
    },
]


DIAMANDIS_LESSONS: list[dict[str, str]] = [
    {
        "lesson": "six_ds_inevitable",
        "source": "Peter H. Diamandis",
        "insight": (
            "Once a technology is digitized, it enters the 6 D's pipeline "
            "inevitably: Deceptive growth → Disruptive breakthrough → "
            "Demonetization → Dematerialization → Democratization. "
            "Track the stage, not the hype."
        ),
    },
    {
        "lesson": "abundance_over_scarcity",
        "source": "Peter H. Diamandis",
        "insight": (
            "Scarcity thinking is a cognitive bias. Technology converts "
            "scarcity to abundance in domain after domain — energy, food, "
            "water, healthcare, education. Bet on abundance trajectories."
        ),
    },
    {
        "lesson": "convergence_amplifies",
        "source": "Peter H. Diamandis",
        "insight": (
            "The convergence of AI + robotics + biotech + nanotech + networks "
            "creates impact far greater than any single technology. The most "
            "disruptive innovations live at convergence boundaries."
        ),
    },
    {
        "lesson": "ten_x_over_ten_percent",
        "source": "Peter H. Diamandis",
        "insight": (
            "Aiming for 10x improvement forces you to rethink from first "
            "principles. 10% improvement traps you in incremental optimization. "
            "Moonshot thinking generates breakthroughs."
        ),
    },
    {
        "lesson": "mtp_drives_everything",
        "source": "Peter H. Diamandis",
        "insight": (
            "A Massively Transformative Purpose (MTP) is the gravitational "
            "core of exponential organizations. Without MTP, technology is "
            "directionless. With MTP, teams achieve 10x outcomes."
        ),
    },
    {
        "lesson": "longevity_escape_velocity",
        "source": "Peter H. Diamandis",
        "insight": (
            "Longevity Escape Velocity — where science extends life faster "
            "than time passes — is approaching. AI accelerates drug discovery, "
            "genomics, and regenerative medicine toward this threshold."
        ),
    },
    {
        "lesson": "crowd_over_expert",
        "source": "Peter H. Diamandis",
        "insight": (
            "Incentive competitions (XPRIZE model) unlock solutions from "
            "unexpected sources. The crowd often outperforms the expert. "
            "Design systems that harness collective intelligence."
        ),
    },
]


ALL_LESSONS = NLW_LESSONS + DIAMANDIS_LESSONS


# ── Unified Engine ─────────────────────────────────────────────


class AIDailyBriefEngine:
    """Unified engine integrating both channels.

    Combines NLW's daily AI intelligence with Diamandis's
    exponential technology frameworks into a single briefing
    and analysis pipeline.
    """

    def __init__(self) -> None:
        self.collector = BriefingCollector()
        self.tracker = ExponentialTracker()
        self.convergence = ConvergenceAnalyzer()
        self.abundance = AbundanceScorer()
        self.metatrends = MetatrendEngine()
        self.moonshots = MoonshotFactory()
        self._initialized = False

    def initialize(self) -> None:
        """Bootstrap the engine."""
        self._initialized = True

    def ingest_briefing(
        self,
        title: str,
        headline: str,
        category: BriefingCategory,
        analysis: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        tier: InsightTier = InsightTier.NOTABLE,
        source: str = "ai_daily_brief",
    ) -> dict[str, Any]:
        """Ingest an AI Daily Brief signal."""
        briefing = self.collector.ingest(
            title, headline, category, analysis, content, tags, tier, source,
        )
        return {
            "briefing_id": briefing.briefing_id,
            "category": str(briefing.category),
            "tier": str(briefing.tier),
            "fingerprint": briefing.fingerprint,
        }

    def track_exponential(
        self,
        technology: TechnologyDomain,
        stage: ExponentialStage,
        description: str = "",
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """Track a technology signal through the 6 D's."""
        signal = self.tracker.track(technology, stage, description, evidence)
        return {
            "signal_id": signal.signal_id,
            "technology": str(signal.technology),
            "stage": str(signal.stage),
            "impact_score": signal.impact_score,
        }

    def detect_convergence(
        self,
        technologies: list[TechnologyDomain],
        convergence_type: ConvergenceType = ConvergenceType.PARALLEL,
        description: str = "",
        timeline_years: int = 5,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """Detect and record a technology convergence."""
        event = self.convergence.detect(
            technologies, convergence_type, description, timeline_years, evidence,
        )
        return {
            "convergence_id": event.convergence_id,
            "technologies": [str(t) for t in event.technologies],
            "type": str(event.convergence_type),
            "impact_multiplier": event.impact_multiplier,
        }

    def assess_abundance(
        self,
        domain: AbundanceDomain,
        current_scarcity: float = 0.5,
        enabling_technologies: list[TechnologyDomain] | None = None,
        barriers: list[str] | None = None,
        enablers: list[str] | None = None,
        moonshot_ideas: list[str] | None = None,
        timeline_years: int = 10,
    ) -> dict[str, Any]:
        """Assess abundance potential for a domain."""
        assessment = self.abundance.assess(
            domain, current_scarcity, enabling_technologies,
            barriers, enablers, moonshot_ideas, timeline_years,
        )
        return {
            "assessment_id": assessment.assessment_id,
            "domain": str(assessment.domain),
            "abundance_score": assessment.abundance_score(),
            "trajectory": assessment.abundance_trajectory,
            "confidence": assessment.confidence,
        }

    def register_metatrend(
        self,
        name: str,
        description: str,
        contributing_technologies: list[TechnologyDomain] | None = None,
        horizon_years: int = 20,
    ) -> dict[str, Any]:
        """Register a macro metatrend."""
        trend = self.metatrends.register(
            name, description, contributing_technologies, horizon_years,
        )
        return {
            "trend_id": trend.trend_id,
            "name": trend.name,
            "horizon_years": trend.horizon_years,
        }

    def create_moonshot(
        self,
        title: str,
        domain: AbundanceDomain,
        current_baseline: str = "",
        ten_x_target: str = "",
        enabling_convergences: list[str] | None = None,
        mtp_alignment: float = 0.5,
    ) -> dict[str, Any]:
        """Create a moonshot idea."""
        idea = self.moonshots.create(
            title, domain, current_baseline, ten_x_target,
            enabling_convergences, mtp_alignment,
        )
        return {
            "idea_id": idea.idea_id,
            "title": idea.title,
            "moonshot_score": idea.moonshot_score(),
            "feasibility": idea.feasibility,
            "impact_potential": idea.impact_potential,
        }

    def generate_digest(self, date: str = "") -> dict[str, Any]:
        """Generate a daily digest combining both channels."""
        collector_stats = self.collector.stats()
        tracker_stats = self.tracker.stats()
        convergence_stats = self.convergence.stats()

        # Determine tempo
        briefing_count = collector_stats["total_briefings"]
        if briefing_count == 0:
            tempo = "quiet"
        elif briefing_count <= 3:
            tempo = "normal"
        elif briefing_count <= 7:
            tempo = "accelerating"
        else:
            tempo = "breakneck"

        digest = BriefingDigest(
            date=date or "today",
            briefing_count=briefing_count,
            exponential_signals=tracker_stats["total_signals"],
            convergences_detected=convergence_stats["total_convergences"],
            top_category=collector_stats["top_category"],
            overall_tempo=tempo,
        )

        return {
            "digest_id": digest.digest_id,
            "date": digest.date,
            "briefing_count": digest.briefing_count,
            "exponential_signals": digest.exponential_signals,
            "convergences_detected": digest.convergences_detected,
            "top_category": digest.top_category,
            "tempo": digest.overall_tempo,
        }

    def query_lessons(
        self,
        source: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        """Query integrated lessons from both channels."""
        filtered = ALL_LESSONS
        if source:
            source_lower = source.lower()
            filtered = [
                lsn for lsn in filtered
                if source_lower in lsn["source"].lower()
            ]
        if keyword:
            kw_lower = keyword.lower()
            filtered = [
                lsn for lsn in filtered
                if kw_lower in lsn["insight"].lower()
                or kw_lower in lsn["lesson"].lower()
            ]
        return {
            "lessons_found": len(filtered),
            "lessons": [
                {"lesson": lsn["lesson"], "source": lsn["source"]}
                for lsn in filtered
            ],
        }

    def score_lessons(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Score how well the council applies the integrated lessons."""
        scores: dict[str, float] = {}
        ctx = context or {}

        for lesson_data in ALL_LESSONS:
            lesson = lesson_data["lesson"]
            # Each lesson scores 1.0 if context mentions it, 0.5 baseline
            if lesson in ctx:
                scores[lesson] = min(1.0, float(ctx[lesson]))
            else:
                scores[lesson] = 0.5

        avg_score = sum(scores.values()) / max(1, len(scores))
        return {
            "lesson_scores": scores,
            "avg_compliance": round(avg_score, 4),
            "total_lessons": len(ALL_LESSONS),
            "nlw_lessons": len(NLW_LESSONS),
            "diamandis_lessons": len(DIAMANDIS_LESSONS),
        }

    def full_pipeline(
        self,
        title: str,
        headline: str,
        category: BriefingCategory,
        technology: TechnologyDomain | None = None,
        stage: ExponentialStage | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline: ingest → track → analyze → digest."""
        # Step 1: Ingest briefing
        brief_result = self.ingest_briefing(
            title=title,
            headline=headline,
            category=category,
            tags=tags,
        )

        # Step 2: Track exponential if technology provided
        exp_result: dict[str, Any] = {}
        if technology and stage:
            exp_result = self.track_exponential(
                technology=technology,
                stage=stage,
                description=headline,
            )

        # Step 3: Generate digest
        digest_result = self.generate_digest()

        return {
            "briefing": brief_result,
            "exponential": exp_result,
            "digest": digest_result,
            "pipeline": "complete",
        }

    def operational_readiness(self) -> dict[str, Any]:
        """Check engine readiness."""
        return {
            "engine": "ai_daily_brief",
            "initialized": self._initialized,
            "collector_stats": self.collector.stats(),
            "tracker_stats": self.tracker.stats(),
            "convergence_stats": self.convergence.stats(),
            "abundance_stats": self.abundance.stats(),
            "metatrend_stats": self.metatrends.stats(),
            "moonshot_stats": self.moonshots.stats(),
            "lessons_integrated": len(ALL_LESSONS),
            "nlw_lessons": len(NLW_LESSONS),
            "diamandis_lessons": len(DIAMANDIS_LESSONS),
        }
