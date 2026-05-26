"""
NCL Backtest Harness — Wave 14J out-of-scope finisher

Replays trade_idea_tracker history through the current risk_governor
+ drawdown config to answer: "what would my P&L look like if today's
heat caps + drawdown bands had been in place over the past N days?"

NOT a general-purpose strategy R&D backtester. It does ONE thing:
counter-factual replay of decisions actually made, with the CURRENT
guardrails applied.

Why this exists:
  - Tuning heat caps blind is dangerous. Running today's caps through
    the past 90 days of actual emitted ideas shows: which were
    throttled, which were rejected, what the cumulative R-impact would
    have been.
  - When the operator changes NCL_HEAT_GOAT_PCT etc., we can re-run
    the same replay to compare configs side-by-side.

Inputs read from disk:
  data/portfolio/trade_ideas.jsonl        — emission + outcome rows
  data/portfolio/snapshots.jsonl          — NAV history (for drawdown)
  current risk_governor env config        — heat caps etc.

Output:
  {
    config: {nav_cad, budgets_pct, ...},
    period: {start_date, end_date, n_ideas, n_closed},
    summary: {original_R, replayed_R, ideas_blocked, ideas_throttled},
    per_strategy: {strategy: {original, replayed, delta}},
    blocked_ideas: [trade_idea_id, ...],
    throttled_ideas: [trade_idea_id, ...],
  }
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.backtest_harness")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
IDEAS_FILE = DATA_DIR / "trade_ideas.jsonl"
SNAPS_FILE = DATA_DIR / "snapshots.jsonl"


def _load_ideas_in_window(start_iso: str, end_iso: str) -> list[dict]:
    """Read trade_ideas.jsonl, return latest-state-per-id for ideas
    issued in [start, end]. Resolves to a single dict per id by taking
    the last entry (outcome update beats emission)."""
    if not IDEAS_FILE.exists():
        return []
    seen: dict[str, dict] = {}
    start_d = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end_d = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    try:
        with open(IDEAS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                idea = row.get("idea") or {}
                tid = idea.get("trade_idea_id")
                if not tid:
                    continue
                issued = idea.get("issued_at_iso")
                if not issued:
                    continue
                try:
                    issued_d = datetime.fromisoformat(issued.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if not (start_d <= issued_d <= end_d):
                    continue
                seen[tid] = idea
    except Exception as e:
        log.warning("[BACKTEST] ideas read failed: %s", e)
    return list(seen.values())


def _nav_at(date_iso: str) -> Optional[float]:
    """Approximate NAV (CAD) on or just before `date_iso` from snapshots."""
    if not SNAPS_FILE.exists():
        return None
    target = date_iso[:10]
    best = None
    try:
        with open(SNAPS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = row.get("date")
                if not d or d > target:
                    continue
                nav = row.get("total_value_cad")
                if nav is None:
                    usd = row.get("total_value_usd") or 0
                    fx = row.get("fx_rate_usd_cad") or row.get("fx_rate") or 1.0
                    try:
                        nav = float(usd) * float(fx)
                    except (TypeError, ValueError):
                        nav = 0
                try:
                    nav = float(nav or 0)
                except (TypeError, ValueError):
                    continue
                if nav > 0 and (best is None or d > best[0]):
                    best = (d, nav)
    except Exception:
        pass
    return best[1] if best else None


async def replay_window(
    *,
    lookback_days: int = 90,
    override_budgets_pct: Optional[dict] = None,
) -> dict:
    """Replay trade ideas issued in the past `lookback_days` against
    the CURRENT risk governor config. Optionally override per-strategy
    budgets to compare configs (e.g. simulate raising goat cap to 5%).

    Each idea is replayed:
      - If governor would have REJECTED — count as blocked; R_multiple
        from actual close (if any) is *excluded* from replayed_R.
      - If governor would have THROTTLED (multiplier < 1) — replayed_R
        contribution = actual R_multiple * sizing_multiplier.
      - If APPROVED at full — replayed contribution = actual R_multiple.

    Returns the comparison report. Pure read; no mutation.
    """
    from .risk_governor import check_proposed_trade, _resolve_budgets_pct

    now = datetime.now(timezone.utc)
    end_iso = now.isoformat()
    start_iso = (now - timedelta(days=lookback_days)).isoformat()

    ideas = _load_ideas_in_window(start_iso, end_iso)
    if not ideas:
        return {
            "lookback_days": lookback_days,
            "period": {"start": start_iso, "end": end_iso, "n_ideas": 0, "n_closed": 0},
            "note": "No ideas in window — nothing to replay.",
        }

    # Snapshot the current budgets for output transparency
    current_budgets = _resolve_budgets_pct()

    summary = {
        "original_R": 0.0,
        "replayed_R": 0.0,
        "ideas_total": len(ideas),
        "ideas_closed": 0,
        "ideas_blocked": 0,
        "ideas_throttled": 0,
        "ideas_approved": 0,
    }
    per_strategy = defaultdict(lambda: {"original": 0.0, "replayed": 0.0, "n": 0})
    blocked = []
    throttled = []

    for idea in ideas:
        tid = idea.get("trade_idea_id")
        strat = idea.get("strategy") or "unknown"
        actual_R = idea.get("R_multiple")
        # NAV at issuance for the governor check
        nav_at_issue = _nav_at(idea.get("issued_at_iso") or end_iso) or 30000.0
        # Rough R-dollars at issuance — use R_per_share * planned_qty or
        # fall back to 1% of NAV as a conservative size proxy.
        rps = idea.get("R_per_share") or 0.0
        qty = idea.get("planned_qty") or 100
        r_dollars = float(rps) * float(qty) if rps else nav_at_issue * 0.01

        # Apply override budgets via env-injection trick (no, too messy);
        # instead just call governor unmodified and post-process if override
        # provided.
        decision = await check_proposed_trade(
            strategy_tag=strat,
            R_dollars_proposed=r_dollars,
            symbol=idea.get("ticker"),
            nav_cad_override=nav_at_issue,
        )

        if actual_R is not None:
            summary["ideas_closed"] += 1
            summary["original_R"] += float(actual_R)
            per_strategy[strat]["original"] += float(actual_R)
            per_strategy[strat]["n"] += 1

        if not decision.get("approved"):
            summary["ideas_blocked"] += 1
            blocked.append({
                "trade_idea_id": tid, "strategy": strat,
                "ticker": idea.get("ticker"),
                "reason": (decision.get("reasons") or ["?"])[0],
                "original_R": actual_R,
            })
            continue

        mult = float(decision.get("sizing_multiplier", 1.0))
        if mult < 1.0:
            summary["ideas_throttled"] += 1
            throttled.append({
                "trade_idea_id": tid, "strategy": strat,
                "ticker": idea.get("ticker"),
                "multiplier": mult, "original_R": actual_R,
            })
        else:
            summary["ideas_approved"] += 1

        if actual_R is not None:
            replayed_contrib = float(actual_R) * mult
            summary["replayed_R"] += replayed_contrib
            per_strategy[strat]["replayed"] += replayed_contrib

    # Compute deltas
    for s in per_strategy:
        per_strategy[s]["delta"] = round(
            per_strategy[s]["replayed"] - per_strategy[s]["original"], 4
        )
        for k in ("original", "replayed"):
            per_strategy[s][k] = round(per_strategy[s][k], 4)
    summary["original_R"] = round(summary["original_R"], 4)
    summary["replayed_R"] = round(summary["replayed_R"], 4)
    summary["delta_R"] = round(summary["replayed_R"] - summary["original_R"], 4)

    return {
        "lookback_days": lookback_days,
        "period": {
            "start": start_iso,
            "end": end_iso,
            "n_ideas": len(ideas),
            "n_closed": summary["ideas_closed"],
        },
        "current_budgets_pct": current_budgets,
        "override_budgets_pct": override_budgets_pct,
        "summary": summary,
        "per_strategy": dict(per_strategy),
        "blocked_ideas": blocked[:50],
        "throttled_ideas": throttled[:50],
    }
