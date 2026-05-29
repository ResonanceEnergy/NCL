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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    # 5) Wave 14K Phase 4 K3a: feed the strategy bandit
    try:
        from .strategy_bandit import get_bandit
        bandit = await get_bandit()
        strategy = getattr(paper_trade, "strategy", None) or "unknown"
        win = engine_r > 0
        await bandit.record_result(
            strategy=str(strategy),
            win=win,
            R_multiple=engine_r,
            trade_idea_id=trade_idea_id,
        )
    except Exception as e:
        log.warning("[AT-ATTR] bandit update skipped (non-fatal): %s", e)

    # 6) Wave 14K Phase 4 K3d: trigger SHAP attribution every N closes
    try:
        from .shap_attribution import maybe_run_attribution
        strategy = str(getattr(paper_trade, "strategy", None) or "unknown")
        # Use bandit's count as authoritative — same number we just bumped
        from .strategy_bandit import get_bandit
        bandit = await get_bandit()
        p = await bandit.posterior(strategy)
        n_closed = (p or {}).get("n_observed", 0)
        if n_closed > 0:
            await maybe_run_attribution(
                brain=brain, strategy=strategy, closed_trades_count=n_closed,
            )
    except Exception as e:
        log.warning("[AT-ATTR] SHAP trigger skipped (non-fatal): %s", e)

    # 7) Wave 14K Phase 6 K5a + K5b: feed drift detector + auto-pause
    #    on DRIFT_DOWN transition. Non-blocking — never breaks the close.
    try:
        from .drift_detector import update as drift_update, maybe_auto_pause
        strategy = str(getattr(paper_trade, "strategy", None) or "unknown")
        drift_result = await drift_update(strategy, win=engine_r > 0)
        result["drift_status"] = drift_result.get("status")
        result["drift_transition"] = drift_result.get("transition")
        if drift_result.get("status") == "DRIFT_DOWN":
            pause_result = await maybe_auto_pause(strategy, drift_result)
            result["auto_paused"] = pause_result.get("paused", False)
            if pause_result.get("paused"):
                # Emit a high-importance memory unit so the morning brief
                # sees the drift event in tomorrow's context packet.
                await _emit_drift_memory_unit(
                    brain, strategy=strategy, drift_result=drift_result,
                    pause_reason=pause_result.get("reason", ""),
                )
    except Exception as e:
        log.warning("[AT-ATTR] drift detector skipped (non-fatal): %s", e)

    # 7.5) Gap-close B — write a Prediction record per close so accuracy
    #      shows in the /predictions tab. Maps R_multiple to outcome:
    #        > 0 → "correct"   (target hit / favorable manual close)
    #        ≤ 0 → "incorrect" (stopped out / expired / unfavorable)
    #      Idempotent on trade_idea_id (filename suffix).
    #      Non-blocking on failure.
    try:
        await _emit_close_prediction_record(
            paper_trade=paper_trade,
            trade_idea_id=trade_idea_id,
            outcome=result["outcome"],
            engine_r=engine_r,
            exit_price=exit_price,
        )
        result["prediction_emitted"] = True
    except Exception as e:
        log.warning("[AT-ATTR] prediction record write skipped: %s", e)

    # 7.55) Wave 14L M1 — record realized loss into WashSaleLedger so the
    #       next open on this ticker triggers the 30-day wash check.
    try:
        if engine_r < 0:
            from .tax_sizing import record_realized_loss
            realized_pl = getattr(paper_trade, "realized_pl", 0) or 0
            loss_amount = abs(float(realized_pl)) if realized_pl < 0 else 0
            if loss_amount > 0:
                await record_realized_loss(
                    symbol=getattr(paper_trade, "symbol", "?"),
                    broker="paper",
                    account_id="auto_trader",
                    loss_amount=loss_amount,
                    notes=(
                        f"auto-trader paper close: trade_idea_id={trade_idea_id} "
                        f"trigger={result['outcome']} engine_R={engine_r:+.2f}"
                    ),
                )
    except Exception as e:
        log.warning("[AT-ATTR] wash sale record skipped: %s", e)

    # 7.6) Wave 14L L4 — Profit Ladder: if this was a short-dated lottery
    #      win, emit a follow-on long-dated LEAP trade idea at 50% of
    #      realized profit. Idempotent on source trade_idea_id.
    try:
        from .profit_ladder import maybe_ladder_from_close
        ladder_result = await maybe_ladder_from_close(
            brain=brain,
            paper_trade=paper_trade,
            closed_idea={
                "trade_idea_id": trade_idea_id,
                "strategy": getattr(paper_trade, "strategy", None),
                "ticker": getattr(paper_trade, "symbol", None),
                "direction": getattr(paper_trade, "direction", None),
                "entry_price": getattr(paper_trade, "entry_price", None),
            },
            engine_r=engine_r,
            exit_price=exit_price,
        )
        if ladder_result and ladder_result.get("emitted"):
            result["ladder_emitted"] = True
            result["ladder_new_trade_idea_id"] = ladder_result.get("new_trade_idea_id")
            result["ladder_R_dollars"] = ladder_result.get("ladder_R_dollars")
    except Exception as e:
        log.warning("[AT-ATTR] profit ladder skipped (non-fatal): %s", e)

    # 7.7) Wave 14U-2/4 — Post-trade factor attribution. Decompose
    #      every close into alpha/beta/factor/noise so we can tell which
    #      strategies have real edge vs which are just long-the-market.
    #      Non-blocking — failure never breaks the close path.
    try:
        from .factor_attribution import attribute_closed_trade
        strategy = str(getattr(paper_trade, "strategy", None) or "unknown")
        entry_price = float(getattr(paper_trade, "entry_price", 0) or 0)
        direction = str(getattr(paper_trade, "direction", "long"))
        # Timestamps
        opened_at = str(getattr(paper_trade, "opened_at", "") or "") or _now_iso()
        closed_at = str(getattr(paper_trade, "closed_at", "") or "") or _now_iso()
        fa_res = await attribute_closed_trade(
            strategy=strategy,
            ticker=str(getattr(paper_trade, "symbol", "?") or "?"),
            entry_price=entry_price,
            exit_price=exit_price,
            direction=direction,
            entry_iso=opened_at,
            exit_iso=closed_at,
            trade_idea_id=trade_idea_id,
        )
        if fa_res and fa_res.get("current_fit"):
            result["factor_alpha"] = fa_res["current_fit"].get("alpha")
            result["factor_beta_spy"] = fa_res["current_fit"].get("beta_spy")
    except Exception as e:
        log.warning("[AT-ATTR] factor attribution skipped (non-fatal): %s", e)

    # 8) Wave 14K Phase 7 K6b: re-calibrate friction profile every N closes.
    #    Non-blocking — friction failures never break the close path.
    try:
        from .friction_profile import maybe_calibrate
        from .strategy_bandit import get_bandit
        strategy = str(getattr(paper_trade, "strategy", None) or "unknown")
        bandit = await get_bandit()
        p = await bandit.posterior(strategy)
        n_closed = (p or {}).get("n_observed", 0)
        calib = await maybe_calibrate(strategy, n_closed=n_closed)
        if calib:
            result["friction_recalibrated"] = True
            result["new_slippage_bps"] = calib.get("new_slippage_bps")
    except Exception as e:
        log.warning("[AT-ATTR] friction calibration skipped (non-fatal): %s", e)

    result["ok"] = True
    result["reason"] = "attributed + memory + tracker + bandit updated"
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


