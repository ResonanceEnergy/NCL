"""
Auto-Trader profit ladder — Wave 14L L4

Meta-strategy: when a SHORT-DATED LOTTERY paper trade closes with
R_multiple ≥ NCL_AT_LADDER_R_THRESHOLD (default +2R = 200% return on
premium), automatically emit a follow-on LONG-DATED LEAPS trade idea
on the SAME underlying that scales NCL_AT_LADDER_PROFIT_RATIO of the
realized profit into a 6-12 month position.

This is the NATRIX-specific "aggressive growing with short dated
options then converting those wins in to long dated options and trade
up on swings" pattern, encoded as code.

Flow:
  1. outcome_attributor.attribute_close fires on stop/target/manual
  2. After bandit + SHAP + drift + friction updates, profit_ladder
     checks: "was this a short-dated lottery? did it win big?"
  3. If yes, emit a new TradeIdea via trade_idea_tracker:
       - source = "profit_ladder"
       - strategy = best long-dated swing recipe from registry
       - ticker = same underlying as closed trade
       - direction = same as closed trade
       - effective_R_dollars = realized_profit * NCL_AT_LADDER_PROFIT_RATIO
       - DTE = randint(LADDER_DTE_MIN..LADDER_DTE_MAX) target
  4. The new idea flows through the normal auto-trader loop (governor,
     calendar, working_context, policy, friction, council quorum if R≥$1k,
     paper open).
  5. Audit JSONL + MemUnit at importance 85.

Idempotent on the source trade_idea_id — same close can't ladder twice.

Storage:
  data/portfolio/auto_trader/ladder_emissions.jsonl  (audit)
  data/portfolio/auto_trader/ladder_state.json       (already-laddered set)

Tunables (env):
  NCL_AT_LADDER_ENABLED=1            (master kill)
  NCL_AT_LADDER_R_THRESHOLD=2.0      (R-multiple gate for ladder trigger)
  NCL_AT_LADDER_PROFIT_RATIO=0.50    (fraction of realized profit to roll)
  NCL_AT_LADDER_MIN_PROFIT_USD=50    (min $ to bother laddering)
  NCL_AT_LADDER_DTE_MIN=120          (LEAP DTE lower bound)
  NCL_AT_LADDER_DTE_MAX=365          (LEAP DTE upper bound)
  NCL_AT_LADDER_DESTINATION=leaps_long_dated  (default destination recipe)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.profit_ladder")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
LADDER_AUDIT = DATA_DIR / "ladder_emissions.jsonl"
LADDER_STATE = DATA_DIR / "ladder_state.json"

ENABLED = os.getenv("NCL_AT_LADDER_ENABLED", "1") not in ("0", "false", "False")
R_THRESHOLD = float(os.getenv("NCL_AT_LADDER_R_THRESHOLD", "2.0"))
PROFIT_RATIO = float(os.getenv("NCL_AT_LADDER_PROFIT_RATIO", "0.50"))
MIN_PROFIT_USD = float(os.getenv("NCL_AT_LADDER_MIN_PROFIT_USD", "50"))
DTE_MIN = int(os.getenv("NCL_AT_LADDER_DTE_MIN", "120"))
DTE_MAX = int(os.getenv("NCL_AT_LADDER_DTE_MAX", "365"))
DESTINATION_RECIPE = os.getenv("NCL_AT_LADDER_DESTINATION", "leaps_long_dated")

_LOCK = asyncio.Lock()
_LADDERED: set[str] = set()
_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not LADDER_STATE.exists():
        return
    try:
        raw = json.loads(LADDER_STATE.read_text())
        if isinstance(raw, dict):
            for tid in (raw.get("laddered_ids") or []):
                _LADDERED.add(str(tid))
    except Exception as e:
        log.warning("[LADDER] state load failed: %s", e)


def _persist_state() -> None:
    _ensure_dir()
    tmp = LADDER_STATE.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps({"laddered_ids": sorted(_LADDERED)}, indent=2, sort_keys=True)
        )
        tmp.replace(LADDER_STATE)
    except Exception as e:
        log.error("[LADDER] state persist failed: %s", e)


def _append_audit(row: dict) -> None:
    _ensure_dir()
    try:
        with open(LADDER_AUDIT, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("[LADDER] audit append failed: %s", e)


async def maybe_ladder_from_close(
    *,
    brain,
    paper_trade,
    closed_idea: dict,
    engine_r: float,
    exit_price: float,
) -> Optional[dict]:
    """Check if a close should trigger a profit-ladder emission.

    Returns a dict describing the emission (or skip reason). Never raises."""
    if not ENABLED:
        return {"emitted": False, "reason": "ladder disabled"}

    tid = closed_idea.get("trade_idea_id")
    if not tid:
        return {"emitted": False, "reason": "no trade_idea_id"}

    async with _LOCK:
        _load_state()
        if tid in _LADDERED:
            return {"emitted": False, "reason": "already laddered"}

    # Gate 1: R-multiple threshold
    if engine_r < R_THRESHOLD:
        return {
            "emitted": False,
            "reason": f"R={engine_r:.2f} < threshold {R_THRESHOLD:.2f}",
        }

    # Gate 2: source recipe must be a short-dated lottery
    from .strategy_registry import (
        get_recipe, list_short_dated_lottery_recipes,
    )
    source_strategy = (closed_idea.get("strategy") or "").lower()
    short_dated = await list_short_dated_lottery_recipes()
    if source_strategy not in short_dated:
        return {
            "emitted": False,
            "reason": (
                f"source strategy '{source_strategy}' not in lottery set "
                f"{short_dated}"
            ),
        }

    # Gate 3: compute realized profit + ladder dollars
    entry_price = float(closed_idea.get("entry_price") or 0)
    qty = float(getattr(paper_trade, "quantity", 0) or 0)
    direction = (closed_idea.get("direction") or "long").lower()
    if direction == "short":
        realized_profit = (entry_price - exit_price) * qty
    else:
        realized_profit = (exit_price - entry_price) * qty
    if realized_profit < MIN_PROFIT_USD:
        return {
            "emitted": False,
            "reason": (
                f"realized profit ${realized_profit:.2f} < "
                f"min ${MIN_PROFIT_USD:.2f}"
            ),
        }
    ladder_R = round(realized_profit * PROFIT_RATIO, 2)

    # Gate 4: destination recipe exists + is enabled
    dest_recipe = await get_recipe(DESTINATION_RECIPE)
    if dest_recipe is None or not dest_recipe.enabled:
        return {
            "emitted": False,
            "reason": (
                f"destination recipe '{DESTINATION_RECIPE}' unknown or disabled"
            ),
        }

    # Construct new trade idea — emit via trade_idea_tracker so the
    # auto-trader loop picks it up on the next tick. R_per_share is
    # ladder_R since we want effective_R_dollars to be exactly the
    # ladder profit fraction.
    ticker = closed_idea.get("ticker")
    underlying_price = exit_price  # rough proxy
    # For LEAPS, R_per_share is the LEAP's premium-at-risk per contract
    # × 100. We can't know the real premium without an options chain
    # lookup; use a conservative estimate: 5% of underlying for ITM
    # LEAP, scaled by direction (long calls = atm-ish).
    est_premium_per_share = underlying_price * 0.05
    est_R_per_share = max(0.01, est_premium_per_share)  # full premium at risk

    thesis = (
        f"PROFIT LADDER from {tid[:8]}: short-dated {source_strategy} "
        f"closed {direction} {ticker} for {engine_r:+.2f}R (${realized_profit:.0f} "
        f"realized). Rolling {PROFIT_RATIO:.0%} (${ladder_R:.0f}) into a "
        f"{DTE_MIN}-{DTE_MAX} DTE LEAP on the same underlying."
    )

    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        new_idea = await tracker.record_emission(
            source="profit_ladder",
            strategy=DESTINATION_RECIPE,
            ticker=ticker,
            direction=direction,
            entry_price=underlying_price,  # underlying price; actual entry
                                            # will be the LEAP premium at fill
            stop_price=round(
                underlying_price * (0.85 if direction == "long" else 1.15),
                2,
            ),
            target_price=round(
                underlying_price * (1.30 if direction == "long" else 0.70),
                2,
            ),
            R_per_share=est_R_per_share,
            planned_qty=max(1, int(ladder_R / est_R_per_share)),
            stop_type="thesis_break",
            stop_basis=(
                "thesis break: LEAP loses >40% of premium OR underlying "
                "violates pre-ladder swing structure"
            ),
            target_basis=(
                f"30% underlying move within {DTE_MIN}-{DTE_MAX} DTE"
            ),
            thesis=thesis,
            metadata={
                "profit_ladder": True,
                "source_trade_idea_id": tid,
                "source_strategy": source_strategy,
                "realized_profit_usd": round(realized_profit, 2),
                "ladder_profit_ratio": PROFIT_RATIO,
                "ladder_R_dollars": ladder_R,
                "target_dte_min": DTE_MIN,
                "target_dte_max": DTE_MAX,
                "destination_recipe": DESTINATION_RECIPE,
                "wave": "14L-L4",
            },
        )
    except Exception as e:
        log.error("[LADDER] record_emission failed for %s: %s", ticker, e)
        return {"emitted": False, "reason": f"emission exception: {e}"}

    new_tid = new_idea.get("trade_idea_id")
    async with _LOCK:
        _LADDERED.add(tid)
        _persist_state()

    audit_row = {
        "ts": _now_iso(),
        "source_trade_idea_id": tid,
        "source_strategy": source_strategy,
        "ticker": ticker,
        "direction": direction,
        "engine_r": engine_r,
        "realized_profit_usd": round(realized_profit, 2),
        "ladder_profit_ratio": PROFIT_RATIO,
        "ladder_R_dollars": ladder_R,
        "new_trade_idea_id": new_tid,
        "destination_recipe": DESTINATION_RECIPE,
        "target_dte_min": DTE_MIN,
        "target_dte_max": DTE_MAX,
    }
    _append_audit(audit_row)

    # MemUnit at importance 85 so the morning brief sees the ladder event
    try:
        mem = getattr(brain, "memory_store", None)
        if mem and hasattr(mem, "create_unit"):
            content = (
                f"PROFIT LADDER fired: {ticker} {direction} {source_strategy} "
                f"closed {engine_r:+.2f}R (${realized_profit:.0f}). "
                f"Rolled {PROFIT_RATIO:.0%} into new {DESTINATION_RECIPE} "
                f"trade idea {new_tid} (ladder_R=${ladder_R:.0f}, "
                f"{DTE_MIN}-{DTE_MAX} DTE target)."
            )
            await mem.create_unit(
                content=content,
                source="portfolio:profit_ladder",
                importance=85.0,
                tags=[
                    "portfolio", "auto_trader", "profit_ladder",
                    f"ticker:{ticker}", f"strategy:{source_strategy}",
                    f"destination:{DESTINATION_RECIPE}",
                ],
                memory_type="episodic",
                metadata=audit_row,
            )
    except Exception as e:
        log.debug("[LADDER] memory unit emission skipped: %s", e)

    log.info(
        "[LADDER] LADDERED %s: %s %s %+.2fR (${%.0f}) → new idea %s "
        "(${%.0f} R, %d-%d DTE)",
        tid, ticker, direction, engine_r, realized_profit,
        new_tid, ladder_R, DTE_MIN, DTE_MAX,
    )
    return {
        "emitted": True,
        "source_trade_idea_id": tid,
        "new_trade_idea_id": new_tid,
        "ladder_R_dollars": ladder_R,
        "realized_profit_usd": round(realized_profit, 2),
    }


async def ladder_summary() -> dict:
    """Snapshot for /dashboard rollup."""
    async with _LOCK:
        _load_state()
        laddered_count = len(_LADDERED)
    # Tail the audit JSONL for the most recent 10 emissions
    recent = []
    if LADDER_AUDIT.exists():
        try:
            with open(LADDER_AUDIT) as f:
                rows = [json.loads(line) for line in f if line.strip()]
            recent = rows[-10:]
        except Exception:
            pass
    total_realized = sum(r.get("realized_profit_usd") or 0 for r in recent)
    total_laddered = sum(r.get("ladder_R_dollars") or 0 for r in recent)
    return {
        "enabled": ENABLED,
        "r_threshold": R_THRESHOLD,
        "profit_ratio": PROFIT_RATIO,
        "min_profit_usd": MIN_PROFIT_USD,
        "dte_min": DTE_MIN,
        "dte_max": DTE_MAX,
        "destination_recipe": DESTINATION_RECIPE,
        "total_laddered_ever": laddered_count,
        "recent_10_emissions": recent,
        "recent_total_realized_usd": round(total_realized, 2),
        "recent_total_laddered_usd": round(total_laddered, 2),
    }
