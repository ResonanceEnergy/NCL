"""
Polymarket agent main decision + resolution loops — Wave 14R R5

Two loops:
  poly_decision_loop  — 5min market / 30min off-hours. Reads collector
                        cache → computes edges → for each positive edge:
                        kelly_size → cluster heat check → open paper bet.
  poly_resolution_loop — 5min. Checks open bets against today's collector
                        cache: if endDate passed AND market lifecycle is
                        "resolved", auto-close at terminal price.

Self-learning hooks (post-resolution):
  - bandit.record_result(strategy="polymarket_edge", won=bool)
  - drift_detector update
  - Calibration: track stated_probability vs actual outcome per
    prediction_id for Brier score / reliability diagram (queued for
    Wave 14R+1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .collector_loop import read_today_cache
from .edge_engine import compute_edges, EdgeOpportunity
from .paper_engine import get_engine
from .state import (
    get_state, is_active, record_tick, increment_counter, adjust_bankroll,
)

log = logging.getLogger("ncl.portfolio.polymarket_agent.loop")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))

LOOP_INTERVAL_S = int(os.getenv("NCL_POLY_LOOP_INTERVAL_S", "300"))           # 5min
LOOP_OFF_INTERVAL_S = int(os.getenv("NCL_POLY_LOOP_OFF_S", "1800"))           # 30min
RESOLUTION_INTERVAL_S = int(os.getenv("NCL_POLY_RESOLUTION_INTERVAL_S", "300"))
KELLY_FRACTIONAL = float(os.getenv("NCL_POLY_KELLY_FRACTIONAL", "0.25"))
MAX_OPENS_PER_TICK = int(os.getenv("NCL_POLY_MAX_OPENS_PER_TICK", "2"))
MAX_OPENS_PER_DAY = int(os.getenv("NCL_POLY_MAX_OPENS_PER_DAY", "8"))
MIN_STAKE_USD = float(os.getenv("NCL_POLY_MIN_STAKE_USD", "5"))
MAX_STAKE_PCT_BANKROLL = float(os.getenv("NCL_POLY_MAX_STAKE_PCT", "0.05"))  # 5% per bet cap


def _is_market_hours() -> bool:
    now = datetime.now(timezone.utc)
    return now.weekday() < 5 and 13 <= now.hour < 21


async def _build_open_market_lookup() -> dict:
    """slug → market dict from today's collector cache."""
    markets = read_today_cache()
    return {m.get("slug"): m for m in markets if m.get("slug")}


