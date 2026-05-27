"""
Auto-Trader high-R council quorum check — Wave 14K gap-close A

For any trade idea with effective_R_dollars >= NCL_AT_COUNCIL_R_THRESHOLD
(default $1000), spawn a 2-LLM Sonnet+Haiku quorum pre-pass asking
"is this a sane trade given context?" before opening.

  AGREE_SHORT_CIRCUIT  → approve (both models agree it's sane)
  ESCALATE_FULL_COUNCIL→ defer to operator review (queue mandate
                         only — do not open)
  ERROR_ESCALATE       → fail-open (open anyway with warning logged)

Spawn cost ~$0.05/trade; only fires on high-R so impact is bounded.
Result attached to reasoning chain for audit.

Tunables:
  NCL_AT_COUNCIL_R_THRESHOLD=1000   (USD effective R that triggers)
  NCL_AT_COUNCIL_ENABLED=1          (master kill switch; 0 disables)
  NCL_AT_COUNCIL_FAIL_OPEN=1        (1=open on quorum failure; 0=block)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.council_check")

R_THRESHOLD = float(os.getenv("NCL_AT_COUNCIL_R_THRESHOLD", "1000"))
ENABLED = os.getenv("NCL_AT_COUNCIL_ENABLED", "1") not in ("0", "false", "False")
FAIL_OPEN = os.getenv("NCL_AT_COUNCIL_FAIL_OPEN", "1") not in ("0", "false", "False")


def _build_topic(idea: dict, effective_R: float) -> str:
    return (
        f"Auto-trader high-R open: {idea.get('direction', 'long')} "
        f"{idea.get('ticker', '?')} effective_R=${effective_R:.0f}"
    )


def _build_context(idea: dict, gov: Optional[dict], effective_R: float) -> str:
    parts = [
        f"Ticker: {idea.get('ticker')}",
        f"Direction: {idea.get('direction')}",
        f"Strategy: {idea.get('strategy_tag') or idea.get('strategy', '?')}",
        f"Entry: ${idea.get('entry_price')}",
        f"Stop: ${idea.get('stop_price')} ({idea.get('stop_type', '?')})",
        f"Target: ${idea.get('target_price')}",
        f"R per share: ${idea.get('R_per_share')}",
        f"Effective R dollars: ${effective_R:.0f}",
        f"Confidence: {idea.get('confidence_pct')}",
        f"Rotation: {idea.get('rotation_quadrant')} / {idea.get('rotation_stance')}",
    ]
    if idea.get("thesis"):
        parts.append(f"Thesis: {idea['thesis']}")
    if gov:
        parts.append(
            f"Risk governor: {gov.get('decision', '?')} "
            f"effective_R=${gov.get('effective_R_dollars', 0):.0f}"
        )
    return "\n".join(parts)


def _build_prompt() -> str:
    return (
        "You are a risk-aware second opinion on an automated paper trade.\n"
        "Given the trade context above, answer in 2-3 sentences:\n"
        "1. Is this a SANE trade given the structure (R:R, stop placement, "
        "stance, confidence)?\n"
        "2. If you would VETO it, state the specific concrete reason.\n"
        "3. Decision word at the end: SANE or VETO."
    )


async def check_high_r_open(
    *,
    idea: dict,
    gov: Optional[dict],
    effective_R: float,
) -> dict:
    """Returns:
      {
        veto: bool,
        decision: "approve" | "veto" | "skipped" | "fail_open" | "fail_block",
        reason: str,
        cost_usd: float,
        similarity: float | None,
      }
    Non-blocking: any unhandled exception ⇒ fail-open (or fail-block per env).
    """
    out = {
        "veto": False,
        "decision": "skipped",
        "reason": "below threshold",
        "cost_usd": 0.0,
        "similarity": None,
    }
    if not ENABLED:
        out["reason"] = "council check disabled (NCL_AT_COUNCIL_ENABLED=0)"
        return out
    if effective_R < R_THRESHOLD:
        out["reason"] = (
            f"effective_R ${effective_R:.0f} < threshold ${R_THRESHOLD:.0f}"
        )
        return out

    try:
        from ...councils.quorum import CouncilQuorum, QuorumDecision
        from ...cost_tracker import get_tracker

        async def _gate(provider: str, amount: float) -> bool:
            tr = await get_tracker()
            return await tr.can_spend(provider, amount)

        quorum = CouncilQuorum(
            cost_gate_callable=_gate,
            threshold=0.55,  # slightly more permissive than default 0.6
        )
        topic = _build_topic(idea, effective_R)
        context = _build_context(idea, gov, effective_R)
        prompt = _build_prompt()

        result = await quorum.run_quorum(
            topic=topic, context=context, prompt=prompt,
        )

        out["cost_usd"] = result.cost_usd
        out["similarity"] = result.similarity
        # Look at the COMBINED text for a VETO token; if either model said
        # VETO clearly, treat as veto (more conservative than the agree-only
        # signal from the quorum decision).
        combined = (
            (result.sonnet_response or "") + " | " +
            (result.haiku_response or "")
        ).upper()
        has_veto_token = "VETO" in combined
        if result.decision == QuorumDecision.AGREE_SHORT_CIRCUIT and not has_veto_token:
            out["decision"] = "approve"
            out["reason"] = (
                f"both models agree (similarity={result.similarity:.2f}); "
                f"opening"
            )
        elif has_veto_token:
            out["veto"] = True
            out["decision"] = "veto"
            # Pull a brief snippet so the reasoning chain captures what each model said
            sonnet_snip = (result.sonnet_response or "")[:200].replace("\n", " ")
            haiku_snip = (result.haiku_response or "")[:200].replace("\n", " ")
            out["reason"] = (
                f"council quorum VETO (similarity={result.similarity:.2f}) — "
                f"SONNET: {sonnet_snip[:120]}... HAIKU: {haiku_snip[:120]}..."
            )
        elif result.decision == QuorumDecision.ESCALATE_FULL_COUNCIL:
            # Disagreement on direction → conservative: don't open
            out["veto"] = True
            out["decision"] = "veto"
            out["reason"] = (
                f"council quorum DISAGREE (similarity={result.similarity:.2f}) — "
                f"models disagree on direction; deferring to operator review"
            )
        else:
            # ERROR_ESCALATE
            if FAIL_OPEN:
                out["decision"] = "fail_open"
                out["reason"] = (
                    f"quorum error ({result.reason}); fail-open per "
                    f"NCL_AT_COUNCIL_FAIL_OPEN=1"
                )
            else:
                out["veto"] = True
                out["decision"] = "fail_block"
                out["reason"] = (
                    f"quorum error ({result.reason}); fail-block per "
                    f"NCL_AT_COUNCIL_FAIL_OPEN=0"
                )

        log.info(
            "[AT-COUNCIL] %s for %s effective_R=$%.0f decision=%s (cost=$%.4f, sim=%.2f)",
            "VETO" if out["veto"] else "APPROVE",
            idea.get("ticker", "?"),
            effective_R,
            out["decision"],
            out["cost_usd"],
            result.similarity or 0,
        )
    except Exception as e:
        log.warning("[AT-COUNCIL] check failed (fail-open=%s): %s", FAIL_OPEN, e)
        if FAIL_OPEN:
            out["decision"] = "fail_open"
            out["reason"] = f"exception: {e}"
        else:
            out["veto"] = True
            out["decision"] = "fail_block"
            out["reason"] = f"exception (fail-block): {e}"
    return out
