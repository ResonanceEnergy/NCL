"""
Thesis evaluator — runs each night during the Portfolio Analyst phase.

Takes a ``PositionThesis`` + the last 24h of awarebot signals + the
last 24h of council briefs + calendar events for the next 14d, and
produces a ``ThesisEvaluationResult``. Pure-Python in the deterministic
layer; the LLM consumes the result and writes the narrative.

The matcher is intentionally simple — token-overlap against the
thesis pillars + ticker + watch-for labels — because the goal is
RECALL of relevant evidence, not precision. The LLM critique pass
discards false-positive matches.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .theses import (
    Evidence,
    EvidenceKind,
    Mandate,
    PositionThesis,
    ThesisEvaluationResult,
    ThesisStatus,
)


# ── Health-score → trend mapping ────────────────────────────────────────

_STRONG_SUPPORT = 0.70
_BROKEN = 0.30


def _trend_label(prev: float | None, current: float) -> str:
    if current >= _STRONG_SUPPORT:
        return "strengthening"
    if current <= _BROKEN:
        return "broken"
    if prev is None:
        return "stable"
    delta = current - prev
    if delta >= 0.10:
        return "strengthening"
    if delta <= -0.10:
        return "weakening"
    return "stable"


# ── Signal → Evidence matcher ───────────────────────────────────────────


_TICKER_RE = re.compile(r"\b\$?([A-Z]{1,5})\b")


def _ticker_appears(text: str, ticker_symbols: list[str]) -> bool:
    """True when any of the ticker variants appear in `text`.

    Conservative: only matches uppercase or $TICKER. Avoids "amp" being
    a TSLA match.
    """
    if not text:
        return False
    found = set(_TICKER_RE.findall(text))
    return any(t in found for t in ticker_symbols)


def _pillar_token_overlap(text: str, pillars: list[str], threshold: int = 2) -> bool:
    """True when the signal text shares >=threshold lowercase tokens with any pillar.

    Tokens >=4 chars to avoid junk-overlap on "and", "the", etc.
    """
    if not text or not pillars:
        return False
    text_tokens = {t for t in re.findall(r"[a-z]{4,}", text.lower())}
    for p in pillars:
        pillar_tokens = {t for t in re.findall(r"[a-z]{4,}", p.lower())}
        if len(text_tokens & pillar_tokens) >= threshold:
            return True
    return False


def _condition_token_overlap(text: str, condition: str, threshold: int = 2) -> bool:
    """Match a signal against ONE invalidation condition's tokens."""
    if not text or not condition:
        return False
    text_tokens = {t for t in re.findall(r"[a-z]{4,}", text.lower())}
    cond_tokens = {t for t in re.findall(r"[a-z]{4,}", condition.lower())}
    return len(text_tokens & cond_tokens) >= threshold


def _ticker_variants(thesis: PositionThesis) -> list[str]:
    """Extract the ticker symbols a signal might reference."""
    variants: set[str] = set()
    iid = (thesis.instrument_id or "").upper()
    disp = (thesis.ticker_display or "").upper()
    # Pull bare ticker from "EQ:AAPL:US" or "OPT:AAPL:..."
    parts = iid.split(":")
    if len(parts) >= 2:
        variants.add(parts[1])
    # Display first token, e.g., "TSLA 250C" -> "TSLA"
    if disp:
        variants.add(disp.split()[0])
        variants.add(disp)
    return [v for v in variants if v and len(v) <= 6]


def _classify_signal(signal: dict, thesis: PositionThesis) -> Evidence | None:
    """Decide whether one awarebot signal is evidence for this thesis.

    Args:
        signal: dict-shaped Awarebot signal — title, content, direction,
            confidence, source, signal_id, etc.
        thesis: PositionThesis to evaluate against

    Returns:
        Evidence object if the signal is relevant; None otherwise.
    """
    title = signal.get("title") or ""
    content = signal.get("content") or ""
    text = f"{title} {content}"
    if not text.strip():
        return None

    tickers = _ticker_variants(thesis)
    pillars_match = _pillar_token_overlap(text, thesis.thesis_pillars)
    ticker_match = _ticker_appears(text, tickers) if tickers else False

    # A signal needs at least one match-vector
    if not (pillars_match or ticker_match):
        return None

    direction = (signal.get("direction") or "neutral").lower()
    confidence = float(signal.get("confidence") or signal.get("composite_score") or 0.5)
    source = signal.get("source") or signal.get("source_platform") or ""

    # Direction maps to evidence kind, modulated by thesis tilt.
    # For a long position: bullish/positive direction = supporting,
    # bearish/negative direction = invalidating.
    # Options shorts (short calls / short puts) invert sign.
    if direction in ("bullish", "positive", "buy", "up"):
        kind = EvidenceKind.SUPPORTING
    elif direction in ("bearish", "negative", "sell", "down"):
        kind = EvidenceKind.INVALIDATING
    else:
        kind = EvidenceKind.NEUTRAL

    # Check whether this signal addresses one of the explicit
    # invalidation conditions. If so, weight it heavier.
    addressed = None
    weight = 1.0
    for cond in thesis.exit_plan.thesis_invalidation_conditions:
        if _condition_token_overlap(text, cond):
            addressed = cond
            weight = 2.0  # invalidation-condition signals count double
            # If the signal directly addresses an invalidation condition
            # AND the direction is bearish, this is heavy invalidation.
            if direction in ("bearish", "negative", "sell", "down"):
                kind = EvidenceKind.INVALIDATING
            break

    return Evidence(
        ts=datetime.now(timezone.utc),
        kind=kind,
        summary=(title or content)[:200],
        source=source,
        signal_id=signal.get("signal_id"),
        confidence=confidence,
        weight=weight,
        addressed_invalidation_condition=addressed,
    )


