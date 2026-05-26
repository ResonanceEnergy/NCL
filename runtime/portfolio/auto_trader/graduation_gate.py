"""
Auto-Trader multi-criteria graduation gate — Wave 14K Phase 6 (K5c)

"Graduation" here means: a paper-trading strategy has accumulated
enough evidence — across sample size, hit rate, profit factor, system
quality, drawdown discipline, regime coverage, and freedom from
active drift — that an operator could *consider* it ready for live
promotion.

Wave 14K does NOT auto-promote anything. Graduation is a recommendation
surface (REST endpoint, memory unit, dashboard widget) that supports a
human decision. The "no live executor" rule from Wave 14J is intact.

The gate composes evidence from:
  - trade_idea_tracker.expectancy_by_strategy() — N, hit_rate, profit_factor,
    expectancy_R, SQN, avg_holding_days, total_R_realized
  - strategy_bandit.posterior() — Beta(α, β) credible interval lower bound
  - drift_detector.get_strategy_state() — current drift status
  - cycle_phase (if available) — confidence floor for regime coverage

Each criterion returns {passed: bool, value, threshold, reason}; the
overall gate is pass-only-if-all-criteria-pass.

Tunables (env):
  NCL_GRAD_MIN_N            — min closed trades  (default 50)
  NCL_GRAD_MIN_HIT_RATE     — min hit rate       (default 0.45)
  NCL_GRAD_MIN_PROFIT_FACTOR— min profit factor  (default 1.5)
  NCL_GRAD_MIN_SQN          — min SQN            (default 1.7)
  NCL_GRAD_MIN_EXPECTANCY_R — min expectancy R   (default 0.10)
  NCL_GRAD_MIN_LCB_HIT_RATE — min Bayesian LCB   (default 0.40)
  NCL_GRAD_MAX_DRIFT_RECENT — DRIFT_DOWN within
                              this many days bars graduation (default 14)
  NCL_GRAD_REQUIRE_CYCLE_OK — require cycle_phase confidence ≥ 0.35
                              (mixed/uncertain regimes block) (default 1)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.auto_trader.graduation_gate")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))

MIN_N = int(os.getenv("NCL_GRAD_MIN_N", "50"))
MIN_HIT_RATE = float(os.getenv("NCL_GRAD_MIN_HIT_RATE", "0.45"))
MIN_PROFIT_FACTOR = float(os.getenv("NCL_GRAD_MIN_PROFIT_FACTOR", "1.5"))
MIN_SQN = float(os.getenv("NCL_GRAD_MIN_SQN", "1.7"))
MIN_EXPECTANCY_R = float(os.getenv("NCL_GRAD_MIN_EXPECTANCY_R", "0.10"))
MIN_LCB_HIT_RATE = float(os.getenv("NCL_GRAD_MIN_LCB_HIT_RATE", "0.40"))
MAX_DRIFT_RECENT_DAYS = int(os.getenv("NCL_GRAD_MAX_DRIFT_RECENT", "14"))
REQUIRE_CYCLE_OK = bool(int(os.getenv("NCL_GRAD_REQUIRE_CYCLE_OK", "1")))


def _criterion(
    name: str,
    *,
    passed: bool,
    value: Any,
    threshold: Any,
    reason: str = "",
    weight: int = 1,
) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "value": value,
        "threshold": threshold,
        "reason": reason,
        "weight": weight,
    }


async def evaluate(strategy: str) -> dict:
    """Run the multi-criteria gate for one strategy. Returns:
      {
        strategy, evaluated_at_iso,
        graduated (bool),  # AND across all criteria
        pass_count, fail_count, total_count,
        criteria: [ {name, passed, value, threshold, reason, weight}, ... ],
        readiness_score: float (0..1, weighted),
        recommendation: str,
      }
    """
    criteria: list[dict] = []

    # 1) Sample size
    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        expectancy = await tracker.expectancy_by_strategy()
        stats = expectancy.get(strategy) or {}
    except Exception as e:
        log.warning("[GRAD] expectancy lookup failed for %s: %s", strategy, e)
        stats = {}

    n_closed = int(stats.get("n_closed") or 0)
    criteria.append(_criterion(
        "min_sample_size",
        passed=n_closed >= MIN_N,
        value=n_closed, threshold=MIN_N,
        reason=(
            f"need {MIN_N} closed paper trades; have {n_closed}"
            if n_closed < MIN_N else f"{n_closed} closed paper trades"
        ),
        weight=3,  # weighted highest — no other criterion is meaningful without it
    ))

    # 2) Hit rate
    hit_rate = float(stats.get("hit_rate") or 0.0)
    criteria.append(_criterion(
        "min_hit_rate",
        passed=hit_rate >= MIN_HIT_RATE,
        value=round(hit_rate, 4), threshold=MIN_HIT_RATE,
        reason=f"realized {hit_rate:.2%} vs floor {MIN_HIT_RATE:.0%}",
    ))

    # 3) Profit factor
    pf_raw = stats.get("profit_factor")
    if pf_raw is None:
        pf_passed = False
        pf_value: Any = None
        pf_reason = "profit factor undefined (no closed losses)"
    else:
        pf_value = round(float(pf_raw), 4)
        pf_passed = pf_value >= MIN_PROFIT_FACTOR
        pf_reason = f"realized {pf_value:.2f} vs floor {MIN_PROFIT_FACTOR:.2f}"
    criteria.append(_criterion(
        "min_profit_factor", passed=pf_passed,
        value=pf_value, threshold=MIN_PROFIT_FACTOR, reason=pf_reason,
    ))

    # 4) SQN
    sqn = float(stats.get("sqn") or 0.0)
    criteria.append(_criterion(
        "min_sqn",
        passed=sqn >= MIN_SQN,
        value=round(sqn, 4), threshold=MIN_SQN,
        reason=f"Van Tharp SQN {sqn:.2f} vs floor {MIN_SQN:.2f}",
    ))

    # 5) Expectancy R
    expectancy_r = float(stats.get("expectancy_R") or 0.0)
    criteria.append(_criterion(
        "min_expectancy_R",
        passed=expectancy_r >= MIN_EXPECTANCY_R,
        value=round(expectancy_r, 4), threshold=MIN_EXPECTANCY_R,
        reason=f"realized {expectancy_r:+.4f}R vs floor {MIN_EXPECTANCY_R:+.4f}R",
    ))

    # 6) Bandit LCB hit rate (Bayesian lower 95% credible bound)
    try:
        from .strategy_bandit import get_bandit
        bandit = await get_bandit()
        post = await bandit.posterior(strategy)
        lcb = float((post or {}).get("ci_low_95") or 0.0)
    except Exception as e:
        log.warning("[GRAD] bandit posterior lookup failed: %s", e)
        lcb = 0.0
    criteria.append(_criterion(
        "min_lcb_hit_rate",
        passed=lcb >= MIN_LCB_HIT_RATE,
        value=round(lcb, 4), threshold=MIN_LCB_HIT_RATE,
        reason=(
            f"Bayesian LCB {lcb:.2%} (lower 95% CI) vs floor "
            f"{MIN_LCB_HIT_RATE:.0%} — accounts for sample-size uncertainty"
        ),
    ))

    # 7) No recent DRIFT_DOWN
    recent_drift_down = False
    drift_reason = "no drift detector state"
    try:
        from .drift_detector import get_strategy_state
        ds = await get_strategy_state(strategy)
        if ds:
            last_iso = ds.get("last_drift_iso") or ""
            drift_count = int(ds.get("drift_down_count") or 0)
            if last_iso and drift_count > 0:
                try:
                    dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - dt).days
                    if age_days <= MAX_DRIFT_RECENT_DAYS:
                        recent_drift_down = True
                        drift_reason = (
                            f"DRIFT_DOWN signal {age_days}d ago "
                            f"(within {MAX_DRIFT_RECENT_DAYS}d window) — strategy needs "
                            f"re-validation before graduation"
                        )
                    else:
                        drift_reason = (
                            f"last DRIFT_DOWN was {age_days}d ago "
                            f"(outside {MAX_DRIFT_RECENT_DAYS}d window)"
                        )
                except ValueError:
                    drift_reason = "drift state parse error"
            else:
                drift_reason = "no DRIFT_DOWN signals on record"
    except Exception as e:
        log.warning("[GRAD] drift state lookup failed: %s", e)
    criteria.append(_criterion(
        "no_recent_drift",
        passed=not recent_drift_down,
        value=not recent_drift_down,
        threshold=True, reason=drift_reason,
    ))

    # 8) Cycle phase confidence (regime coverage proxy)
    if REQUIRE_CYCLE_OK:
        cycle_ok = True
        cycle_reason = "cycle phase check disabled or unavailable"
        try:
            cycle_path = NCL_BASE / "data" / "rotation"
            if cycle_path.exists():
                # Find most-recent cycle file
                cycle_files = sorted(cycle_path.glob("cycle-*.json"), reverse=True)
                if cycle_files:
                    import json
                    raw = json.loads(cycle_files[0].read_text())
                    conf = float(raw.get("confidence") or 0.0)
                    phase = raw.get("phase", "?")
                    cycle_ok = conf >= 0.35
                    cycle_reason = (
                        f"current cycle phase '{phase}' confidence "
                        f"{conf:.2f} {'≥' if cycle_ok else '<'} 0.35 "
                        f"(low confidence = mixed regime, bar graduation)"
                    )
        except Exception as e:
            log.warning("[GRAD] cycle phase lookup failed: %s", e)
            cycle_reason = f"cycle phase exception: {e}"
        criteria.append(_criterion(
            "cycle_phase_confident",
            passed=cycle_ok, value=None, threshold=0.35, reason=cycle_reason,
        ))

    # Aggregate
    pass_count = sum(1 for c in criteria if c["passed"])
    fail_count = len(criteria) - pass_count
    graduated = fail_count == 0
    # Weighted readiness score: weight-sum of passed / weight-sum of total
    weight_total = sum(c["weight"] for c in criteria)
    weight_passed = sum(c["weight"] for c in criteria if c["passed"])
    readiness_score = round(weight_passed / weight_total, 4) if weight_total else 0.0

    if graduated:
        recommendation = (
            f"GRADUATED — all {len(criteria)} criteria pass. Operator may "
            f"consider promotion. Wave 14K never auto-promotes — review "
            f"the full criteria table + recent reasoning chains before "
            f"any live exposure."
        )
    elif n_closed < MIN_N:
        recommendation = (
            f"NEEDS DATA — {n_closed}/{MIN_N} closed paper trades. "
            f"Continue paper trading until sample size is reached."
        )
    elif recent_drift_down:
        recommendation = (
            f"HOLD — recent drift signal. Re-validate after detector "
            f"returns to STABLE for ≥ {MAX_DRIFT_RECENT_DAYS}d."
        )
    else:
        failing = [c["name"] for c in criteria if not c["passed"]]
        recommendation = (
            f"NOT READY — {fail_count}/{len(criteria)} criteria failing: "
            f"{', '.join(failing)}. Readiness score {readiness_score:.0%}."
        )

    return {
        "strategy": strategy,
        "evaluated_at_iso": datetime.now(timezone.utc).isoformat(),
        "graduated": graduated,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "total_count": len(criteria),
        "criteria": criteria,
        "readiness_score": readiness_score,
        "recommendation": recommendation,
        "raw_stats": {
            "n_closed": n_closed, "hit_rate": hit_rate,
            "profit_factor": pf_value, "sqn": sqn,
            "expectancy_R": expectancy_r, "lcb_hit_rate": round(lcb, 4),
            "recent_drift_down": recent_drift_down,
        },
    }


async def evaluate_all() -> dict:
    """Run evaluate() for every strategy known to trade_idea_tracker.
    Returns: {strategy: report, ..., "_summary": {graduated: [..], failing: [..]}}.
    """
    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        expectancy = await tracker.expectancy_by_strategy()
    except Exception as e:
        log.warning("[GRAD] expectancy_by_strategy failed: %s", e)
        return {"_summary": {"graduated": [], "failing": [], "error": str(e)}}

    out: dict[str, Any] = {}
    grad_list: list[str] = []
    fail_list: list[str] = []
    for strat in expectancy.keys():
        if strat == "_all":
            continue
        report = await evaluate(strat)
        out[strat] = report
        (grad_list if report["graduated"] else fail_list).append(strat)
    out["_summary"] = {
        "graduated": grad_list,
        "failing": fail_list,
        "total_strategies": len(grad_list) + len(fail_list),
        "evaluated_at_iso": datetime.now(timezone.utc).isoformat(),
    }
    return out


async def list_graduated_strategies() -> list[str]:
    """Short helper: which strategies currently meet all criteria."""
    report = await evaluate_all()
    return list(report.get("_summary", {}).get("graduated", []))
