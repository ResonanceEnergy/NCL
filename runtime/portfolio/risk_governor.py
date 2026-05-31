"""
NCL Risk Governor — Wave 14J Phase 2 (J1a + J1b)

Single entrypoint that composes J0b (R-fields), J0c (drawdown bucket) and
configurable per-strategy heat budgets into one `check_proposed_trade()`
call. Every consumer (GOAT scanner, BRAVO scanner, brief executor, paper
trading) calls this BEFORE proposing or executing new risk.

The whole point: heat-cap math + drawdown throttle live in ONE place. A
new scanner cannot accidentally skip one half of the check.

Decision tree (in order, first-match wins):
  1. If band == 'halt' (drawdown beyond -12%):       REJECT  (mult=0)
  2. If platform-wide heat would breach total cap:    REJECT
  3. If per-strategy heat would breach strategy cap:  REJECT
  4. Else:                                            APPROVE
     - effective_R_dollars = proposed_R * sizing_multiplier
       (so caution band shrinks size 25%, warning 50%, halt to zero —
        but halt already rejected above)

Heat == sum of R_dollars across positions with risk_status == 'at_risk'.
Source of truth: PositionRiskStore.aggregate() (J0b).

Per-strategy budgets (% of total portfolio NAV — defaults):
  Total portfolio heat:    10.0%   (NCL_HEAT_TOTAL_PCT)
  goat (momentum):          3.0%   (NCL_HEAT_GOAT_PCT)
  bravo (swing):            2.0%   (NCL_HEAT_BRAVO_PCT)
  options (premium-sell):   4.0%   (NCL_HEAT_OPTIONS_PCT)
  polymarket:               1.0%   (NCL_HEAT_POLYMARKET_PCT)
  manual / unknown:         3.0%   (NCL_HEAT_MANUAL_PCT)

Budgets are PERCENTAGES of NAV. The governor converts to $ using current
portfolio NAV (CAD-equivalent) at decision time. If NAV is unavailable
the governor falls back to a configurable absolute floor
NCL_HEAT_NAV_FLOOR_CAD (default 30000) so dev / pre-connect environments
still produce usable decisions.

Return shape:
  {
    "approved": bool,
    "decision": "approve" | "throttle" | "reject",   # throttle means
        "approved AT a smaller size after drawdown multiplier"
    "reasons": [str, ...],                            # human-readable
    "proposed_R_dollars": float,
    "effective_R_dollars": float,                     # after multiplier
    "strategy_tag": str,
    "nav_cad": float,
    "band": str,
    "sizing_multiplier": float,
    "heat": {
        "current_total_R": float,
        "total_cap_R": float,
        "by_strategy_current_R": dict,
        "by_strategy_cap_R": dict,
        "remaining_total_R": float,
        "remaining_strategy_R": float,
    }
  }
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("ncl.portfolio.risk_governor")

# Default per-strategy budgets — fraction of NAV
# Wave 14U HOTFIX B: added pairs, mean_reversion, pead, factor, whale_flow,
# crypto_carry buckets so quant scanners stop falling into "unknown" with a
# too-small cap. Sized per Carver/CME emerging-CTA sleeve guidance.
DEFAULT_BUDGETS_PCT: dict[str, float] = {
    "total": 10.0,
    "goat": 3.0,
    "bravo": 2.0,
    "options": 4.0,
    "polymarket": 1.0,
    "manual": 3.0,
    "pairs": 6.0,
    "mean_reversion": 6.0,
    "pead": 6.0,
    "factor": 6.0,
    "whale_flow": 6.0,
    "crypto_carry": 2.0,
    "unknown": 3.0,
}
# Wave 14U HOTFIX B+ (note 2026-05-27): scanner sleeves bumped from 2-3%
# to 5% to align with mandate's "5% risk per trade" budget — pairs/MR/
# PEAD/factor/whale_flow all emit ~$1800-2100 trade size at NAV=$36K and
# would otherwise be permanently blocked by an under-sized heat cap.
# Crypto_carry stays at 2% because the capability registry shows it's
# still using a momentum proxy (no real perp funding adapter yet).

ENV_KEY_MAP = {
    "total": "NCL_HEAT_TOTAL_PCT",
    "goat": "NCL_HEAT_GOAT_PCT",
    "bravo": "NCL_HEAT_BRAVO_PCT",
    "options": "NCL_HEAT_OPTIONS_PCT",
    "polymarket": "NCL_HEAT_POLYMARKET_PCT",
    "manual": "NCL_HEAT_MANUAL_PCT",
    "pairs": "NCL_HEAT_PAIRS_PCT",
    "mean_reversion": "NCL_HEAT_MEANREV_PCT",
    "pead": "NCL_HEAT_PEAD_PCT",
    "factor": "NCL_HEAT_FACTOR_PCT",
    "whale_flow": "NCL_HEAT_WHALE_PCT",
    "crypto_carry": "NCL_HEAT_CRYPTOCARRY_PCT",
    "unknown": "NCL_HEAT_UNKNOWN_PCT",
}

NAV_FLOOR_CAD = float(os.getenv("NCL_HEAT_NAV_FLOOR_CAD", "30000"))


def _resolve_budgets_pct() -> dict[str, float]:
    """Read environment overrides on every call so live tuning is
    possible without bouncing the brain."""
    out = dict(DEFAULT_BUDGETS_PCT)
    for strat, env_key in ENV_KEY_MAP.items():
        env_val = os.getenv(env_key)
        if env_val is None:
            continue
        try:
            out[strat] = float(env_val)
        except ValueError:
            log.warning("[GOV] invalid %s=%r — using default %.2f", env_key, env_val, out[strat])
    return out


def _normalize_strategy(tag: Optional[str]) -> str:
    """Map free-form strategy_tags to the budget bucket they hit.

    Wave 14U HOTFIX B: added pairs/mean_reversion/pead/factor/whale_flow/
    crypto_carry aliases so quant scanner emissions get the right bucket
    (was falling to 'unknown' with $1800 cap → every $2000+ trade rejected).

    Known aliases (case-insensitive):
      goat / momentum / goat_trend       -> 'goat'
      bravo / swing / bravo_swing        -> 'bravo'
      options / theta / strangle / ...   -> 'options'
      polymarket / prediction            -> 'polymarket'
      pairs / pairs_stat_arb / stat_arb  -> 'pairs'
      mean_reversion / meanrev / mr      -> 'mean_reversion'
      pead / post_earnings_drift         -> 'pead'
      factor / factor_tilt / factor_long -> 'factor'
      whale_flow / unusual_options / uw  -> 'whale_flow'
      crypto_carry / carry / funding     -> 'crypto_carry'
      manual                             -> 'manual'
      everything else                    -> 'unknown'
    """
    if not tag:
        return "unknown"
    t = str(tag).lower().strip()
    if t in ("goat", "momentum", "goat_trend", "goat_academy"):
        return "goat"
    if t in ("bravo", "swing", "bravo_swing", "johnny_bravo"):
        return "bravo"
    if t in (
        "options", "theta", "covered_call", "cash_secured_put",
        "put_credit", "call_credit", "iron_condor", "iron_butterfly",
        "strangle", "straddle", "calendar", "diagonal",
    ):
        return "options"
    if t in ("polymarket", "prediction", "predmkt", "polymarket_kelly"):
        return "polymarket"
    if t in ("pairs", "pairs_stat_arb", "stat_arb", "statistical_arbitrage",
             "pair_trade"):
        return "pairs"
    if t in ("mean_reversion", "meanrev", "mr", "mean_rev", "reversion"):
        return "mean_reversion"
    if t in ("pead", "post_earnings_drift", "post_earnings_announcement_drift",
             "earnings_drift"):
        return "pead"
    if t in ("factor", "factor_tilt", "factor_long", "smart_beta", "value",
             "quality", "low_vol"):
        return "factor"
    if t in ("whale_flow", "whale", "unusual_options", "unusual_whales", "uw",
             "options_flow"):
        return "whale_flow"
    if t in ("crypto_carry", "carry", "funding", "perp_funding", "basis_trade"):
        return "crypto_carry"
    if t == "manual":
        return "manual"
    # Wave 14CT — brief-emitted ideas tag type="stock" or "options".
    # "stock" was falling to "unknown" → governor capped at 5% NAV →
    # any $2000+ R rejected as "Strategy 'unknown' heat would breach cap".
    # Treat brief-stock as momentum (goat-style) since that's what the
    # brief's PORTFOLIO lane typically picks.
    if t in ("stock", "stocks", "equity", "equities", "brief", "brief_stock"):
        return "goat"
    if t in ("future", "futures", "es", "nq"):
        return "manual"  # treat futures as manual until a budget bucket lands
    return "unknown"


@dataclass
class RiskDecision:
    """Container for governor output (also serializable as dict)."""

    approved: bool
    decision: str  # "approve" | "throttle" | "reject"
    reasons: list[str]
    proposed_R_dollars: float
    effective_R_dollars: float
    strategy_tag: str
    strategy_bucket: str
    nav_cad: float
    band: str
    sizing_multiplier: float
    heat: dict


async def check_proposed_trade(
    *,
    strategy_tag: str,
    R_dollars_proposed: float,
    symbol: Optional[str] = None,
    broker: Optional[str] = None,
    nav_cad_override: Optional[float] = None,
    band_override: Optional[str] = None,
) -> dict:
    """Composes J0b + J0c + heat caps in one decision.

    Caller passes the strategy_tag (free-form, normalized into budget
    buckets) and the proposed R_dollars (|entry-stop|*qty in USD-equiv
    or CAD-equiv, whichever consistent with how positions are stored —
    we treat as plain $ and let the operator pick a currency convention).

    Returns a dict (see module docstring for shape). Does NOT raise on
    rejection — callers inspect the `approved` / `decision` fields.

    `nav_cad_override` is for testing — if set, used instead of the
    portfolio_manager's live NAV. Floor: NCL_HEAT_NAV_FLOOR_CAD.

    `band_override` (Wave 14CS): accept the loop's already-normalized
    band so we don't lose the loop's NAV=$0 → band="unknown" coercion
    to a stale bucket read race. Without this, the governor was
    independently re-reading the bucket and could see band=halt during
    the few ms before the loop's set_drawdown_halt(False, "unknown")
    write propagated → false REJECT on every NAV-race tick. Audit B4.4.
    """
    from .drawdown_bucket import get_drawdown_bucket
    from .position_risk_state import get_risk_store

    # 1. Drawdown band + sizing multiplier
    bucket = await get_drawdown_bucket()
    dd_state = await bucket.get_state()
    band = dd_state.get("band", "green")
    multiplier = float(dd_state.get("sizing_multiplier", 1.0))

    # Wave 14CS — NAV=$0 guard mirroring loop.py:217-227. If the bucket
    # currently says halt but NAV is $0, treat as data-unavailable
    # rather than 100% drawdown (the portfolio sync just hasn't
    # completed yet). Operator's loop applies the same guard
    # asymmetrically; this propagates it to anyone calling the governor
    # directly (the brief pipeline + manual ops + tests).
    if band == "halt":
        try:
            nav_for_guard = float(dd_state.get("current_nav_cad") or 0)
        except (TypeError, ValueError):
            nav_for_guard = 0.0
        if nav_for_guard < 100:
            band = "unknown"
            multiplier = 1.0  # reset sizing — no halt means no haircut

    # Caller's explicit override always wins (e.g. loop passing
    # already-normalized band so the two reads can't race).
    if band_override is not None:
        band = str(band_override)

    # 2. Current heat (from PositionRiskStore aggregate)
    risk_store = await get_risk_store()
    agg = await risk_store.aggregate()
    current_total_R = float(agg.get("total_R_at_risk_usd", 0.0))
    current_by_strategy = dict(agg.get("by_strategy", {}))

    # 3. Normalize strategy tag + budgets
    bucket_name = _normalize_strategy(strategy_tag)
    budgets_pct = _resolve_budgets_pct()
    total_cap_pct = budgets_pct["total"]
    strategy_cap_pct = budgets_pct.get(bucket_name, budgets_pct["unknown"])

    # 4. Resolve NAV (preferred: live portfolio NAV in CAD)
    nav_cad = 0.0
    if nav_cad_override is not None:
        nav_cad = float(nav_cad_override)
    else:
        try:
            # Late-bind portfolio_manager to avoid hard coupling
            from .portfolio_manager import PortfolioManager  # noqa: F401
            # Prefer the singleton on whatever import path is wired up
            try:
                from ..api.routers.portfolio import _portfolio_manager as _pm  # type: ignore
            except Exception:
                _pm = None
            if _pm is not None:
                summary = _pm.get_summary("CAD")
                nav_cad = float(summary.get("total_value", 0) or 0)
        except Exception:
            nav_cad = 0.0
    if nav_cad < NAV_FLOOR_CAD:
        nav_cad = NAV_FLOOR_CAD

    # 5. Compute $ caps from %s
    total_cap_R = nav_cad * total_cap_pct / 100.0
    strategy_cap_R = nav_cad * strategy_cap_pct / 100.0
    by_strategy_cap_R = {k: nav_cad * v / 100.0 for k, v in budgets_pct.items()}

    current_strategy_R = float(current_by_strategy.get(bucket_name, 0.0))
    remaining_total_R = max(0.0, total_cap_R - current_total_R)
    remaining_strategy_R = max(0.0, strategy_cap_R - current_strategy_R)

    proposed_R = float(R_dollars_proposed or 0.0)
    effective_R = round(proposed_R * multiplier, 6)
    reasons: list[str] = []

    # 6. Decision tree
    if band == "halt":
        reasons.append(
            f"Drawdown band=halt (dd={dd_state.get('drawdown_pct')}%). All new risk blocked."
        )
        return _decision(
            approved=False, decision="reject", reasons=reasons,
            proposed_R=proposed_R, effective_R=0.0,
            strategy_tag=strategy_tag, bucket=bucket_name,
            nav_cad=nav_cad, band=band, multiplier=multiplier,
            current_total_R=current_total_R, total_cap_R=total_cap_R,
            by_strategy_current_R=current_by_strategy,
            by_strategy_cap_R=by_strategy_cap_R,
            remaining_total_R=remaining_total_R,
            remaining_strategy_R=remaining_strategy_R,
        )

    if effective_R <= 0:
        reasons.append("Proposed R is zero — nothing to allocate.")
        return _decision(
            approved=False, decision="reject", reasons=reasons,
            proposed_R=proposed_R, effective_R=effective_R,
            strategy_tag=strategy_tag, bucket=bucket_name,
            nav_cad=nav_cad, band=band, multiplier=multiplier,
            current_total_R=current_total_R, total_cap_R=total_cap_R,
            by_strategy_current_R=current_by_strategy,
            by_strategy_cap_R=by_strategy_cap_R,
            remaining_total_R=remaining_total_R,
            remaining_strategy_R=remaining_strategy_R,
        )

    if current_total_R + effective_R > total_cap_R:
        reasons.append(
            f"Total heat would breach cap: current=${current_total_R:.0f} + "
            f"effective=${effective_R:.0f} > total_cap=${total_cap_R:.0f} "
            f"({total_cap_pct:.1f}% of NAV ${nav_cad:.0f})."
        )
        return _decision(
            approved=False, decision="reject", reasons=reasons,
            proposed_R=proposed_R, effective_R=effective_R,
            strategy_tag=strategy_tag, bucket=bucket_name,
            nav_cad=nav_cad, band=band, multiplier=multiplier,
            current_total_R=current_total_R, total_cap_R=total_cap_R,
            by_strategy_current_R=current_by_strategy,
            by_strategy_cap_R=by_strategy_cap_R,
            remaining_total_R=remaining_total_R,
            remaining_strategy_R=remaining_strategy_R,
        )

    if current_strategy_R + effective_R > strategy_cap_R:
        reasons.append(
            f"Strategy '{bucket_name}' heat would breach cap: "
            f"current=${current_strategy_R:.0f} + "
            f"effective=${effective_R:.0f} > strategy_cap=${strategy_cap_R:.0f} "
            f"({strategy_cap_pct:.1f}% of NAV ${nav_cad:.0f})."
        )
        return _decision(
            approved=False, decision="reject", reasons=reasons,
            proposed_R=proposed_R, effective_R=effective_R,
            strategy_tag=strategy_tag, bucket=bucket_name,
            nav_cad=nav_cad, band=band, multiplier=multiplier,
            current_total_R=current_total_R, total_cap_R=total_cap_R,
            by_strategy_current_R=current_by_strategy,
            by_strategy_cap_R=by_strategy_cap_R,
            remaining_total_R=remaining_total_R,
            remaining_strategy_R=remaining_strategy_R,
        )

    # Approved — annotate whether throttled
    if multiplier < 1.0:
        reasons.append(
            f"Approved with throttle: drawdown band={band} -> multiplier={multiplier:.2f}. "
            f"Proposed R ${proposed_R:.0f} -> effective R ${effective_R:.0f}."
        )
        decision = "throttle"
    else:
        reasons.append(
            f"Approved at full size (band={band}). "
            f"Strategy '{bucket_name}' heat: ${current_strategy_R:.0f}/"
            f"${strategy_cap_R:.0f} ({strategy_cap_pct:.1f}% NAV)."
        )
        decision = "approve"
    return _decision(
        approved=True, decision=decision, reasons=reasons,
        proposed_R=proposed_R, effective_R=effective_R,
        strategy_tag=strategy_tag, bucket=bucket_name,
        nav_cad=nav_cad, band=band, multiplier=multiplier,
        current_total_R=current_total_R, total_cap_R=total_cap_R,
        by_strategy_current_R=current_by_strategy,
        by_strategy_cap_R=by_strategy_cap_R,
        remaining_total_R=remaining_total_R,
        remaining_strategy_R=remaining_strategy_R,
    )


def _decision(
    *,
    approved: bool,
    decision: str,
    reasons: list[str],
    proposed_R: float,
    effective_R: float,
    strategy_tag: str,
    bucket: str,
    nav_cad: float,
    band: str,
    multiplier: float,
    current_total_R: float,
    total_cap_R: float,
    by_strategy_current_R: dict,
    by_strategy_cap_R: dict,
    remaining_total_R: float,
    remaining_strategy_R: float,
) -> dict:
    return {
        "approved": approved,
        "decision": decision,
        "reasons": reasons,
        "proposed_R_dollars": round(proposed_R, 6),
        "effective_R_dollars": round(effective_R, 6),
        "strategy_tag": strategy_tag,
        "strategy_bucket": bucket,
        "nav_cad": round(nav_cad, 2),
        "band": band,
        "sizing_multiplier": multiplier,
        "heat": {
            "current_total_R": round(current_total_R, 2),
            "total_cap_R": round(total_cap_R, 2),
            "by_strategy_current_R": {k: round(v, 2) for k, v in by_strategy_current_R.items()},
            "by_strategy_cap_R": {k: round(v, 2) for k, v in by_strategy_cap_R.items()},
            "remaining_total_R": round(remaining_total_R, 2),
            "remaining_strategy_R": round(remaining_strategy_R, 2),
        },
    }


async def heat_summary(nav_cad_override: Optional[float] = None) -> dict:
    """Portfolio-level heat snapshot — used by GET /portfolio/risk-governor/heat
    and by scanners that want to display current utilization."""
    from .drawdown_bucket import get_drawdown_bucket
    from .position_risk_state import get_risk_store

    bucket = await get_drawdown_bucket()
    dd_state = await bucket.get_state()
    band = dd_state.get("band", "green")
    multiplier = float(dd_state.get("sizing_multiplier", 1.0))

    store = await get_risk_store()
    agg = await store.aggregate()
    current_total_R = float(agg.get("total_R_at_risk_usd", 0.0))
    current_by_strategy = dict(agg.get("by_strategy", {}))

    budgets_pct = _resolve_budgets_pct()
    total_cap_pct = budgets_pct["total"]

    nav_cad = 0.0
    if nav_cad_override is not None:
        nav_cad = float(nav_cad_override)
    else:
        try:
            from ..api.routers.portfolio import _portfolio_manager as _pm  # type: ignore
            if _pm is not None:
                summary = _pm.get_summary("CAD")
                nav_cad = float(summary.get("total_value", 0) or 0)
        except Exception:
            pass
    if nav_cad < NAV_FLOOR_CAD:
        nav_cad = NAV_FLOOR_CAD

    total_cap_R = nav_cad * total_cap_pct / 100.0
    by_strategy_cap_R = {k: nav_cad * v / 100.0 for k, v in budgets_pct.items()}

    # Utilization fractions (current / cap, capped at 1.0 for display)
    total_util = (current_total_R / total_cap_R) if total_cap_R > 0 else 0.0
    by_strategy_util = {
        k: (current_by_strategy.get(k, 0.0) / by_strategy_cap_R.get(k, 1.0))
        if by_strategy_cap_R.get(k, 0) > 0
        else 0.0
        for k in budgets_pct.keys()
        if k != "total"
    }

    return {
        "nav_cad": round(nav_cad, 2),
        "band": band,
        "sizing_multiplier": multiplier,
        "budgets_pct": budgets_pct,
        "total": {
            "current_R": round(current_total_R, 2),
            "cap_R": round(total_cap_R, 2),
            "utilization": round(total_util, 4),
            "remaining_R": round(max(0.0, total_cap_R - current_total_R), 2),
        },
        "by_strategy": {
            k: {
                "current_R": round(current_by_strategy.get(k, 0.0), 2),
                "cap_R": round(by_strategy_cap_R.get(k, 0.0), 2),
                "utilization": round(by_strategy_util.get(k, 0.0), 4),
                "remaining_R": round(
                    max(0.0, by_strategy_cap_R.get(k, 0.0) - current_by_strategy.get(k, 0.0)),
                    2,
                ),
            }
            for k in budgets_pct.keys()
            if k != "total"
        },
    }
