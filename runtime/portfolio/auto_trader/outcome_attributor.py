"""
Auto-Trader outcome attributor — Wave 14K Phase 3 (K2b + K2c)

When PaperTradingEngine.update_prices() returns triggered events
(stop_hit / target_hit / trailing_stop / time_exit), this module:

  1. Looks up the closed paper trade
  2. Reads paper_trade.scanner_data.trade_idea_id (set at open
     time by loop._idea_to_paper_payload — K1b)
  3. Calls trade_idea_tracker.update_outcome() so per-strategy
     expectancy stats refresh
  4. Emits portfolio:paper_trade_closed MemUnit at importance 80
     (K2c)
  5. Reconciles R_multiple between the two engines (paper_trade.r_multiple
     vs tracker-computed); logs DRIFT warning if they disagree > 1¢

Trigger → outcome mapping (matches paper_trading.status_map):
  stop_hit       → "stopped_out"
  target_hit     → "target_hit"
  trailing_stop  → "manually_closed"   # trail = locked-in profit, treat as close
  time_exit      → "expired"
  manual         → "manually_closed"   # operator-initiated close
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.outcome_attributor")


# Trigger names returned by PaperTradingEngine.update_prices() →
# trade_idea_tracker outcome enum values
TRIGGER_TO_OUTCOME = {
    "stop_hit": "stopped_out",
    "target_hit": "target_hit",
    "trailing_stop": "manually_closed",  # profit trail = considered closed
    "time_exit": "expired",
    "manual": "manually_closed",
}


def trigger_to_outcome(trigger: str) -> str:
    """Translate paper-trading trigger string to trade_idea_tracker
    outcome enum. Unknown triggers default to 'manually_closed'."""
    return TRIGGER_TO_OUTCOME.get((trigger or "").lower(), "manually_closed")


def extract_trade_idea_id(paper_trade) -> Optional[str]:
    """Extract trade_idea_id from paper_trade.scanner_data (set at
    open time by loop._idea_to_paper_payload)."""
    if paper_trade is None:
        return None
    scanner_data = getattr(paper_trade, "scanner_data", None) or {}
    if isinstance(scanner_data, dict):
        tid = scanner_data.get("trade_idea_id")
        return str(tid) if tid else None
    return None


async def attribute_close(
    *,
    brain,
    paper_engine,
    triggered_event: dict,
) -> dict:
    """Process one triggered event from PaperTradingEngine.update_prices().

    Returns a dict describing what was done:
      {
        ok: bool,
        trade_id: str,
        trade_idea_id: str | None,
        outcome: str,                  # mapped tracker enum
        exit_price: float,
        engine_R_multiple: float,
        tracker_R_multiple: float | None,
        r_drift_warning: str | None,
        memory_unit_emitted: bool,
        reason: str
      }
    """
    trade_id = triggered_event.get("trade_id")
    trigger = triggered_event.get("trigger")
    exit_price = float(triggered_event.get("price") or 0)
    engine_r = float(triggered_event.get("r_multiple") or 0)

    result = {
        "ok": False,
        "trade_id": trade_id,
        "trade_idea_id": None,
        "outcome": trigger_to_outcome(trigger or ""),
        "exit_price": exit_price,
        "engine_R_multiple": engine_r,
        "tracker_R_multiple": None,
        "r_drift_warning": None,
        "memory_unit_emitted": False,
        "reason": "",
    }

    # 1) Load the paper trade
    paper_trade = paper_engine._trades.get(trade_id) if hasattr(paper_engine, "_trades") else None
    if paper_trade is None:
        result["reason"] = f"trade {trade_id} not found"
        log.warning("[AT-ATTR] %s", result["reason"])
        return result

    # 2) Extract trade_idea_id
    trade_idea_id = extract_trade_idea_id(paper_trade)
    result["trade_idea_id"] = trade_idea_id
    if not trade_idea_id:
        result["reason"] = (
            f"no trade_idea_id in scanner_data for {trade_id} — "
            "manual / pre-auto-trader trade, skipping attribution"
        )
        log.info("[AT-ATTR] %s", result["reason"])
        # Still emit the memory unit so we have a record
        await _emit_close_memory_unit(
            brain, paper_trade=paper_trade,
            outcome=result["outcome"], engine_r=engine_r,
            trade_idea_id=None,
        )
        result["memory_unit_emitted"] = True
        result["ok"] = True
        return result

    # 3) Call trade_idea_tracker.update_outcome()
    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        notes = (
            f"auto-attributed: paper_trade={trade_id} trigger={trigger} "
            f"engine_R={engine_r}"
        )
        outcome_result = await tracker.update_outcome(
            trade_idea_id,
            outcome=result["outcome"],
            exit_price=exit_price,
            notes=notes,
        )
        if outcome_result and outcome_result.get("R_multiple") is not None:
            tracker_r = float(outcome_result["R_multiple"])
            result["tracker_R_multiple"] = tracker_r
            # Reconcile within 1c tolerance
            if abs(tracker_r - engine_r) > 0.01:
                drift_msg = (
                    f"OUTCOME-DRIFT {trade_idea_id}: engine_R={engine_r} "
                    f"!= tracker_R={tracker_r:.2f} (diff={tracker_r - engine_r:+.4f})"
                )
                result["r_drift_warning"] = drift_msg
                log.warning("[AT-ATTR] %s", drift_msg)
    except Exception as e:
        result["reason"] = f"tracker.update_outcome failed: {e}"
        log.error("[AT-ATTR] %s", result["reason"], exc_info=True)
        # Still try the memory unit
        await _emit_close_memory_unit(
            brain, paper_trade=paper_trade,
            outcome=result["outcome"], engine_r=engine_r,
            trade_idea_id=trade_idea_id,
        )
        result["memory_unit_emitted"] = True
        return result

    # 4) Emit memory unit
    await _emit_close_memory_unit(
        brain, paper_trade=paper_trade,
        outcome=result["outcome"], engine_r=engine_r,
        trade_idea_id=trade_idea_id,
    )
    result["memory_unit_emitted"] = True

    result["ok"] = True
    result["reason"] = "attributed + memory + tracker updated"
    log.info(
        "[AT-ATTR] CLOSED %s (paper_trade_id=%s) outcome=%s exit_price=$%.2f "
        "R=%.2f",
        trade_idea_id, trade_id, result["outcome"], exit_price, engine_r,
    )
    return result


async def _emit_close_memory_unit(
    brain,
    *,
    paper_trade,
    outcome: str,
    engine_r: float,
    trade_idea_id: Optional[str],
) -> None:
    """K2c: emit portfolio:paper_trade_closed at importance 80.
    Fire-and-forget. Never raises."""
    mem = getattr(brain, "memory_store", None)
    if mem is None or not hasattr(mem, "create_unit"):
        return
    try:
        symbol = getattr(paper_trade, "symbol", "?")
        direction = getattr(paper_trade, "direction", "?")
        entry_price = getattr(paper_trade, "entry_price", 0)
        exit_price = getattr(paper_trade, "current_price", 0)
        qty = getattr(paper_trade, "quantity", 0)
        strategy = getattr(paper_trade, "strategy", "auto")
        realized_pl = getattr(paper_trade, "realized_pl", 0)
        days_held = getattr(paper_trade, "days_held", 0)
        outcome_emoji = {
            "target_hit": "🎯",
            "stopped_out": "🛑",
            "expired": "⏰",
            "manually_closed": "✋",
        }.get(outcome, "📊")
        content = (
            f"Auto-trader CLOSED paper position: {symbol} {direction} qty={qty}. "
            f"Entry ${entry_price} → exit ${exit_price} ({outcome}). "
            f"R_multiple={engine_r:+.2f}, P&L=${realized_pl:+.2f}, "
            f"days_held={days_held}. strategy={strategy} "
            f"trade_idea_id={trade_idea_id or 'manual'}"
        )
        await mem.create_unit(
            content=content,
            source="portfolio:paper_trade_closed",
            importance=80.0,
            tags=[
                "portfolio", "auto_trader", "paper_close",
                f"strategy:{strategy}", f"ticker:{symbol}",
                f"outcome:{outcome}",
                "win" if engine_r > 0 else "loss" if engine_r < 0 else "scratch",
            ],
            memory_type="episodic",
            metadata={
                "trade_idea_id": trade_idea_id,
                "paper_trade_id": getattr(paper_trade, "id", None),
                "symbol": symbol,
                "strategy": strategy,
                "outcome": outcome,
                "R_multiple": engine_r,
                "realized_pl": realized_pl,
                "days_held": days_held,
                "wave": "14K-K2c",
            },
        )
        log.debug("[AT-ATTR] emoji=%s mem unit emitted for %s", outcome_emoji, symbol)
    except Exception as e:
        log.warning("[AT-ATTR] memory unit emit failed (non-fatal): %s", e)


async def attribute_batch(
    *,
    brain,
    paper_engine,
    triggered_events: list,
) -> list[dict]:
    """Process a batch of triggered events; returns one result per event."""
    out = []
    for evt in triggered_events:
        try:
            r = await attribute_close(
                brain=brain, paper_engine=paper_engine, triggered_event=evt,
            )
            out.append(r)
        except Exception as e:
            log.error("[AT-ATTR] batch error on %s: %s", evt.get("trade_id"), e)
            out.append({"ok": False, "trade_id": evt.get("trade_id"),
                       "reason": f"unexpected: {e}"})
    return out