# ── Forward catalyst proximity ──────────────────────────────────────────


def _imminent_catalysts(thesis: PositionThesis, days_ahead: int = 7) -> list[dict]:
    """Return watch_for items dated within `days_ahead`.

    Includes items missing a date (always surface — they're "watch indefinitely").
    """
    now = datetime.now(timezone.utc).date()
    cutoff = now + timedelta(days=days_ahead)
    out: list[dict] = []
    for w in thesis.watch_for:
        if not w.date:
            out.append({**w.model_dump(), "imminent": False})
            continue
        try:
            d = datetime.strptime(w.date[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d <= cutoff:
            out.append({**w.model_dump(), "imminent": True, "days_until": (d - now).days})
    return out


# ── Public API ──────────────────────────────────────────────────────────


def evaluate(
    thesis: PositionThesis,
    signals_24h: list[dict],
    council_briefs_24h: list[dict] | None = None,
    today_utc: datetime | None = None,
) -> ThesisEvaluationResult:
    """Re-evaluate a thesis against last 24h of evidence.

    Args:
        thesis: the PositionThesis (will NOT be mutated — caller decides
            whether to persist the appended evidence)
        signals_24h: awarebot signal dicts
        council_briefs_24h: optional council brief dicts to fold in
        today_utc: clock injection for tests

    Returns:
        ThesisEvaluationResult — what the agent + LLM consume to write
        the night's narrative. Mandate-drift, contract-completeness,
        recommended_action all populated.
    """
    today = today_utc or datetime.now(timezone.utc)

    # 1) Classify each signal against the thesis
    new_supporting: list[Evidence] = []
    new_invalidating: list[Evidence] = []
    addressed_conds: set[str] = set()

    for sig in signals_24h:
        ev = _classify_signal(sig, thesis)
        if ev is None:
            continue
        if ev.kind == EvidenceKind.SUPPORTING:
            new_supporting.append(ev)
        elif ev.kind == EvidenceKind.INVALIDATING:
            new_invalidating.append(ev)
        if ev.addressed_invalidation_condition:
            addressed_conds.add(ev.addressed_invalidation_condition)

    # Council briefs count double if they're scored by the chair
    for brief in council_briefs_24h or []:
        # Fabricate a signal-shaped dict from the brief
        sig = {
            "title": brief.get("topic") or brief.get("title", ""),
            "content": brief.get("chair_summary") or brief.get("summary", ""),
            "direction": brief.get("consensus_direction", "neutral"),
            "confidence": float(brief.get("consensus_confidence") or 0.7),
            "source": "council",
            "signal_id": brief.get("session_id"),
        }
        ev = _classify_signal(sig, thesis)
        if ev is None:
            continue
        ev.weight *= 1.5  # council carries more weight
        if ev.kind == EvidenceKind.SUPPORTING:
            new_supporting.append(ev)
        elif ev.kind == EvidenceKind.INVALIDATING:
            new_invalidating.append(ev)

    # 2) Build the up-to-date evidence ledger (without mutating original)
    ledger = list(thesis.evidence) + new_supporting + new_invalidating

    # 3) Recompute health
    # We compute against a temporary copy so the formula sees the new evidence
    tmp = thesis.model_copy(update={"evidence": ledger})
    new_score = tmp.compute_health_score()
    prev_score = thesis.health.health_score
    delta = round(new_score - prev_score, 4)
    trend = _trend_label(prev_score, new_score)

    # 4) Mandate-drift check
    days_since_entry = thesis.health.days_since_entry
    if thesis.entry_date:
        try:
            entry_dt = datetime.strptime(thesis.entry_date[:10], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            days_since_entry = (today - entry_dt).days
        except ValueError:
            pass
    mandate_drift = False
    days_past_horizon: int | None = None
    if thesis.exit_plan.time_horizon_days is not None:
        days_past_horizon = days_since_entry - thesis.exit_plan.time_horizon_days
        mandate_drift = days_past_horizon > 0

    # 5) Contract completeness
    complete, missing = thesis.has_complete_contract()

    # 6) Recommended action
    # Priority order: broken > drift > weakening > strengthening > hold
    if new_score <= _BROKEN:
        action = "escalate_to_council"
        rationale = (
            f"Thesis health {new_score:.2f} below broken threshold {_BROKEN}. "
            f"Invalidating evidence count: {len(new_invalidating)} this cycle."
        )
    elif mandate_drift and (days_past_horizon or 0) > 7:
        action = "exit"
        rationale = (
            f"Mandate drift: {thesis.mandate.value} typically held "
            f"{thesis.exit_plan.time_horizon_days}d; held {days_since_entry}d "
            f"({days_past_horizon}d past horizon). Review for exit."
        )
    elif trend == "weakening":
        action = "trim"
        rationale = (
            f"Health score declined {delta:+.2f} to {new_score:.2f}. "
            f"{len(new_invalidating)} invalidating signals in 24h."
        )
    elif trend == "strengthening":
        action = "defend"
        rationale = (
            f"Health score improved {delta:+.2f} to {new_score:.2f}. "
            f"{len(new_supporting)} supporting signals in 24h."
        )
    elif not complete:
        action = "complete_contract"
        rationale = f"Thesis missing required fields: {', '.join(missing[:3])}"
    else:
        action = "hold"
        rationale = (
            f"Thesis stable at {new_score:.2f}. "
            f"{len(new_supporting)} supporting / {len(new_invalidating)} invalidating in 24h."
        )

    return ThesisEvaluationResult(
        instrument_id=thesis.instrument_id,
        health_score=new_score,
        health_score_delta=delta,
        trend=trend,
        new_supporting_evidence=new_supporting,
        new_invalidating_evidence=new_invalidating,
        addressed_invalidation_conditions=sorted(addressed_conds),
        mandate_drift=mandate_drift,
        days_past_horizon=days_past_horizon,
        recommended_action=action,
        rationale=rationale,
        contract_complete=complete,
        missing_contract_fields=missing,
    )


# ── Status transition helper ────────────────────────────────────────────


def apply_evaluation(thesis: PositionThesis, result: ThesisEvaluationResult) -> PositionThesis:
    """Apply an evaluation to a thesis — append evidence, update health,
    bump status if a transition is warranted.

    Returns a NEW PositionThesis (does not mutate input). Caller decides
    whether to persist via ``ThesisStore.save``.
    """
    new_evidence = list(thesis.evidence)
    new_evidence.extend(result.new_supporting_evidence)
    new_evidence.extend(result.new_invalidating_evidence)

    new_health = thesis.health.model_copy(
        update={
            "last_evaluated_at": datetime.now(timezone.utc),
            "supporting_count": thesis.health.supporting_count + len(result.new_supporting_evidence),
            "invalidating_count": thesis.health.invalidating_count
            + len(result.new_invalidating_evidence),
            "health_score": result.health_score,
            "last_health_score": thesis.health.health_score,
            "trend": result.trend,
            "mandate_drift": result.mandate_drift,
            "days_since_entry": (
                (thesis.health.days_since_entry + 1)
                if thesis.entry_date
                else thesis.health.days_since_entry
            ),
        }
    )

    # Status transitions
    new_status = thesis.status
    if thesis.status == ThesisStatus.DRAFT:
        pass  # only NATRIX confirms draft → active
    elif result.health_score <= _BROKEN:
        new_status = ThesisStatus.BROKEN
    elif result.trend == "strengthening":
        new_status = ThesisStatus.STRENGTHENING
    elif result.trend == "weakening":
        new_status = ThesisStatus.WEAKENING
    elif result.trend == "stable" and thesis.status in (
        ThesisStatus.STRENGTHENING,
        ThesisStatus.WEAKENING,
    ):
        new_status = ThesisStatus.ACTIVE

    return thesis.model_copy(
        update={
            "evidence": new_evidence,
            "health": new_health,
            "status": new_status,
            "updated_at": datetime.now(timezone.utc),
        }
    )


__all__ = [
    "evaluate",
    "apply_evaluation",
    "imminent_catalysts",
]


# expose the catalyst helper
imminent_catalysts = _imminent_catalysts
