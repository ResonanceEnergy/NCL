"""
Position Thesis — structured contract for every open position.

Mandate from NATRIX (2026-05-25): "ensure every position has an entry
and exit and goal/mandate and that its being followed and what to watch
for coming up." The Portfolio Analyst Agent uses these contracts to:

  1. Flag positions without a thesis (auto-draft one from journal +
     entry context, then surface for confirmation).
  2. Re-evaluate each thesis nightly against new signals — supporting
     evidence (defend) vs invalidating evidence (challenge), producing
     a health_score 0-1 with a trend.
  3. Track mandate drift (a "swing 1-5d" thesis still open at day 30).
  4. Surface forward catalysts each position is exposed to.
  5. Auto-escalate broken theses to council.

Persistence
-----------
``data/portfolio/analyst/theses/<instrument_id>.json`` — one file per
position. Closed positions move to
``data/portfolio/analyst/theses/closed/`` with a final evaluation note.

The agent reads + writes; iOS reads via ``GET /portfolio/analyst/theses``
and ``GET /portfolio/analyst/theses/{instrument_id}``.

Schema is versioned (``schema_version``) so we can evolve fields
without breaking consumers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ───────────────────────────────────────────────────────────────


class Mandate(str, Enum):
    """Position-style classifier. Drives time-horizon checks."""

    SCALP = "scalp"          # intraday — minutes to hours
    SWING = "swing"          # 1-5 days
    POSITION = "position"    # 1-4 weeks
    CORE = "core"            # 1-6 months
    LONG_TERM = "long_term"  # 6+ months / multi-year
    OPTIONS_HEDGE = "options_hedge"  # protective put, covered call


class ThesisStatus(str, Enum):
    """Lifecycle. Drives Morning Brief surfacing + council escalation."""

    DRAFT = "draft"                  # agent drafted, awaiting NATRIX confirm
    ACTIVE = "active"                # confirmed + position open
    STRENGTHENING = "strengthening"  # new evidence supports thesis
    WEAKENING = "weakening"          # counter-evidence accumulating
    BROKEN = "broken"                # invalidating evidence dominant → council
    EXITED_WIN = "exited_win"        # target hit, exit
    EXITED_LOSS = "exited_loss"      # stop hit, exit
    EXITED_TIME = "exited_time"      # time-stop hit, mandate expired
    EXITED_THESIS = "exited_thesis"  # exited because thesis broke


class EvidenceKind(str, Enum):
    SUPPORTING = "supporting"
    INVALIDATING = "invalidating"
    NEUTRAL = "neutral"


# ── Sub-structures ──────────────────────────────────────────────────────


class ExitPlan(BaseModel):
    """The contract for getting out. Required for every position."""

    target_price: Optional[float] = Field(
        default=None,
        description="Take-profit level. Optional for core/long_term holds.",
    )
    target_price_rationale: Optional[str] = None

    stop_price: Optional[float] = Field(
        default=None,
        description="Hard stop. Required for swing/scalp/position mandates.",
    )
    stop_kind: Optional[str] = Field(
        default=None,
        description="hard | trailing | atr-3x | technical-200sma | news",
    )

    time_horizon_days: Optional[int] = Field(
        default=None,
        description="Max days to hold per the mandate. Drives drift alarms.",
    )

    thesis_invalidation_conditions: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete observable conditions that would invalidate the thesis. "
            "Examples: 'iPhone unit volume drops >10% YoY', 'Fed pivot to cuts', "
            "'CEO resignation', 'guidance cut on next earnings'."
        ),
    )

    target_return_pct: Optional[float] = None  # informational
    max_loss_pct: Optional[float] = None        # informational


class WatchItem(BaseModel):
    """One forward-looking catalyst the position is exposed to."""

    label: str  # "Q3 earnings", "FDA PDUFA date", "ETH Pectra fork"
    date: Optional[str] = None  # ISO date string when known
    kind: str = "catalyst"      # catalyst | regulatory | macro | technical
    expected_impact: str = "medium"  # low | medium | high
    notes: str = ""


class Evidence(BaseModel):
    """One piece of evidence that supports or invalidates the thesis."""

    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    kind: EvidenceKind
    summary: str
    source: str = ""             # "awarebot:reddit", "council:youtube:xyz", "news"
    signal_id: Optional[str] = None  # link back to the originating signal/unit
    confidence: float = 0.5      # 0-1
    weight: float = 1.0           # how much this counts toward health_score
    addressed_invalidation_condition: Optional[str] = (
        None  # which condition from exit_plan does this hit
    )


class ThesisHealth(BaseModel):
    """Computed nightly. NOT manually edited."""

    last_evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    supporting_count: int = 0
    invalidating_count: int = 0
    health_score: float = 0.5  # 0-1, computed from weighted evidence
    trend: str = "stable"  # strengthening | stable | weakening | broken
    days_since_last_supporting: Optional[int] = None
    days_since_entry: int = 0
    mandate_drift: bool = False  # True if days_since_entry > time_horizon_days
    last_health_score: Optional[float] = None  # previous night
    notes: list[str] = Field(default_factory=list)


# ── Top-level Thesis ────────────────────────────────────────────────────


class PositionThesis(BaseModel):
    """Structured contract for one position."""

    schema_version: int = 1
    instrument_id: str = Field(
        description="Canonical id matching Holdings reconciler — EQ:AAPL:US, OPT:..., CRYPTO:BTC"
    )
    ticker_display: str = Field(description="Human-readable ticker — AAPL, BTC, TSLA 250C")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    status: ThesisStatus = ThesisStatus.DRAFT
    mandate: Mandate

    # Entry
    entry_date: Optional[str] = None  # YYYY-MM-DD
    entry_price: Optional[float] = None
    entry_size_pct_nav: Optional[float] = None  # % of NAV at entry — drives concentration-creep alarm
    entry_rationale: str = Field(description="Why this trade now — 1-3 sentences")

    # Thesis pillars — load-bearing claims
    thesis_statement: str = Field(description="One-line statement — what NATRIX believes")
    thesis_pillars: list[str] = Field(
        default_factory=list,
        description="3-5 specific claims that, if all true, make the thesis work",
    )

    # Exit contract — required
    exit_plan: ExitPlan = Field(default_factory=ExitPlan)

    # Forward watch — what catalysts could move this
    watch_for: list[WatchItem] = Field(default_factory=list)

    # Evidence ledger — appended each night
    evidence: list[Evidence] = Field(default_factory=list)

    # Health — computed
    health: ThesisHealth = Field(default_factory=ThesisHealth)

    # Provenance
    source: str = "manual"  # manual | agent_draft | council_synthesis | journal_inferred
    journal_links: list[str] = Field(default_factory=list)

    # Lifecycle exit metadata
    exited_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_kind: Optional[str] = None  # target | stop | time | thesis | manual
    final_pl_pct: Optional[float] = None
    final_pl_usd: Optional[float] = None
    post_mortem: Optional[str] = None  # what the agent learned

    @field_validator("entry_size_pct_nav")
    @classmethod
    def _clamp_size(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        return max(0.0, min(1.0, v))

    # ── Contract compliance ────────────────────────────────────────────

    def has_complete_contract(self) -> tuple[bool, list[str]]:
        """Check the thesis has every field NATRIX's mandate requires.

        Returns (is_complete, list_of_missing_fields).
        """
        missing: list[str] = []
        if not self.entry_rationale.strip():
            missing.append("entry_rationale")
        if not self.thesis_statement.strip():
            missing.append("thesis_statement")
        if not self.thesis_pillars:
            missing.append("thesis_pillars")
        if self.mandate in (Mandate.SCALP, Mandate.SWING, Mandate.POSITION):
            if self.exit_plan.stop_price is None:
                missing.append(f"exit_plan.stop_price (required for {self.mandate.value})")
            if self.exit_plan.time_horizon_days is None:
                missing.append(f"exit_plan.time_horizon_days (required for {self.mandate.value})")
        if not self.exit_plan.thesis_invalidation_conditions:
            missing.append("exit_plan.thesis_invalidation_conditions")
        if not self.watch_for:
            missing.append("watch_for (>=1 forward catalyst required)")
        return (len(missing) == 0, missing)

    def is_mandate_drifting(self) -> bool:
        """True when position has been held past its mandate's time horizon."""
        if self.health.days_since_entry == 0 or self.exit_plan.time_horizon_days is None:
            return False
        return self.health.days_since_entry > self.exit_plan.time_horizon_days

    def recent_evidence(self, days: int = 7, kind: Optional[EvidenceKind] = None) -> list[Evidence]:
        """Filter evidence by recency + kind."""
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        items = [e for e in self.evidence if e.ts.timestamp() >= cutoff]
        if kind is not None:
            items = [e for e in items if e.kind == kind]
        return items

    def compute_health_score(self) -> float:
        """Weighted ratio of supporting vs invalidating evidence in last 14 days.

        Pure function — call from ``thesis_evaluator`` after appending new
        evidence. Returns 0.0 (fully invalidated) to 1.0 (fully supported).
        Neutral evidence is ignored in the ratio but counted in
        ``supporting_count`` via the evaluator.

        A position with NO recent evidence either way decays toward 0.5
        with mild bias toward 0.4 (stale = mild concern, not invalidation).
        """
        recent = self.recent_evidence(days=14)
        if not recent:
            # Decay toward 0.4 — stale, mild concern but not broken
            last = self.health.health_score
            return round(0.7 * last + 0.3 * 0.4, 4)

        supporting_w = sum(
            e.weight * e.confidence for e in recent if e.kind == EvidenceKind.SUPPORTING
        )
        invalidating_w = sum(
            e.weight * e.confidence for e in recent if e.kind == EvidenceKind.INVALIDATING
        )
        total = supporting_w + invalidating_w
        if total <= 0:
            return self.health.health_score  # only neutrals, no change
        return round(supporting_w / total, 4)


class ThesisEvaluationResult(BaseModel):
    """What ``thesis_evaluator.evaluate(thesis, signals)`` returns per night.

    Persisted into the NightlyReport so the LLM and iOS can both render
    the per-position read without re-running the evaluator.
    """

    instrument_id: str
    health_score: float
    health_score_delta: float  # vs last night
    trend: str
    new_supporting_evidence: list[Evidence] = Field(default_factory=list)
    new_invalidating_evidence: list[Evidence] = Field(default_factory=list)
    addressed_invalidation_conditions: list[str] = Field(default_factory=list)
    mandate_drift: bool = False
    days_past_horizon: Optional[int] = None
    recommended_action: str = "hold"  # hold | defend | trim | exit | escalate_to_council
    rationale: str = ""
    contract_complete: bool = True
    missing_contract_fields: list[str] = Field(default_factory=list)
