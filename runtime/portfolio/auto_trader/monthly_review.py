"""
Auto-Trader monthly portfolio review — Wave 14U-2/10

Fires 1st of month at 06:00 ET. Emits a strategy scorecard with:
  - Calmar / Sortino / Sharpe per sleeve
  - Alpha decomposition per sleeve (from factor_attribution)
  - Bandit posterior + credible interval
  - Graduation status
  - ADWIN drift events in the month
  - Retire / explore / scale recommendations
  - LLM-synthesized narrative

Output:
  - data/portfolio/auto_trader/monthly_reviews/YYYY-MM.json (scorecard)
  - data/portfolio/auto_trader/monthly_reviews/YYYY-MM.md (narrative)
  - portfolio:monthly_review memory unit at importance 90
  - Journal entry of type 'reflection' importance 85

Closes the "who's looking at this weekly?" gap. NATRIX gets a clear
monthly picture without having to run reports manually.

Scheduler hook: ncl-auto-trader-monthly-review fires at 06:00 ET on
the 1st of each month (idempotent — checks if review already written).

Tunables (env):
  NCL_MONTHLY_REVIEW_DISABLED  "1"/"0"  default "0"
  NCL_MONTHLY_REVIEW_LLM       "1"/"0"  default "1" (use Sonnet narrative)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.monthly_review")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
REVIEW_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader" / "monthly_reviews"

DISABLED = os.getenv("NCL_MONTHLY_REVIEW_DISABLED", "0") == "1"
USE_LLM = os.getenv("NCL_MONTHLY_REVIEW_LLM", "1") == "1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_key(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


def _annualize_sharpe(returns: list[float], periods_per_year: int = 252) -> float:
    """Simple Sharpe annualized from per-trade returns."""
    if not returns or len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    return (mean / std) * math.sqrt(periods_per_year) if std > 0 else 0.0


def _sortino(returns: list[float], target: float = 0.0,
              periods_per_year: int = 252) -> float:
    """Sortino: only downside deviation in denominator."""
    if not returns or len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [(r - target) ** 2 for r in returns if r < target]
    if not downside:
        return float("inf") if mean > target else 0.0
    dd = math.sqrt(sum(downside) / len(downside))
    return ((mean - target) / dd) * math.sqrt(periods_per_year) if dd > 0 else 0.0


def _calmar(returns: list[float], periods_per_year: int = 252) -> float:
    """Calmar: annualized return / max drawdown."""
    if not returns or len(returns) < 2:
        return 0.0
    # Cumulative equity curve (1 + r compounded)
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    total_ret = (equity[-1] / equity[0]) - 1.0
    ann_ret = total_ret * (periods_per_year / len(returns))
    return (ann_ret / max_dd) if max_dd > 0 else 0.0


async def _build_per_strategy_scorecard(month: str) -> dict:
    """Pull all the per-strategy metrics + decompositions."""
    out: dict[str, dict] = {}

    # Bandit posteriors
    try:
        from .strategy_bandit import get_bandit
        bandit = await get_bandit()
        all_post = await bandit.all_posteriors()
        for s, p in all_post.items():
            out.setdefault(s, {})["bandit"] = {
                "n_observed": p.get("n_observed"),
                "win_rate_mean": p.get("mean"),
                "ci_low_95": p.get("ci_low_95"),
                "ci_high_95": p.get("ci_high_95"),
                "avg_R_per_trade": p.get("avg_R_per_trade"),
            }
    except Exception as e:
        log.warning("[AT-MONTHLY] bandit pull failed: %s", e)

    # Factor attribution
    try:
        from .factor_attribution import all_attributions
        atts = await all_attributions()
        for s, a in atts.items():
            entry = out.setdefault(s, {})
            entry["factor"] = {
                "alpha": a.get("alpha"),
                "alpha_t_stat": a.get("alpha_t_stat"),
                "beta_spy": a.get("beta_spy"),
                "beta_sector": a.get("beta_sector"),
                "sharpe_alpha": a.get("sharpe_alpha"),
                "r_squared": a.get("r_squared"),
                "n_trades_in_window": a.get("n_trades"),
            }
    except Exception as e:
        log.warning("[AT-MONTHLY] factor attribution pull failed: %s", e)

    # Per-strategy returns this month — read from trade_idea_tracker
    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        all_ideas = await tracker.list_by_strategy(None)
        # Group by strategy + filter to this month
        month_prefix = month  # YYYY-MM
        for idea in all_ideas:
            iso = idea.get("issued_at_iso") or ""
            if not iso.startswith(month_prefix):
                continue
            outcome = idea.get("outcome")
            if outcome in (None, "emitted", "taken"):
                continue
            r = float(idea.get("R_multiple") or 0)
            s = str(idea.get("strategy") or "unknown")
            entry = out.setdefault(s, {})
            stats = entry.setdefault("month_stats", {
                "returns": [], "n_closed": 0,
                "wins": 0, "losses": 0, "scratches": 0,
                "sum_R": 0.0,
            })
            stats["returns"].append(r)
            stats["n_closed"] += 1
            stats["sum_R"] += r
            if r > 0:
                stats["wins"] += 1
            elif r < 0:
                stats["losses"] += 1
            else:
                stats["scratches"] += 1
    except Exception as e:
        log.warning("[AT-MONTHLY] tracker pull failed: %s", e)

    # Compute Sharpe / Sortino / Calmar per strategy from month_stats
    for s, entry in out.items():
        stats = entry.get("month_stats") or {}
        rets = stats.get("returns") or []
        if rets:
            entry["risk_metrics"] = {
                "sharpe_R": round(_annualize_sharpe(rets, periods_per_year=52), 4),
                "sortino_R": round(_sortino(rets, periods_per_year=52), 4),
                "calmar_R": round(_calmar(rets, periods_per_year=52), 4),
                "avg_R": round(sum(rets) / len(rets), 4),
                "n_closed": len(rets),
                "hit_rate": round(
                    stats.get("wins", 0) / len(rets) if rets else 0, 4),
                "sum_R": round(stats.get("sum_R", 0), 2),
            }
        else:
            entry["risk_metrics"] = {
                "sharpe_R": 0, "sortino_R": 0, "calmar_R": 0,
                "avg_R": 0, "n_closed": 0, "hit_rate": 0, "sum_R": 0,
            }
        # Drop raw returns from output (audit log has them)
        entry.pop("month_stats", None)

    # Graduation status
    try:
        from .graduation_gate import evaluate_all
        grad = await evaluate_all()
        for s, g in grad.items():
            out.setdefault(s, {})["graduation"] = {
                "graduated": g.get("graduated"),
                "pass_count": g.get("pass_count"),
                "fail_count": g.get("fail_count"),
            }
    except Exception as e:
        log.warning("[AT-MONTHLY] graduation gate pull failed: %s", e)

    return out


def _recommend(entry: dict) -> str:
    """Single-line recommendation per strategy."""
    bandit = entry.get("bandit") or {}
    factor = entry.get("factor") or {}
    risk = entry.get("risk_metrics") or {}
    grad = entry.get("graduation") or {}

    n = bandit.get("n_observed") or 0
    alpha = factor.get("alpha") or 0
    t_stat = factor.get("alpha_t_stat") or 0
    sharpe = risk.get("sharpe_R") or 0
    hit_rate = risk.get("hit_rate") or 0
    ci_low = bandit.get("ci_low_95") or 0

    if n < 10:
        return "explore — insufficient sample (N<10); keep collecting data"
    if alpha > 0 and t_stat > 2 and sharpe > 0.5:
        return f"scale — real alpha (α={alpha:+.4f}, t={t_stat:.1f}, Sharpe={sharpe:.2f})"
    if sharpe < 0 and ci_low < 0.3 and n >= 30:
        return f"retire — N={n}, Sharpe={sharpe:.2f}, CI_low={ci_low:.2f}"
    if grad.get("graduated"):
        return "GRADUATED — eligible for live consideration"
    return f"hold — N={n}, hit-rate={hit_rate:.1%}, Sharpe={sharpe:.2f}"


async def build_scorecard(month: Optional[str] = None) -> dict:
    """Build the full month scorecard dict."""
    month = month or _month_key()
    per_strat = await _build_per_strategy_scorecard(month)
    recommendations = {s: _recommend(entry) for s, entry in per_strat.items()}

    # ADWIN portfolio drift state
    adwin = {}
    try:
        from .portfolio_drift import get_state as port_drift_state
        adwin = await port_drift_state()
    except Exception:
        pass

    # Drawdown band
    dd_band = "unknown"
    try:
        from ..drawdown_bucket import get_drawdown_state
        dd = await get_drawdown_state()
        dd_band = dd.get("band", "unknown")
    except Exception:
        pass

    return {
        "month": month,
        "generated_at_iso": _now_iso(),
        "strategies": per_strat,
        "recommendations": recommendations,
        "adwin_portfolio_drift": adwin,
        "drawdown_band": dd_band,
        "wave": "14U-2/10",
    }


async def _llm_narrative(scorecard: dict) -> str:
    """Optional Sonnet 4 brief synthesis. Budget-gated; returns empty
    string if budget exhausted or LLM disabled."""
    if not USE_LLM:
        return ""
    try:
        from runtime.cost_tracker import can_spend
        if not can_spend("anthropic", 0.10):
            return ""
        from runtime.llms.facade import call_llm
        # Compact scorecard for prompt
        compact_strats = {}
        for s, entry in (scorecard.get("strategies") or {}).items():
            compact_strats[s] = {
                "n": (entry.get("bandit") or {}).get("n_observed"),
                "win_rate": (entry.get("bandit") or {}).get("win_rate_mean"),
                "sharpe": (entry.get("risk_metrics") or {}).get("sharpe_R"),
                "alpha": (entry.get("factor") or {}).get("alpha"),
                "recommendation": scorecard["recommendations"].get(s),
            }
        prompt = (
            f"Monthly auto-trader review for {scorecard['month']}. "
            f"Drawdown band: {scorecard['drawdown_band']}. "
            f"Per-strategy compact stats: {json.dumps(compact_strats)}. "
            f"Write a 4-paragraph review for NATRIX (the operator): "
            f"(1) overall portfolio health + drawdown context, "
            f"(2) which strategies are showing real alpha vs which are noise, "
            f"(3) retire/explore/scale recommendations summary, "
            f"(4) one specific tactical action for next month. "
            f"Plain prose. No markdown headers. Crisp, actionable."
        )
        out = await call_llm(
            model="claude-sonnet-4-20250514",
            prompt=prompt,
            max_tokens=1500,
            system="You are NCL's portfolio review writer. Plain prose, no markdown.",
        )
        return (out or "").strip() if isinstance(out, str) else ""
    except Exception as e:
        log.warning("[AT-MONTHLY] LLM narrative failed: %s", e)
        return ""


async def run_monthly_review(*, month: Optional[str] = None,
                               brain=None,
                               force: bool = False) -> dict:
    """Top-level entry — builds scorecard, optionally LLM narrative,
    persists to disk, emits memory unit + journal entry.

    force=True overrides the "already generated this month" idempotency check.
    """
    if DISABLED:
        return {"disabled": True}
    month = month or _month_key()
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REVIEW_DIR / f"{month}.json"
    md_path = REVIEW_DIR / f"{month}.md"

    if json_path.exists() and not force:
        log.info("[AT-MONTHLY] %s already exists — skip (force=False)", json_path)
        return {"skipped": True, "reason": "already_generated", "path": str(json_path)}

    log.info("[AT-MONTHLY] building scorecard for %s", month)
    scorecard = await build_scorecard(month=month)

    narrative = await _llm_narrative(scorecard)
    scorecard["narrative"] = narrative

    json_path.write_text(json.dumps(scorecard, indent=2, sort_keys=True, default=str))

    # Plain-text markdown for human reading
    md_lines = [
        f"# NCL Auto-Trader Monthly Review — {month}",
        f"_Generated {scorecard['generated_at_iso'][:19]}Z_",
        "",
        f"Drawdown band: **{scorecard['drawdown_band']}**",
        "",
        "## Per-strategy scorecard",
        "",
        "| Strategy | N | Win-rate | Sharpe | Alpha | Sortino | Calmar | Recommendation |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s, entry in (scorecard.get("strategies") or {}).items():
        b = entry.get("bandit") or {}
        f = entry.get("factor") or {}
        r = entry.get("risk_metrics") or {}
        rec = scorecard["recommendations"].get(s, "")
        md_lines.append(
            f"| {s} | {b.get('n_observed', 0)} | "
            f"{(b.get('win_rate_mean') or 0):.1%} | "
            f"{(r.get('sharpe_R') or 0):.2f} | "
            f"{(f.get('alpha') or 0):+.4f} | "
            f"{(r.get('sortino_R') or 0):.2f} | "
            f"{(r.get('calmar_R') or 0):.2f} | "
            f"{rec} |"
        )
    if narrative:
        md_lines += ["", "## Narrative", "", narrative]
    md_path.write_text("\n".join(md_lines))

    # Memory unit
    try:
        if brain is not None:
            mem = getattr(brain, "memory_store", None)
            if mem and hasattr(mem, "create_unit"):
                rec_summary = "; ".join(
                    f"{s}: {r}" for s, r in
                    list(scorecard["recommendations"].items())[:10]
                )
                await mem.create_unit(
                    content=(
                        f"AUTO-TRADER MONTHLY REVIEW {month}: "
                        f"drawdown_band={scorecard['drawdown_band']}. "
                        f"Recommendations — {rec_summary}. "
                        f"Full scorecard at {json_path}."
                    ),
                    source="portfolio:monthly_review",
                    importance=90.0,
                    tags=["portfolio", "auto_trader", "monthly_review",
                          f"month:{month}"],
                    memory_type="semantic",
                    metadata={
                        "month": month,
                        "recommendations": scorecard["recommendations"],
                        "drawdown_band": scorecard["drawdown_band"],
                        "wave": "14U-2/10",
                    },
                )
    except Exception as e:
        log.warning("[AT-MONTHLY] memory unit emit failed: %s", e)

    # Journal entry of type reflection
    try:
        from runtime.journal.store import create_entry
        await create_entry(
            kind="reflection",
            content=narrative or json.dumps(scorecard["recommendations"], indent=2),
            title=f"Auto-Trader Monthly Review — {month}",
            tags=["auto_trader", "monthly_review", "portfolio"],
            importance=85,
            source="auto_trader:monthly_review",
        )
    except Exception as e:
        log.debug("[AT-MONTHLY] journal entry skipped: %s", e)

    log.info("[AT-MONTHLY] %s scorecard written (%d strategies)",
             month, len(scorecard.get("strategies") or {}))
    return {
        "ok": True,
        "month": month,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "strategies": list((scorecard.get("strategies") or {}).keys()),
        "narrative_chars": len(narrative),
    }


async def monthly_review_loop(brain) -> None:
    """Scheduler task. Sleeps until next 1st-of-month 06:00 ET, fires
    run_monthly_review, repeats."""
    log.info("[AT-MONTHLY] monthly review loop started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Compute next 1st of month at 10:00 UTC (≈ 06:00 ET in DST)
            if now.month == 12:
                next_run = datetime(now.year + 1, 1, 1, 10, 0, 0,
                                     tzinfo=timezone.utc)
            else:
                next_run = datetime(now.year, now.month + 1, 1, 10, 0, 0,
                                     tzinfo=timezone.utc)
            sleep_s = max(60, (next_run - now).total_seconds())
            log.info("[AT-MONTHLY] sleeping %.0fs until %s",
                     sleep_s, next_run.isoformat())
            await asyncio.sleep(sleep_s)
            try:
                await run_monthly_review(brain=brain)
            except Exception as e:
                log.error("[AT-MONTHLY] review run failed: %s", e, exc_info=True)
        except asyncio.CancelledError:
            log.info("[AT-MONTHLY] loop cancelled")
            return
        except Exception as e:
            log.error("[AT-MONTHLY] outer loop error: %s", e)
            await asyncio.sleep(3600)


__all__ = [
    "run_monthly_review",
    "build_scorecard",
    "monthly_review_loop",
]