async def _open_one(
    opp: EdgeOpportunity,
    bankroll_usd: float,
) -> Optional[dict]:
    """Apply Kelly sizing + cluster/heat caps + open the paper bet.
    Returns the bet dict on success, None on skip with reason logged."""
    from runtime.portfolio.polymarket_discipline import (
        kelly_size, cluster_id_from_metadata,
    )

    # Estimated prob = our stated probability; market_yes_price is what
    # Polymarket implies. For NO bets we flip both.
    if opp.side == "YES":
        p_est = opp.prediction_stated_probability
        p_mkt = opp.market_yes_price
    else:
        p_est = 1.0 - (opp.prediction_stated_probability or 0)
        p_mkt = 1.0 - opp.market_yes_price

    if not p_est or not (0 < p_est < 1) or not (0 < p_mkt < 1):
        log.debug("[POLY-LOOP] skip %s — bad probs", opp.market_slug)
        return None

    sizing = kelly_size(
        prob_estimated=p_est,
        prob_market=p_mkt,
        bankroll_usd=bankroll_usd,
        days_to_resolution=opp.days_to_resolution,
        fractional=KELLY_FRACTIONAL,
    )
    if sizing.get("side") == "PASS":
        log.info("[POLY-LOOP] skip %s — kelly PASS: %s", opp.market_slug, sizing.get("reasons"))
        await increment_counter("bets_skipped_today")
        return None
    raw_size = float(sizing.get("size_usd", 0))
    cap = bankroll_usd * MAX_STAKE_PCT_BANKROLL
    size = min(raw_size, cap)
    if size < MIN_STAKE_USD:
        log.info(
            "[POLY-LOOP] skip %s — size $%.2f < min $%.2f",
            opp.market_slug, size, MIN_STAKE_USD,
        )
        await increment_counter("bets_skipped_today")
        return None

    # Cluster heat — read all currently-open bets and aggregate by cluster
    engine = get_engine()
    open_bets = engine.list_open()
    cluster = cluster_id_from_metadata({
        "title": opp.market_question,
        "slug": opp.market_slug,
        "end_date_year": (
            (opp.market_end_date_iso or "")[:4] if opp.market_end_date_iso else ""
        ),
    })
    cluster_exposure = sum(
        b.stake_usd for b in open_bets
        if cluster_id_from_metadata({
            "title": b.market_question, "slug": b.market_slug,
            "end_date_year": (b.end_date_iso or "")[:4] if b.end_date_iso else "",
        }) == cluster
    )
    cluster_cap = bankroll_usd * 0.10  # 10% of bankroll per cluster
    if cluster_exposure + size > cluster_cap:
        log.info(
            "[POLY-LOOP] skip %s — cluster %s exposure $%.2f + $%.2f > cap $%.2f",
            opp.market_slug, cluster, cluster_exposure, size, cluster_cap,
        )
        await increment_counter("bets_skipped_today")
        return None

    bet = await engine.open_bet(
        market_slug=opp.market_slug,
        market_question=opp.market_question,
        side=opp.side,
        entry_price=opp.market_yes_price,
        stake_usd=size,
        end_date_iso=opp.market_end_date_iso,
        edge_pp_at_entry=opp.edge_pp,
        prediction_id=opp.prediction_id,
        prediction_title=opp.prediction_title,
        edge_terms=opp.overlap_terms,
        notes=(
            f"kelly={sizing.get('fractional_kelly', 0):.4f} "
            f"time_disc={sizing.get('time_discount', 1):.3f} "
            f"days_to_res={opp.days_to_resolution}"
        ),
    )
    # Reserve bankroll
    await adjust_bankroll(-bet.stake_usd, reason=f"open {bet.bet_id}")
    await increment_counter("bets_placed_today")
    return bet.to_dict()


async def _decision_tick(brain=None) -> dict:
    """One tick — returns summary."""
    if not await is_active():
        return {"ok": False, "reason": "agent paused"}

    state = await get_state()
    if state.bets_placed_today >= MAX_OPENS_PER_DAY:
        return {"ok": False, "reason": "max_opens_per_day reached"}

    markets = read_today_cache()
    if not markets:
        log.warning("[POLY-LOOP] no markets in cache (collector hasn't run yet?)")
        return {"ok": False, "reason": "no markets in cache"}

    edges = compute_edges(markets)
    await increment_counter("edges_evaluated_today", delta=len(edges))
    if not edges:
        return {"ok": True, "edges": 0, "opens": 0}

    bankroll = state.current_bankroll_usd
    opened: list[dict] = []
    for opp in edges[:MAX_OPENS_PER_TICK]:
        # Dedup: skip if we already have an open bet on this slug
        if any(b.market_slug == opp.market_slug for b in get_engine().list_open()):
            continue
        bet = await _open_one(opp, bankroll)
        if bet:
            opened.append(bet)
            bankroll -= bet["stake_usd"]
        if len(opened) >= MAX_OPENS_PER_TICK:
            break

    await record_tick("loop")
    log.info(
        "[POLY-LOOP] tick: %d edges, %d new bets (bankroll now $%.2f)",
        len(edges), len(opened), bankroll,
    )
    return {"ok": True, "edges": len(edges), "opens": len(opened), "bankroll_usd": bankroll}


