"""Pydantic models for NCL brain service."""

from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum

from pydantic import BaseModel, Field


class PillarType(str, Enum):
    """Pillar types in RESONANCE ENERGY ecosystem."""

    NCL = "ncl"
    NCC = "ncc"
    BRS = "brs"
    AAC = "aac"


class MandateStatus(str, Enum):
    """Mandate lifecycle status."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"  # Awaiting NATRIX review before NCC dispatch
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class CouncilStatus(str, Enum):
    """Council session status."""

    PENDING = "pending"
    DEBATING = "debating"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    FAILED = "failed"


class PumpPrompt(BaseModel):
    """Pump prompt received from iPhone via Grok."""

    prompt_id: str = Field(..., description="Unique pump prompt ID")
    source: str = Field(..., description="Source (e.g., 'grok-iphone')")
    intent: str = Field(..., description="Primary intent of the prompt")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Rich context data from Grok"
    )
    urgency: str = Field(
        default="normal", description="Urgency level (low, normal, high, critical)"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Mandate(BaseModel):
    """Directive mandate for a pillar."""

    mandate_id: str = Field(..., description="Unique mandate ID")
    pillar: PillarType = Field(..., description="Target pillar (NCC, BRS, AAC)")
    priority: int = Field(..., ge=1, le=10, description="Priority 1-10")
    title: str = Field(..., description="Mandate title")
    objective: str = Field(..., description="Strategic objective")
    success_criteria: list[str] = Field(
        default_factory=list, description="Criteria for completion"
    )
    deadline: Optional[datetime] = Field(default=None, description="Target deadline")
    resources: dict[str, Any] = Field(
        default_factory=dict, description="Allocated resources"
    )
    status: MandateStatus = Field(default=MandateStatus.DRAFT)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_pump_id: Optional[str] = Field(
        default=None, description="Originating pump prompt ID"
    )


class CouncilMember(str, Enum):
    """Council member roles."""

    CLAUDE = "claude"
    GROK = "grok"
    GEMINI = "gemini"
    PERPLEXITY = "perplexity"
    GPT = "gpt"
    COPILOT = "copilot"


class CouncilRole(str, Enum):
    """Debate role assigned to each member per session."""

    CHAIR = "chair"          # Claude — moderates, synthesizes, judges
    STRATEGIST = "strategist"  # Grok — first-strike intuition, bold moves
    ANALYST = "analyst"        # Gemini — data-driven, structured analysis
    RESEARCHER = "researcher"  # Perplexity — fact-checking, source-backed
    CREATIVE = "creative"      # GPT — lateral thinking, alternatives
    ENGINEER = "engineer"      # Copilot — technical feasibility, implementation


class DebateRound(BaseModel):
    """Single round of structured debate."""

    round_number: int
    round_type: str = "position"  # position, rebuttal, convergence, final_vote
    responses: dict[str, str] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConsensusScore(BaseModel):
    """Quantified consensus measurement."""

    agreement_pct: float = Field(ge=0.0, le=100.0, default=0.0)
    convergence_delta: float = 0.0  # How much positions shifted toward center
    confidence_weighted: float = 0.0  # Agreement weighted by member confidence
    unanimous: bool = False
    threshold_met: bool = False  # ≥70% agreement = consensus
    dissent_strength: float = 0.0  # 0-100, how strong minority view is


class CouncilSession(BaseModel):
    """Multi-round council debate session."""

    session_id: str = Field(..., description="Unique session ID")
    topic: str = Field(..., description="Debate topic")
    chair: str = Field(default="claude", description="Session chair (always Claude)")
    members: list[CouncilMember] = Field(
        default_factory=lambda: [
            CouncilMember.CLAUDE,
            CouncilMember.GROK,
            CouncilMember.GEMINI,
            CouncilMember.PERPLEXITY,
            CouncilMember.GPT,
            CouncilMember.COPILOT,
        ],
        description="Debate members",
    )
    role_assignments: dict[str, str] = Field(
        default_factory=dict, description="Member → CouncilRole mapping"
    )
    status: CouncilStatus = Field(default=CouncilStatus.PENDING)
    prompt: str = Field(..., description="Chair's prompt to members")
    rounds: list[DebateRound] = Field(default_factory=list, description="Debate rounds")
    responses: dict[str, str] = Field(
        default_factory=dict, description="Final member positions (last round)"
    )
    synthesis: Optional[str] = Field(
        default=None, description="Chair's final synthesis"
    )
    consensus: Optional[str] = Field(default=None, description="Consensus reached")
    consensus_score: Optional[ConsensusScore] = Field(default=None)
    dissents: list[str] = Field(default_factory=list, description="Minority views")
    recommendations: list[str] = Field(default_factory=list, description="Action items")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
    protocol: str = Field(default="delphi-mad", description="Debate protocol used")


class FeedbackReport(BaseModel):
    """Feedback report from downstream pillar."""

    report_id: str = Field(..., description="Unique report ID")
    origin: PillarType = Field(
        ..., description="Originating pillar (NCC, BRS, AAC, UNI)"
    )
    report_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content: str = Field(..., description="Feedback narrative")
    signals: dict[str, Any] = Field(
        default_factory=dict, description="Structured signal data"
    )
    lessons: list[str] = Field(default_factory=list, description="Key lessons")
    recommendations: list[str] = Field(
        default_factory=list, description="Recommendations for NCL"
    )
    related_mandates: list[str] = Field(
        default_factory=list, description="Mandate IDs this feedback relates to"
    )


class MemUnit(BaseModel):
    """Memory unit - semantic building block of NCL memory."""

    unit_id: str = Field(..., description="Unique memory unit ID")
    content: str = Field(..., description="Memory content")
    source: str = Field(..., description="Source of memory (e.g., council output)")
    importance: float = Field(
        ge=0.0, le=100.0, default=50.0, description="Importance score 0-100"
    )
    decay_rate: float = Field(
        ge=0.0, le=1.0, default=0.95, description="Daily decay multiplier"
    )
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reinforcement_count: int = Field(
        ge=0, default=0, description="Times accessed/reinforced"
    )
    tags: list[str] = Field(default_factory=list, description="Search tags")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    related_units: list[str] = Field(
        default_factory=list, description="Related memory unit IDs"
    )


class InsightSignal(BaseModel):
    """Signal from Awarebot scanner."""

    signal_id: str = Field(..., description="Unique signal ID")
    source_platform: str = Field(..., description="Source (x, youtube, reddit)")
    content: str = Field(..., description="Signal content/summary")
    url: Optional[str] = Field(default=None, description="Source URL")
    importance_score: float = Field(
        ge=0.0, le=100.0, description="Computed importance 0-100"
    )
    relevance: float = Field(ge=0.0, le=1.0, description="Relevance component")
    novelty: float = Field(ge=0.0, le=1.0, description="Novelty component")
    actionability: float = Field(ge=0.0, le=1.0, description="Actionability component")
    source_authority: float = Field(ge=0.0, le=1.0, description="Authority component")
    time_sensitivity: float = Field(ge=0.0, le=1.0, description="Time sensitivity")
    trend: Optional[str] = Field(
        default=None, description="Trend direction (rising, stable, declining)"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list, description="Signal tags")


class CouncilOutput(BaseModel):
    """Output from council session."""

    session_id: str
    topic: str
    consensus: Optional[str]
    dissents: list[str]
    recommendations: list[str]
    synthesis: Optional[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