async def _emit_drift_memory_unit(
    brain,
    *,
    strategy: str,
    drift_result: dict,
    pause_reason: str,
) -> None:
    """K5b: emit portfolio:strategy_drift at importance 90 so the next
    morning brief sees the regime shift in its context packet. Fire-and-
    forget. Never raises."""
    mem = getattr(brain, "memory_store", None)
    if mem is None or not hasattr(mem, "create_unit"):
        return
    try:
        content = (
            f"STRATEGY-DRIFT [{strategy}] DRIFT_DOWN detected. "
            f"running_mean={drift_result['running_mean']:.2%}, "
            f"recent_hit_rate={drift_result['recent_hit_rate']:.2%}, "
            f"n_observed={drift_result['n']}. "
            f"Auto-trader paused. {pause_reason}"
        )
        await mem.create_unit(
            content=content,
            source="portfolio:strategy_drift",
            importance=90.0,
            tags=[
                "portfolio", "auto_trader", "drift",
                f"strategy:{strategy}", "DRIFT_DOWN",
            ],
            memory_type="semantic",
            metadata={
                "strategy": strategy,
                "drift_status": drift_result.get("status"),
                "running_mean": drift_result.get("running_mean"),
                "recent_hit_rate": drift_result.get("recent_hit_rate"),
                "n": drift_result.get("n"),
                "pause_reason": pause_reason,
                "wave": "14K-K5b",
            },
        )
        log.info("[AT-ATTR] strategy_drift memory emitted for %s", strategy)
    except Exception as e:
        log.warning("[AT-ATTR] drift memory unit emit failed: %s", e)


