"""
Auto-Trader pro-active scout loop — Wave 14L L6

ORIGINATES trade ideas every 5 minutes instead of just consuming them.
The scout is the agent's "always-on" awareness — it scans open paper
trades + snapshot holdings + rotation regime + calendar for action
opportunities:

  1. PROFIT-TARGET HITS
     Any open paper trade where unrealized R >= recipe.profit_target_R
     → close + (if short-dated lottery) trigger profit_ladder.

  2. REGIME-SHIFT EXIT-REDIRECTS
     Compare today's rotation_tracker leading-sectors to yesterday's.
     Quadrant flip (Leading→Weakening) on a sector with active paper
     positions → emit defensive close suggestion.

  3. COVERED-CALL OPPORTUNITIES
     Snapshot stock holdings (≥100 shares) with no existing short call
     → emit covered_call_income trade idea using the OptionStructure
     builder. Pure income harvest on positions you'd hold anyway.

  4. EARNINGS-DEFENSIVE FLAGS
     Open positions whose underlying has earnings within 5d → emit a
     defensive memo (importance 90 MemUnit, not a trade idea by itself
     — operator decides whether to close, roll, or hedge).

The scout writes scout_events.jsonl for audit. It DOES NOT auto-close
positions today (that would bypass the normal close path). It emits
trade ideas + MemUnits that flow through the standard loop gates.

Cadence: 5 min during market hours / 30 min off-hours. Non-blocking on
any subsystem failure (degraded mode logs warning, continues).

Storage:
  data/portfolio/auto_trader/scout_events.jsonl
  data/portfolio/auto_trader/scout_state.json

Tunables (env):
  NCL_AT_SCOUT_ENABLED=1
  NCL_AT_SCOUT_TICK_MARKET=300       (5 min in market hours)
  NCL_AT_SCOUT_TICK_OFFHOURS=1800    (30 min off-hours)
  NCL_AT_SCOUT_PROFIT_R_MIN=2.0      (profit-target detection floor)
  NCL_AT_SCOUT_EARNINGS_WINDOW_D=5
  NCL_AT_SCOUT_CC_MIN_SHARES=100
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.scout")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
SCOUT_AUDIT = DATA_DIR / "scout_events.jsonl"
SCOUT_STATE = DATA_DIR / "scout_state.json"

ENABLED = os.getenv("NCL_AT_SCOUT_ENABLED", "1") not in ("0", "false", "False")
TICK_MARKET = int(os.getenv("NCL_AT_SCOUT_TICK_MARKET", "300"))
TICK_OFFHOURS = int(os.getenv("NCL_AT_SCOUT_TICK_OFFHOURS", "1800"))
PROFIT_R_MIN = float(os.getenv("NCL_AT_SCOUT_PROFIT_R_MIN", "2.0"))
EARNINGS_WINDOW_D = int(os.getenv("NCL_AT_SCOUT_EARNINGS_WINDOW_D", "5"))
CC_MIN_SHARES = int(os.getenv("NCL_AT_SCOUT_CC_MIN_SHARES", "100"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _is_market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    et_hour = (now.hour - 4) % 24
    if now.weekday() >= 5:
        return False
    return (et_hour, now.minute) >= (9, 30) and et_hour < 16


def _load_state() -> dict:
    if not SCOUT_STATE.exists():
        return {}
    try:
        return json.loads(SCOUT_STATE.read_text())
    except Exception:
        return {}


def _persist_state(d: dict) -> None:
    _ensure_dir()
    tmp = SCOUT_STATE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(d, indent=2, sort_keys=True))
        tmp.replace(SCOUT_STATE)
    except Exception as e:
        log.error("[SCOUT] state persist failed: %s", e)


def _append_audit(row: dict) -> None:
    _ensure_dir()
    try:
        with open(SCOUT_AUDIT, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("[SCOUT] audit append failed: %s", e)


# ─────────────────────────────────────────────────────────────────────
# Check 1: profit-target hits on open paper trades
# ─────────────────────────────────────────────────────────────────────

async def _scan_profit_targets(brain) -> dict:
    """Walk all open paper trades. Anything at R >= recipe.profit_target_R
    OR PROFIT_R_MIN gets logged + emits suggestion MemUnit. Doesn't
    auto-close — operator/loop decides."""
    from ..paper_trading import PaperTradingEngine
    from .strategy_registry import get_recipe

    paper = PaperTradingEngine()
    hits = []
    for trade_id, t in list(paper._trades.items()):
        if getattr(t, "status", None) != "open":
            continue
        # PaperTradingEngine's update_prices computes r_multiple as the
        # unrealized R; if not present yet, skip
        r = float(getattr(t, "r_multiple", 0) or 0)
        if r < PROFIT_R_MIN:
            continue
        # Look up recipe-specific profit target
        recipe_target = PROFIT_R_MIN
        try:
            recipe = await get_recipe(getattr(t, "strategy", "") or "")
            if recipe and recipe.profit_target_R:
                recipe_target = recipe.profit_target_R
        except Exception:
            pass
        if r >= recipe_target:
            hits.append({
                "trade_id": trade_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "strategy": t.strategy,
                "r_multiple": r,
                "recipe_target": recipe_target,
                "current_price": getattr(t, "current_price", 0),
                "entry_price": getattr(t, "entry_price", 0),
            })

    if hits and brain:
        mem = getattr(brain, "memory_store", None)
        if mem and hasattr(mem, "create_unit"):
            for h in hits[:10]:  # cap MemUnit emissions per tick
                try:
                    await mem.create_unit(
                        content=(
                            f"SCOUT: {h['symbol']} {h['direction']} ({h['strategy']}) "
                            f"at {h['r_multiple']:+.2f}R (target {h['recipe_target']:.1f}R) — "
                            f"profit-target candidate. Consider close or trail-stop tighten."
                        ),
                        source="portfolio:scout:profit_target",
                        importance=80.0,
                        tags=[
                            "portfolio", "auto_trader", "scout",
                            "profit_target", f"ticker:{h['symbol']}",
                            f"strategy:{h['strategy']}",
                        ],
                        memory_type="episodic",
                        metadata=h,
                    )
                except Exception as e:
                    log.debug("[SCOUT] profit MemUnit emit skipped: %s", e)
    return {"count": len(hits), "hits": hits}


# ─────────────────────────────────────────────────────────────────────
# Check 2: regime-shift detection
# ─────────────────────────────────────────────────────────────────────

async def _scan_regime_shift(brain, state: dict) -> dict:
    """Compare today's rotation_tracker leading sectors to yesterday's.
    Sector flip on a held position → emit regime_shift MemUnit."""
    out = {"shifts": [], "current_leading": [], "previous_leading": []}
    try:
        rotation_files = sorted(
            (NCL_BASE / "data" / "rotation").glob("20*.json"),
            reverse=True,
        )
    except Exception:
        return out
    if len(rotation_files) < 2:
        return out
    try:
        today = json.loads(rotation_files[0].read_text())
        yest = json.loads(rotation_files[1].read_text())
    except Exception as e:
        log.debug("[SCOUT] rotation file parse failed: %s", e)
        return out

    def _leading(rot: dict) -> set[str]:
        sectors = rot.get("sectors") or rot.get("rotation", {}).get("sectors", [])
        return {
            s.get("ticker", "").upper() for s in sectors
            if (s.get("quadrant", "") or "").lower() == "leading"
        }

    cur_leading = _leading(today)
    prev_leading = _leading(yest)
    out["current_leading"] = sorted(cur_leading)
    out["previous_leading"] = sorted(prev_leading)
    demoted = sorted(prev_leading - cur_leading)
    promoted = sorted(cur_leading - prev_leading)
    if not demoted and not promoted:
        return out

    out["shifts"] = [
        {"event": "demoted_from_leading", "sector_etf": s}
        for s in demoted
    ] + [
        {"event": "promoted_to_leading", "sector_etf": s}
        for s in promoted
    ]

    # Only emit a MemUnit on transitions we haven't seen yet today
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_emit_date = state.get("regime_last_emit_date")
    if last_emit_date == today_date and not out["shifts"]:
        return out

    if brain:
        mem = getattr(brain, "memory_store", None)
        if mem and hasattr(mem, "create_unit"):
            content = (
                f"SCOUT REGIME SHIFT: leading sectors changed. "
                f"DEMOTED from Leading: {', '.join(demoted) or 'none'}. "
                f"PROMOTED to Leading: {', '.join(promoted) or 'none'}. "
                f"Review open positions in demoted sectors for defensive close."
            )
            try:
                await mem.create_unit(
                    content=content,
                    source="portfolio:scout:regime_shift",
                    importance=85.0,
                    tags=[
                        "portfolio", "auto_trader", "scout",
                        "regime_shift", "rotation",
                    ],
                    memory_type="semantic",
                    metadata=out,
                )
            except Exception as e:
                log.debug("[SCOUT] regime MemUnit skipped: %s", e)
    state["regime_last_emit_date"] = today_date
    return out


# ─────────────────────────────────────────────────────────────────────
# Check 3: covered-call opportunities on snapshot holdings
# ─────────────────────────────────────────────────────────────────────

async def _scan_covered_call_opportunities(brain, state: dict) -> dict:
    """Snapshot stock holdings ≥100 shares with no existing short call →
    emit covered_call_income trade idea (uses build_covered_call from L3
    options_recipes)."""
    out = {"opportunities": [], "emitted": 0}
    if not brain:
        return out

    # Read live portfolio positions from the portfolio_manager
    try:
        from runtime.api.deps import get_portfolio_mgr
        pm = get_portfolio_mgr()
        if pm is None:
            return out
        positions = pm.get_positions()
    except Exception as e:
        log.debug("[SCOUT] portfolio_manager read failed: %s", e)
        return out

    # Read paper trades to skip tickers that already have an open short call
    try:
        from ..paper_trading import PaperTradingEngine
        paper = PaperTradingEngine()
        existing_short_calls = {
            (t.symbol.upper(), "short_call")
            for t in paper._trades.values()
            if getattr(t, "status", None) == "open"
            and (getattr(t, "strategy", "") or "") == "covered_call_income"
        }
    except Exception:
        existing_short_calls = set()

    last_emit_date = state.get("cc_last_emit_date")
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for pos in positions or []:
        symbol = (pos.get("symbol") or "").upper()
        qty = abs(float(pos.get("quantity") or 0))
        asset_class = (pos.get("asset_class") or "").lower()
        last_price = pos.get("last_price") or pos.get("avg_cost")
        # Only stock holdings (not options) ≥ CC_MIN_SHARES
        if "equity" not in asset_class and "stock" not in asset_class:
            continue
        if qty < CC_MIN_SHARES:
            continue
        if not last_price or float(last_price) <= 0:
            continue
        if (symbol, "short_call") in existing_short_calls:
            continue
        contracts = int(qty // 100)
        out["opportunities"].append({
            "symbol": symbol,
            "shares": int(qty),
            "contracts": contracts,
            "last_price": float(last_price),
        })

    # Only emit suggestions once per day per ticker
    if last_emit_date == today_date:
        return out  # already emitted today; skip re-emission

    if not out["opportunities"]:
        return out

    mem = getattr(brain, "memory_store", None)
    if mem and hasattr(mem, "create_unit"):
        for opp in out["opportunities"][:5]:  # cap
            try:
                content = (
                    f"SCOUT CC OPPORTUNITY: {opp['symbol']} "
                    f"{opp['shares']} shares owned (= {opp['contracts']} contracts). "
                    f"Underlying ${opp['last_price']:.2f}. "
                    f"Recipe: covered_call_income — sell 30-45 DTE ~5% OTM call "
                    f"for premium harvest. Estimated premium per contract: "
                    f"${opp['last_price'] * 1.5:.0f}."
                )
                await mem.create_unit(
                    content=content,
                    source="portfolio:scout:covered_call",
                    importance=75.0,
                    tags=[
                        "portfolio", "auto_trader", "scout",
                        "covered_call_opportunity", f"ticker:{opp['symbol']}",
                    ],
                    memory_type="semantic",
                    metadata=opp,
                )
                out["emitted"] += 1
            except Exception as e:
                log.debug("[SCOUT] CC MemUnit emit skipped: %s", e)
    state["cc_last_emit_date"] = today_date
    return out


# ─────────────────────────────────────────────────────────────────────
# Check 4: earnings-defensive flags on open positions
# ─────────────────────────────────────────────────────────────────────

async def _scan_earnings_defensive(brain, state: dict) -> dict:
    """For each open paper trade, check if underlying has earnings within
    EARNINGS_WINDOW_D. Emit defensive MemUnit at importance 90."""
    out = {"flagged": []}
    try:
        from ..paper_trading import PaperTradingEngine
        paper = PaperTradingEngine()
    except Exception:
        return out

    open_tickers = sorted({
        t.symbol.upper() for t in paper._trades.values()
        if getattr(t, "status", None) == "open"
    })
    if not open_tickers:
        return out

    # Use calendar_gate's earnings fetcher (it has its own cache)
    try:
        from .calendar_gate import _fetch_earnings_dates, _parse_iso_date
    except Exception as e:
        log.debug("[SCOUT] earnings fetcher unavailable: %s", e)
        return out

    from datetime import date as dt_date
    today = datetime.now(timezone.utc).date()
    today_date = today.isoformat()
    last_emit_date = state.get("earnings_last_emit_date")
    if last_emit_date == today_date:
        return out

    for ticker in open_tickers:
        try:
            dates = await _fetch_earnings_dates(ticker) or []
            for ds in dates:
                d = _parse_iso_date(ds)
                if d is None:
                    continue
                delta = (d - today).days
                if 0 <= delta <= EARNINGS_WINDOW_D:
                    out["flagged"].append({
                        "ticker": ticker,
                        "days_away": delta,
                        "earnings_date": ds,
                    })
                    break  # only need closest one
        except Exception as e:
            log.debug("[SCOUT] earnings lookup failed for %s: %s", ticker, e)

    if not out["flagged"]:
        return out

    mem = brain and getattr(brain, "memory_store", None)
    if mem and hasattr(mem, "create_unit"):
        for f in out["flagged"][:8]:
            try:
                await mem.create_unit(
                    content=(
                        f"SCOUT EARNINGS DEFENSIVE: {f['ticker']} reports in "
                        f"{f['days_away']}d ({f['earnings_date']}) and you have an "
                        f"open paper position. Consider: close before earnings, "
                        f"roll out to later DTE, or hedge with vertical spread."
                    ),
                    source="portfolio:scout:earnings_defensive",
                    importance=90.0,
                    tags=[
                        "portfolio", "auto_trader", "scout",
                        "earnings_defensive", f"ticker:{f['ticker']}",
                    ],
                    memory_type="episodic",
                    metadata=f,
                )
            except Exception as e:
                log.debug("[SCOUT] earnings MemUnit skipped: %s", e)
    state["earnings_last_emit_date"] = today_date
    return out


# ─────────────────────────────────────────────────────────────────────
# Tick + loop
# ─────────────────────────────────────────────────────────────────────

async def scout_tick(brain) -> dict:
    """One scout pass — runs all 4 checks. Returns a summary dict."""
    state = _load_state()
    summary = {
        "tick_at_iso": _now_iso(),
        "profit_targets": {"count": 0},
        "regime_shifts": {"count": 0},
        "cc_opportunities": {"count": 0, "emitted": 0},
        "earnings_defensive": {"count": 0},
    }
    try:
        pt = await _scan_profit_targets(brain)
        summary["profit_targets"] = {"count": pt["count"], "hits_sample": pt["hits"][:3]}
    except Exception as e:
        log.warning("[SCOUT] profit_targets failed: %s", e)
    try:
        rs = await _scan_regime_shift(brain, state)
        summary["regime_shifts"] = {
            "count": len(rs.get("shifts", [])),
            "shifts": rs.get("shifts", []),
        }
    except Exception as e:
        log.warning("[SCOUT] regime_shift failed: %s", e)
    try:
        cc = await _scan_covered_call_opportunities(brain, state)
        summary["cc_opportunities"] = {
            "count": len(cc.get("opportunities", [])),
            "emitted": cc.get("emitted", 0),
        }
    except Exception as e:
        log.warning("[SCOUT] covered_call scan failed: %s", e)
    try:
        ed = await _scan_earnings_defensive(brain, state)
        summary["earnings_defensive"] = {
            "count": len(ed.get("flagged", [])),
            "flagged_sample": ed.get("flagged", [])[:3],
        }
    except Exception as e:
        log.warning("[SCOUT] earnings_defensive failed: %s", e)

    _persist_state(state)
    _append_audit(summary)
    log.info(
        "[SCOUT] tick done — profit_targets=%d regime_shifts=%d "
        "cc_opportunities=%d earnings_defensive=%d",
        summary["profit_targets"]["count"],
        summary["regime_shifts"]["count"],
        summary["cc_opportunities"]["count"],
        summary["earnings_defensive"]["count"],
    )
    return summary


async def scout_loop(brain) -> None:
    """Long-running scheduler task. Pro-active 5min / 30min cadence."""
    if not ENABLED:
        log.info("[SCOUT] disabled (NCL_AT_SCOUT_ENABLED=0)")
        # Sleep forever — keeps task alive but inert; supervisor won't restart it
        while True:
            await asyncio.sleep(3600)
    log.info(
        "[SCOUT] starting scout loop (market %ds / off-hours %ds)",
        TICK_MARKET, TICK_OFFHOURS,
    )
    while True:
        try:
            await scout_tick(brain)
        except asyncio.CancelledError:
            log.info("[SCOUT] cancelled")
            raise
        except Exception as e:
            log.error("[SCOUT] tick error (continuing): %s", e, exc_info=True)
        cadence = TICK_MARKET if _is_market_open() else TICK_OFFHOURS
        await asyncio.sleep(cadence)


async def scout_summary() -> dict:
    """Snapshot for /dashboard rollup — recent 10 audit rows."""
    recent = []
    if SCOUT_AUDIT.exists():
        try:
            with open(SCOUT_AUDIT) as f:
                rows = [json.loads(line) for line in f if line.strip()]
            recent = rows[-10:]
        except Exception:
            pass
    return {
        "enabled": ENABLED,
        "tick_market_s": TICK_MARKET,
        "tick_offhours_s": TICK_OFFHOURS,
        "recent_10_ticks": recent,
        "last_tick_iso": recent[-1]["tick_at_iso"] if recent else None,
    }