async def poly_decision_loop(brain=None) -> None:
    log.info("[POLY-LOOP] decision loop starting (interval %ds market / %ds off)",
             LOOP_INTERVAL_S, LOOP_OFF_INTERVAL_S)
    while True:
        try:
            await _decision_tick(brain=brain)
        except Exception as e:
            log.error("[POLY-LOOP] tick raised: %s", e, exc_info=True)
        secs = LOOP_INTERVAL_S if _is_market_hours() else LOOP_OFF_INTERVAL_S
        await asyncio.sleep(secs)


# ─── Resolution loop ─────────────────────────────────────────────────

async def _resolve_one(bet, market_dict: Optional[dict], brain=None) -> Optional[dict]:
    """Check if bet should be auto-closed. Returns resolution summary or None."""
    engine = get_engine()
    end_iso = bet.end_date_iso
    if not end_iso:
        return None
    try:
        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if datetime.now(timezone.utc) < end_dt:
        return None

    # End date passed. Need outcome — check if collector cache marks
    # the market as resolved with a terminal price.
    if market_dict is None:
        # Market not in today's cache (likely rolled off post-resolution).
        # Conservative: close at current visible price if available, else
        # mark as cancelled so it doesn't sit open forever.
        log.warning(
            "[POLY-RES] bet %s past endDate but market %s not in cache — closing manual",
            bet.bet_id, bet.market_slug,
        )
        resolved = await engine.close_manual(
            bet.bet_id, exit_price=bet.entry_price,
            notes="market rolled off cache after endDate",
        )
        return resolved.to_dict()

    yes_price = market_dict.get("yes_price")
    lifecycle = market_dict.get("lifecycle_status", "active")

    if lifecycle == "resolved" and isinstance(yes_price, (int, float)):
        # Terminal price says who won
        outcome = "YES_WON" if yes_price >= 0.5 else "NO_WON"
        resolved = await engine.resolve_bet(bet.bet_id, outcome=outcome)
        # Bankroll: realized stake + profit
        proceeds = bet.stake_usd + (resolved.realized_pl_usd or 0)
        await adjust_bankroll(proceeds, reason=f"resolved {bet.bet_id}")
        await increment_counter("resolutions_today")

        # Self-learning feedback — log to existing bandit if available
        try:
            from runtime.portfolio.auto_trader.strategy_bandit import (
                get_bandit,
            )
            bandit = get_bandit()
            won = resolved.status == "resolved_win"
            await bandit.record_result(
                strategy="polymarket_edge",
                won=won,
                metadata={
                    "bet_id": bet.bet_id,
                    "edge_pp": bet.edge_pp_at_entry,
                    "prediction_id": bet.prediction_id,
                },
            )
        except Exception as e:
            log.debug("[POLY-RES] bandit feedback skipped: %s", e)

        return resolved.to_dict()

    return None


async def _resolution_tick(brain=None) -> dict:
    engine = get_engine()
    open_bets = engine.list_open()
    if not open_bets:
        return {"ok": True, "resolved": 0}
    lookup = await _build_open_market_lookup()
    resolved_count = 0
    for bet in open_bets:
        try:
            res = await _resolve_one(bet, lookup.get(bet.market_slug), brain=brain)
            if res:
                resolved_count += 1
        except Exception as e:
            log.error("[POLY-RES] resolve %s failed: %s", bet.bet_id, e)
    await record_tick("resolution")
    if resolved_count:
        log.info("[POLY-RES] tick: resolved %d bets", resolved_count)
    return {"ok": True, "resolved": resolved_count, "open_after": len(engine.list_open())}


async def poly_resolution_loop(brain=None) -> None:
    log.info("[POLY-RES] resolution loop starting (interval %ds)", RESOLUTION_INTERVAL_S)
    while True:
        try:
            await _resolution_tick(brain=brain)
        except Exception as e:
            log.error("[POLY-RES] tick raised: %s", e, exc_info=True)
        await asyncio.sleep(RESOLUTION_INTERVAL_S)