async def _emit_close_prediction_record(
    *,
    paper_trade,
    trade_idea_id: Optional[str],
    outcome: str,
    engine_r: float,
    exit_price: float,
) -> None:
    """Gap-close B: write data/predictions/pred-auto-<tid>.json + mirror
    to SQLite. Mirrors the awarebot:predictor record shape so the existing
    /predictions endpoint surfaces auto-trader closes alongside organic
    predictions. Idempotent — filename uses trade_idea_id as the stable
    suffix so the same trade can't write twice."""
    import json
    import os
    from datetime import datetime, timezone
    from pathlib import Path

    if not trade_idea_id:
        return  # nothing to key on
    # Map R_multiple to prediction outcome
    if engine_r > 0:
        pred_outcome = "correct"
    elif engine_r < 0:
        pred_outcome = "incorrect"
    else:
        pred_outcome = "partial"  # scratch

    now_iso = datetime.now(timezone.utc).isoformat()
    symbol = getattr(paper_trade, "symbol", "?")
    direction = getattr(paper_trade, "direction", "?")
    strategy = getattr(paper_trade, "strategy", "auto")
    entry_price = getattr(paper_trade, "entry_price", 0)
    days_held = getattr(paper_trade, "days_held", 0)
    pid = f"pred-auto-{trade_idea_id}"

    consensus = (
        f"Auto-trader {direction} {symbol} from ${entry_price} "
        f"closed @ ${exit_price} ({outcome}); R={engine_r:+.2f}"
    )

    record = {
        "id": pid,
        "prediction_id": pid,
        "topic": f"auto_trader:{strategy}:{symbol}",
        "timestamp": now_iso,
        "created_at": now_iso,
        "consensus_prediction": consensus,
        "confidence": min(1.0, max(0.0, abs(engine_r) / 3.0)),  # |R|/3 capped
        "direction": (
            "bullish" if (direction == "long" and engine_r > 0) or
            (direction == "short" and engine_r < 0)
            else "bearish"
        ),
        "linked_signals": [],
        "models": ["auto_trader:paper_close"],
        "source": "auto_trader:paper_close",
        "outcome": pred_outcome,
        "outcome_recorded_at": now_iso,
        "metadata": {
            "trade_idea_id": trade_idea_id,
            "paper_trade_id": getattr(paper_trade, "id", None),
            "symbol": symbol,
            "direction": direction,
            "strategy": strategy,
            "engine_r": engine_r,
            "outcome_trigger": outcome,
            "exit_price": exit_price,
            "days_held": days_held,
            "wave": "14K-gap-close-B",
        },
    }

    base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    pred_dir = base / "data" / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)
    pred_file = pred_dir / f"{pid}.json"
    if pred_file.exists():
        return  # idempotent — already emitted
    pred_file.write_text(json.dumps(record, indent=2, sort_keys=True))

    # SQLite mirror (no-op if gate off)
    try:
        from ...persistence.predictions_writer import (
            mirror_prediction_to_sqlite, mirror_outcome_to_sqlite,
        )
        await mirror_prediction_to_sqlite(record, fallback_id=pid)
        await mirror_outcome_to_sqlite(pid, pred_outcome, recorded_at=now_iso)
    except Exception as e:
        log.debug("[AT-ATTR] SQLite mirror skipped: %s", e)

    log.info(
        "[AT-ATTR] prediction record %s emitted (outcome=%s R=%+.2f)",
        pid, pred_outcome, engine_r,
    )


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
