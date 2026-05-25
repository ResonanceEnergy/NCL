"""
NightlyReport schema — the single artifact the Portfolio Analyst Agent
emits each Night Watch run. Versioned so we can evolve the shape
without breaking the iOS / Morning Brief consumers.

Schema version 1 (2026-05-25).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


# ── Sub-structures ───────────────────────────────────────────────────────


class NAV(BaseModel):
    usd: float = 0.0
    cad: float = 0.0
    fx_rate_usd_cad: Optional[float] = None
    delta_24h_usd: Optional[float] = None
    delta_24h_pct: Optional[float] = None


class SectorWeight(BaseModel):
    sector: str
    weight: float  # 0.0-1.0


class Concentration(BaseModel):
    hhi: float = 0.0  # Herfindahl-Hirschman index over position weights
    top1_weight: float = 0.0
    top5_weight: float = 0.0
    by_sector: list[SectorWeight] = Field(default_factory=list)


class RiskMetrics(BaseModel):
    var_95_1d_usd: Optional[float] = None
    cvar_95_1d_usd: Optional[float] = None
    beta_to_spy: Optional[float] = None
    max_drawdown_30d_pct: Optional[float] = None
    max_drawdown_ytd_pct: Optional[float] = None
    leverage: Optional[float] = None
    cash_pct: Optional[float] = None


class CorrelationBreak(BaseModel):
    a: str
    b: str
    corr_60d: float
    corr_30d: float
    note: str = ""


class OptionExpiry(BaseModel):
    ticker: str
    strike: float
    expiry: str  # YYYY-MM-DD
    contract_type: str  # "call" | "put"
    side: str  # "long" | "short"
    quantity: int
    pin_distance_pct: Optional[float] = None


class OptionsBook(BaseModel):
    net_delta: Optional[float] = None
    net_gamma: Optional[float] = None
    net_vega: Optional[float] = None
    net_theta: Optional[float] = None
    expiries_next_7d: list[OptionExpiry] = Field(default_factory=list)


class CryptoBook(BaseModel):
    stablecoin_pct: Optional[float] = None
    cex_vs_onchain: dict[str, float] = Field(default_factory=dict)
    idle_stake_assets: list[str] = Field(default_factory=list)


class DeterministicSection(BaseModel):
    """Pure Python computations. Always present in every report."""

    concentration: Concentration = Field(default_factory=Concentration)
    risk: RiskMetrics = Field(default_factory=RiskMetrics)
    correlation_breaks: list[CorrelationBreak] = Field(default_factory=list)
    options_book: Optional[OptionsBook] = None
    futures_book: Optional[dict] = None
    crypto_book: Optional[CryptoBook] = None


class ImmediateAction(BaseModel):
    ticker: str
    kind: str  # "stop_breach_imminent" | "option_expiring" | "ex_div" | "news_pivot" | "concentration_alert"
    detail: str  # one-sentence explainer
    severity: str = "medium"  # "low" | "medium" | "high" | "critical"
    linked_signals: list[str] = Field(default_factory=list)  # signal_ids


class TrimAddCandidate(BaseModel):
    ticker: str
    action: str  # "add" | "trim" | "hold-with-stop"
    size_pct: Optional[float] = None  # % of position to trim, or % of NAV to add
    rationale: str
    ev_score: Optional[float] = None  # expected-value rank
    linked_signals: list[str] = Field(default_factory=list)


class CapitalFlow(BaseModel):
    institutional: str = ""
    retail: str = ""
    macro: str = ""


class RiskAlert(BaseModel):
    rule: str  # e.g. "ytd_drawdown_gt_8pct"
    value: float
    threshold: float
    tripped: bool


class NightlyReport(BaseModel):
    """Top-level artifact. Persisted as JSON; consumed by Morning Brief."""

    schema_version: int = 1
    report_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float = 0.0
    cost_usd: float = 0.0

    # Required sections
    nav: NAV = Field(default_factory=NAV)
    deterministic: DeterministicSection = Field(default_factory=DeterministicSection)
    immediate_actions: list[ImmediateAction] = Field(default_factory=list)

    # Optional (LLM-produced) sections
    trim_add_candidates: list[TrimAddCandidate] = Field(default_factory=list)
    capital_flow: Optional[CapitalFlow] = None
    risk_alerts: list[RiskAlert] = Field(default_factory=list)
    llm_narrative: Optional[str] = None
    council_link: Optional[str] = None  # session_id if the agent recommends spawning a council

    # Provenance — what the agent saw when it ran
    positions_count: int = 0
    signals_consumed: int = 0
    notes: list[str] = Field(default_factory=list)

    def summary_for_analyst(self) -> str:
        """Compact text summary the existing night_watch analyst can ingest.

        Keeps the daily-briefing loop's prompt under control — analyst
        sees the report's headline numbers + immediate actions, not the
        full deterministic payload.
        """
        parts: list[str] = []
        parts.append(
            f"NAV: ${self.nav.usd:,.0f} USD / ${self.nav.cad:,.0f} CAD "
            f"(Δ24h {self.nav.delta_24h_pct:+.2f}%)"
            if self.nav.delta_24h_pct is not None
            else f"NAV: ${self.nav.usd:,.0f} USD / ${self.nav.cad:,.0f} CAD"
        )
        c = self.deterministic.concentration
        parts.append(
            f"Concentration: HHI {c.hhi:.3f}, top1 {c.top1_weight:.0%}, top5 {c.top5_weight:.0%}"
        )
        r = self.deterministic.risk
        if r.var_95_1d_usd is not None:
            parts.append(f"VaR 95% 1d: ${r.var_95_1d_usd:,.0f}")
        if r.max_drawdown_ytd_pct is not None:
            parts.append(f"YTD drawdown: {r.max_drawdown_ytd_pct:+.1f}%")
        if self.immediate_actions:
            parts.append(f"\nImmediate actions ({len(self.immediate_actions)}):")
            for ia in self.immediate_actions:
                parts.append(f"  [{ia.severity}] {ia.ticker}: {ia.detail}")
        if self.trim_add_candidates:
            parts.append(f"\nTrim/Add candidates ({len(self.trim_add_candidates)}):")
            for tac in self.trim_add_candidates[:5]:
                size = f" ({tac.size_pct:.0%})" if tac.size_pct is not None else ""
                parts.append(f"  {tac.action.upper()} {tac.ticker}{size}: {tac.rationale}")
        if self.llm_narrative:
            parts.append("\nNarrative:")
            parts.append(self.llm_narrative)
        return "\n".join(parts)
