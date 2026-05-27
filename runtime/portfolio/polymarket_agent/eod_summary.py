"""
Polymarket agent EOD summary — Wave 14R R6

Daily summary of agent activity:
  - bets placed today (by side, by cluster)
  - resolutions today (W/L/manual)
  - realized P/L today
  - bankroll trajectory
  - top open positions by stake
  - calibration check: for resolved bets, mean(stated_prob) vs actual

Outputs:
  - dict summary (consumed by /polymarket-agent/eod-summary REST)
  - journal entry (importance 70, source "auto:polymarket_agent")
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from .state import get_state
from .paper_engine import get_engine

log = logging.getLogger("ncl.portfolio.polymarket_agent.eod_summary")


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def build_eod_summary(brain=None) -> dict:
    engine = get_engine()
    state = await get_state()

    today = _today_utc()
    closed = engine.list_closed(limit=1000)
    today_closed = [c for c in closed if (c.get("exit_at_iso") or "").startswith(today)]
    wins = sum(1 for c in today_closed if c.get("status") == "resolved_win")
    losses = sum(1 for c in today_closed if c.get("status") == "resolved_loss")
    manual = sum(1 for c in today_closed if c.get("status") == "closed_manual")
    pl_today = sum(float(c.get("realized_pl_usd") or 0) for c in today_closed)

    open_bets = [b.to_dict() for b in engine.list_open()]
    open_count = len(open_bets)
    open_stake = sum(float(b.get("stake_usd") or 0) for b in open_bets)

    # Cluster breakdown of open bets
    try:
        from runtime.portfolio.polymarket_discipline import cluster_id_from_metadata
        cluster_breakdown: Counter = Counter()
        for b in open_bets:
            cluster_breakdown[
                cluster_id_from_metadata({
                    "title": b.get("market_question", ""),
                    "slug": b.get("market_slug", ""),
                    "end_date_year": (
                        (b.get("end_date_iso") or "")[:4]
                        if b.get("end_date_iso") else ""
                    ),
                })
            ] += float(b.get("stake_usd") or 0)
        cluster_top = sorted(cluster_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]
    except Exception:
        cluster_top = []

    # Calibration on today's resolved bets
    calibration = None
    decisive = [c for c in today_closed if c.get("status") in ("resolved_win", "resolved_loss")]
    if decisive:
        # Mean stated prob (as recorded at entry) vs hit rate
        stated_avg = (
            sum(float(c.get("edge_pp_at_entry") or 0) for c in decisive) / len(decisive)
        )
        actual_hit_rate = sum(1 for c in decisive if c.get("status") == "resolved_win") / len(decisive)
        calibration = {
            "n_decisive": len(decisive),
            "mean_edge_pp_at_entry": round(stated_avg, 2),
            "actual_hit_rate": round(actual_hit_rate, 3),
        }

    summary = {
        "date_utc": today,
        "built_at_iso": datetime.now(timezone.utc).isoformat(),
        "active": state.active,
        "paused_by": state.paused_by,
        "bankroll_usd": state.current_bankroll_usd,
        "starting_bankroll_usd": state.starting_bankroll_usd,
        "bankroll_pct_change_lifetime": round(
            (state.current_bankroll_usd / state.starting_bankroll_usd - 1) * 100, 2,
        ) if state.starting_bankroll_usd > 0 else 0,
        "today": {
            "edges_evaluated": state.edges_evaluated_today,
            "bets_placed": state.bets_placed_today,
            "bets_skipped": state.bets_skipped_today,
            "resolutions": len(today_closed),
            "wins": wins,
            "losses": losses,
            "closed_manual": manual,
            "realized_pl_usd": round(pl_today, 2),
        },
        "open_positions": {
            "count": open_count,
            "total_stake_usd": round(open_stake, 2),
            "cluster_top5": cluster_top,
        },
        "lifetime_stats": engine.stats(),
        "calibration_today": calibration,
    }

    # Emit journal entry — fire-and-forget
    if brain is not None and hasattr(brain, "memory_store"):
        try:
            mem = brain.memory_store
            content = (
                f"POLYMARKET AGENT EOD {today}: "
                f"placed={state.bets_placed_today} resolved={len(today_closed)} "
                f"W/L={wins}/{losses} pl=${pl_today:+.2f} "
                f"bankroll=${state.current_bankroll_usd:.2f} "
                f"open={open_count} (${open_stake:.0f})"
            )
            import asyncio as _aio
            _aio.create_task(mem.create_unit(
                content=content,
                source="auto:polymarket_agent",
                importance=70,
                tags=["polymarket_agent", "eod_summary", today],
                memory_type="episodic",
                metadata={"summary": summary},
            ))
        except Exception as e:
            log.debug("[POLY-EOD] journal write failed: %s", e)

    return summary
