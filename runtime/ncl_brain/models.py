"""Pydantic models for NCL brain service."""

from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum
import uuid as _uuid

from pydantic import BaseModel, Field


# ── Event Schema v1 ──────────────────────────────────────────────────────────


class EventType(str, Enum):
    """Canonical NCL event types."""

    # Lifecycle
    STARTUP = "startup"
    SHUTDOWN = "shutdown"

    # Pump flow
    PUMP_RECEIVED = "pump_received"
    PUMP_APPROVED = "pump_approved"
    PUMP_REJECTED = "pump_rejected"

    # Council
    COUNCIL_SPAWNED = "council_spawned"
    COUNCIL_ROUND = "council_round"
    COUNCIL_COMPLETED = "council_completed"
    COUNCIL_FAILED = "council_failed"

    # Strike Point pipeline
    STRIKE_COUNCIL_COMPLETE = "strike_council_complete"
    STRIKE_PENDING_APPROVAL = "strike_pending_approval"
    STRIKE_APPROVED_DISPATCHED = "strike_approved_dispatched"
    STRIKE_REJECTED = "strike_rejected"

    # Mandates
    MANDATE_CREATED = "mandate_created"
    MANDATE_DISPATCHED = "mandate_dispatched"
    MANDATE_COMPLETED = "mandate_completed"
    MANDATE_CANCELLED = "mandate_cancelled"

    # Feedback
    FEEDBACK_RECEIVED = "feedback_received"

    # Intelligence
    AWAREBOT_SCAN = "awarebot_scan"
    PREDICTION_GENERATED = "prediction_generated"

    # Memory
    MEMORY_CONSOLIDATED = "memory_consolidated"
    MEMORY_DECAYED = "memory_decayed"

    # Custom / extension point
    CUSTOM = "custom"


class ProvenanceEnvelope(BaseModel):
    """
    Provenance Envelope — tracks the origin, causality chain, and agent
    context for every event flowing through the NCL pipeline.

    Every NCLEvent carries one of these to answer: "Who created this,
    why, and what triggered it?"
    """

    source_agent: str = Field(
        ..., description="Agent/service that emitted the event (e.g., 'ncl-brain', 'awarebot-fpc', 'strike-point')"
    )
    source_pillar: str = Field(
        default="ncl", description="Originating pillar"
    )
    parent_event_id: Optional[str] = Field(
        default=None, description="Event that directly caused this one"
    )
    correlation_id: Optional[str] = Field(
        default=None, description="Shared ID linking all events in a single pump→mandate→execution chain"
    )
    causality_chain: list[str] = Field(
        default_factory=list,
        description="Ordered list of ancestor event_ids from root to immediate parent",
    )
    session_id: Optional[str] = Field(
        default=None, description="Council/debate session this event belongs to"
    )
    pump_id: Optional[str] = Field(
        default=None, description="Originating pump prompt ID (if traceable)"
    )
    mandate_id: Optional[str] = Field(
        default=None, description="Related mandate ID (if traceable)"
    )
    model_used: Optional[str] = Field(
        default=None, description="AI model invoked (e.g., 'claude-sonnet-4-6', 'grok-3')"
    )
    cost_usd: Optional[float] = Field(
        default=None, ge=0.0, description="Estimated API cost in USD for this event"
    )


