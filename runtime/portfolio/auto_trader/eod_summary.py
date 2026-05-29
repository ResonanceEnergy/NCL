"""
Auto-Trader End-of-Day summary — Wave 14K gap-close C

Fires at 21:55 ET (just before the 22:00 ET journal_reflection_loop)
so the daily reflection engine sees the agent's day as one coherent
journal entry rather than scattered per-trade MemUnits.

What it does:
  1. Read today's bandit/drift/graduation/friction/research-topics state
  2. Read today's closed paper trades + opens + rejects from observability
  3. Compose a 1-paragraph human-readable summary
  4. Create a JournalEntry (kind="reflection", importance 75) tagged
     auto_trader. The journal store's _bridge_to_memory auto-creates the
     MemUnit so the morning brief's context packet picks it up tomorrow.
  5. Append to data/portfolio/auto_trader/eod_summaries.jsonl (audit)

Storage:
  data/portfolio/auto_trader/eod_summaries.jsonl

Tunables (env):
  NCL_AT_EOD_HOUR_ET=21      (defaults 21:55 ET — 5min before journal reflection)
  NCL_AT_EOD_MINUTE_ET=55
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.eod_summary")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
EOD_LOG = NCL_BASE / "data" / "portfolio" / "auto_trader" / "eod_summaries.jsonl"
STATE_FILE = NCL_BASE / "data" / "portfolio" / "auto_trader" / "eod_state.json"

EOD_HOUR_ET = int(os.getenv("NCL_AT_EOD_HOUR_ET", "21"))
EOD_MINUTE_ET = int(os.getenv("NCL_AT_EOD_MINUTE_ET", "55"))


def _today_et() -> str:
    """Today's date in ET as YYYY-MM-DD."""
    # Approximate ET = UTC-4 (EDT). Good enough for the date key.
    now_utc = datetime.now(timezone.utc)
    et = now_utc - timedelta(hours=4)
    return et.strftime("%Y-%m-%d")


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _persist_state(d: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(d, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[AT-EOD] state persist failed: %s", e)


async def _build_summary() -> dict:
    """Aggregate everything the auto-trader did today."""
    today = _today_et()
    today_dt = datetime.fromisoformat(today).replace(tzinfo=timezone.utc)
    # ET 00:00 → UTC 04:00 (rough)
    cutoff = (today_dt - timedelta(hours=-4)).isoformat()

    summary = {
        "date": today,
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "state": {},
        "closes_today": 0,
        "winners": 0,
        "losers": 0,
        "scratches": 0,
        "total_r_today": 0.0,
        "tickers_closed": [],
        "opens_today": 0,
        "rejects_today": 0,
        "drift_signals": [],
        "graduated_strategies": [],
        "open_research_topics": 0,
        "council_vetoes": 0,
    }

    # State + counters
    try:
        from .state import get_state
        st = await get_state()
        summary["state"] = {
            "active": st.active,
            "paused_by": st.paused_by,
            "drawdown_halt": st.drawdown_halt_pause,
            "drawdown_band": st.drawdown_halt_band,
            "evaluated": st.ideas_evaluated_today,
            "opened": st.ideas_opened_today,
            "rejected": st.ideas_rejected_today,
            "last_loop_tick_iso": st.last_loop_tick_iso,
        }
        summary["opens_today"] = st.ideas_opened_today
        summary["rejects_today"] = st.ideas_rejected_today
    except Exception as e:
        log.debug("[AT-EOD] state read failed: %s", e)

    # Today's closes (from trade_idea_tracker)
    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        all_ideas = await tracker.list_by_strategy(None)
        for idea in all_ideas:
            closed_iso = idea.get("closed_at_iso") or ""
            if not closed_iso or closed_iso < cutoff:
                continue
            r = idea.get("R_multiple") or 0
            summary["closes_today"] += 1
            summary["total_r_today"] += r
            if r > 0:
                summary["winners"] += 1
            elif r < 0:
                summary["losers"] += 1
            else:
                summary["scratches"] += 1
            ticker = idea.get("ticker")
            if ticker and ticker not in summary["tickers_closed"]:
                summary["tickers_closed"].append(ticker)
    except Exception as e:
        log.debug("[AT-EOD] tracker read failed: %s", e)

    # Drift signals today
    try:
        from .drift_detector import all_states
        ds = await all_states()
        for strat, s in ds.items():
            last_iso = s.get("last_drift_iso") or ""
            if last_iso >= cutoff and s.get("last_status") in ("DRIFT_DOWN", "DRIFT_UP"):
                summary["drift_signals"].append({
                    "strategy": strat,
                    "status": s["last_status"],
                    "reason": (s.get("last_drift_reason") or "")[:80],
                })
    except Exception as e:
        log.debug("[AT-EOD] drift read failed: %s", e)

    # Graduation
    try:
        from .graduation_gate import evaluate_all
        grad = await evaluate_all()
        summary["graduated_strategies"] = (grad.get("_summary") or {}).get("graduated", [])
    except Exception as e:
        log.debug("[AT-EOD] graduation read failed: %s", e)

    # Open research topics
    try:
        from .self_research import list_open_research_topics
        topics = list_open_research_topics()
        summary["open_research_topics"] = len(topics)
    except Exception as e:
        log.debug("[AT-EOD] research topics read failed: %s", e)

    # Council vetoes (count from reasoning chains)
    try:
        from .observability import list_recent_chains
        chains = await list_recent_chains(limit=500)
        veto_count = 0
        for c in chains:
            ts = c.get("ts") or ""
            if ts < cutoff:
                continue
            pc = c.get("policy_check") or {}
            cc = pc.get("council_check") or {}
            if cc.get("veto"):
                veto_count += 1
        summary["council_vetoes"] = veto_count
    except Exception as e:
        log.debug("[AT-EOD] council veto count failed: %s", e)

    # Wave 14U-2/7 — push daily P&L into ADWIN portfolio drift detector
    # so variance regime shifts get caught. Non-blocking on failure.
    try:
        from .portfolio_drift import record_daily_pnl
        adwin_result = await record_daily_pnl(
            daily_pnl=float(summary.get("total_r_today") or 0),
            date_iso=summary["date"],
            brain=brain,
        )
        summary["adwin_drift"] = {
            "window_size": adwin_result.get("window_size"),
            "drift_detected": adwin_result.get("drift_detected"),
        }
        if adwin_result.get("drift_detected"):
            split = adwin_result.get("split") or {}
            summary["drift_signals"].append({
                "strategy": "portfolio_pnl",
                "status": "ADWIN_DRIFT",
                "mean_before": split.get("mean_w0"),
                "mean_after": split.get("mean_w1"),
            })
    except Exception as e:
        log.warning("[AT-EOD] ADWIN portfolio drift skipped: %s", e)

    return summary


def _compose_narrative(summary: dict) -> str:
    """Build a 1-paragraph human-readable summary for the journal entry."""
    parts = [
        f"AUTO-TRADER EOD SUMMARY — {summary['date']}.",
    ]
    s = summary.get("state") or {}
    parts.append(
        f"State: active={s.get('active')} paused_by={s.get('paused_by') or 'none'} "
        f"drawdown_band={s.get('drawdown_band') or '?'}."
    )
    parts.append(
        f"Today: evaluated {s.get('evaluated', 0)} ideas, "
        f"opened {summary['opens_today']}, rejected {summary['rejects_today']}, "
        f"closed {summary['closes_today']} "
        f"({summary['winners']}W / {summary['losers']}L / {summary['scratches']}S) "
        f"for {summary['total_r_today']:+.2f}R total."
    )
    if summary["tickers_closed"]:
        parts.append(
            f"Tickers closed: {', '.join(summary['tickers_closed'][:10])}."
        )
    if summary["drift_signals"]:
        parts.append(
            f"Drift signals: {len(summary['drift_signals'])} "
            f"({', '.join(d['strategy'] + ':' + d['status'] for d in summary['drift_signals'][:3])})."
        )
    if summary["graduated_strategies"]:
        parts.append(
            f"Graduated: {', '.join(summary['graduated_strategies'])}."
        )
    if summary["council_vetoes"]:
        parts.append(f"Council quorum vetoed {summary['council_vetoes']} high-R opens today.")
    if summary["open_research_topics"]:
        parts.append(
            f"{summary['open_research_topics']} open research topics."
        )
    return " ".join(parts)


def _is_already_done_today(state: dict) -> bool:
    return state.get("last_emit_date") == _today_et()


def _mark_done_today(state: dict) -> None:
    state["last_emit_date"] = _today_et()
    state["last_emit_iso"] = datetime.now(timezone.utc).isoformat()
    _persist_state(state)


async def emit_eod_summary(*, force: bool = False) -> Optional[dict]:
    """Build + persist + create JournalEntry. Idempotent per ET date.

    Returns the summary dict if emitted, None if already done today."""
    state = _load_state()
    if not force and _is_already_done_today(state):
        log.debug("[AT-EOD] already emitted for %s — skipping", _today_et())
        return None

    summary = await _build_summary()
    narrative = _compose_narrative(summary)
    summary["narrative"] = narrative

    # Append to audit log
    try:
        EOD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EOD_LOG, "a") as f:
            f.write(json.dumps(summary) + "\n")
    except Exception as e:
        log.warning("[AT-EOD] audit log append failed: %s", e)

    # Create JournalEntry — reflection engine picks it up at 22:00 ET.
    # _bridge_to_memory inside journal_store creates the MemUnit so the
    # morning brief context packet sees it tomorrow.
    try:
        from ...journal.store import JournalStore
        from ...memory.working_context import DailyContextWindow
        # Lightweight init — no working_context binding needed for an
        # auto-trader entry (it's importance 75 = bridges to memory anyway
        # but doesn't try to pin to working_context if WC is unavailable).
        journal = JournalStore()
        await journal.create_entry(
            content=narrative,
            entry_type="reflection",
            title=f"Auto-Trader EOD {summary['date']}",
            tags=["auto_trader", "eod", "hedge_fund_training"],
            importance=75.0,
            source_context="auto_trader:eod_summary",
        )
        log.info("[AT-EOD] journal entry created for %s", summary["date"])
    except Exception as e:
        log.warning("[AT-EOD] journal entry failed (non-fatal): %s", e)

    _mark_done_today(state)
    return summary


async def eod_summary_loop() -> None:
    """Long-running task — fires emit_eod_summary at NCL_AT_EOD_HOUR_ET:MINUTE
    ET daily. Idempotent so missed minute → next-minute fire is harmless."""
    log.info(
        "[AT-EOD] starting EOD summary loop (fires daily at %02d:%02d ET)",
        EOD_HOUR_ET, EOD_MINUTE_ET,
    )
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            # Approximate ET = UTC-4
            et = now_utc - timedelta(hours=4)
            target_h = EOD_HOUR_ET
            target_m = EOD_MINUTE_ET
            if (et.hour, et.minute) == (target_h, target_m):
                await emit_eod_summary()
                # Sleep 65s to ensure we don't double-fire in the same minute
                await asyncio.sleep(65)
            else:
                # Sleep 30s and re-check (cheap, lets us pick up any clock drift)
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            log.info("[AT-EOD] cancelled")
            raise
        except Exception as e:
            log.error("[AT-EOD] tick error (continuing): %s", e, exc_info=True)
            await asyncio.sleep(60)