class NCLEvent(BaseModel):
    """
    NCL Event Schema v1 — the canonical event record for every action,
    decision, and signal in the NCL brain pipeline.

    Replaces the ad-hoc dict format previously used in _log_event().
    All events are persisted to events.ndjson and forwarded to Paperclip.
    """

    event_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Unique event identifier",
    )
    type: EventType = Field(..., description="Canonical event type")
    description: str = Field(..., description="Human-readable event description")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of event creation",
    )
    provenance: ProvenanceEnvelope = Field(
        ..., description="Origin and causality tracking"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-type-specific structured data",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable tags for memory indexing",
    )
    importance: float = Field(
        default=50.0, ge=0.0, le=100.0,
        description="Importance score 0-100 for memory consolidation",
    )
    schema_version: str = Field(
        default="1.0",
        description="Schema version for forward compatibility",
    )

    def to_ndjson(self) -> str:
        """Serialize to single-line JSON for NDJSON storage."""
        return self.model_dump_json()

    def to_legacy_dict(self) -> dict[str, Any]:
        """Backwards-compatible dict matching the old _log_event format."""
        return {
            "event_id": self.event_id,
            "type": self.type.value,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "metadata": {
                **self.payload,
                "provenance": self.provenance.model_dump(),
                "tags": self.tags,
                "importance": self.importance,
            },
        }

    @classmethod
    def quick(
        cls,
        event_type: EventType | str,
        description: str,
        source_agent: str = "ncl-brain",
        payload: dict[str, Any] | None = None,
        parent_event_id: str | None = None,
        correlation_id: str | None = None,
        pump_id: str | None = None,
        mandate_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        importance: float = 50.0,
    ) -> "NCLEvent":
        """Factory for common events — less boilerplate than full construction."""
        if isinstance(event_type, str):
            try:
                event_type = EventType(event_type)
            except ValueError:
                event_type = EventType.CUSTOM

        return cls(
            type=event_type,
            description=description,
            provenance=ProvenanceEnvelope(
                source_agent=source_agent,
                parent_event_id=parent_event_id,
                correlation_id=correlation_id,
                pump_id=pump_id,
                mandate_id=mandate_id,
                session_id=session_id,
            ),
            payload=payload or {},
            tags=tags or [],
            importance=importance,
        )


# ── Pillar & Status Enums ────────────────────────────────────────────────────


class PillarType(str, Enum):
    """Pillar types in RESONANCE ENERGY ecosystem."""

    NCL = "ncl"
    NCC = "ncc"
    BRS = "brs"
    AAC = "aac"


class MandateStatus(str, Enum):
    """Mandate lifecycle status following MWP stage progression."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"  # Awaiting NATRIX review before NCC dispatch
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"

    @staticmethod
    def valid_transitions() -> dict["MandateStatus", list["MandateStatus"]]:
        """
        Define allowed status transitions (MWP governance state machine).

        DRAFT → PENDING_APPROVAL → ACTIVE → IN_PROGRESS → COMPLETED
                                 ↘ CANCELLED
                                   ACTIVE → SUPERSEDED
        """
        S = MandateStatus
        return {
            S.DRAFT: [S.PENDING_APPROVAL, S.CANCELLED],
            S.PENDING_APPROVAL: [S.ACTIVE, S.CANCELLED],
            S.ACTIVE: [S.IN_PROGRESS, S.SUPERSEDED, S.CANCELLED],
            S.IN_PROGRESS: [S.COMPLETED, S.SUPERSEDED, S.CANCELLED],
            S.COMPLETED: [],  # Terminal
            S.SUPERSEDED: [],  # Terminal
            S.CANCELLED: [],  # Terminal
        }

    def can_transition_to(self, target: "MandateStatus") -> bool:
        """Check if transition from current status to target is allowed."""
        allowed = self.valid_transitions().get(self, [])
        return target in allowed


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
    """Directive mandate for a pillar. Enforces MWP status progression."""

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
    status_history: list[dict[str, Any]] = Field(
        default_factory=list, description="Audit trail of status transitions"
    )

    def transition_to(self, new_status: MandateStatus, reason: str = "") -> None:
        """
        Transition mandate to new status with validation and audit trail.

        Follows MWP governance: only valid transitions allowed.
        Logged through Paperclip activity tracking.

        Raises:
            ValueError: If transition is not allowed
        """
        if not self.status.can_transition_to(new_status):
            allowed = [s.value for s in MandateStatus.valid_transitions().get(self.status, [])]
            raise ValueError(
                f"Invalid mandate transition: {self.status.value} → {new_status.value}. "
                f"Allowed: {allowed}"
            )
        self.status_history.append({
            "from": self.status.value,
            "to": new_status.value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)


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
