"""
Auto-Trader shared state — Wave 14K K0a

Tracks: paused/active flag, pause reason, last-seen trade_idea_id,
last loop tick, drawdown_pause boolean (auto-pause when J0c band=halt).

Storage: data/portfolio/auto_trader/state.json (atomic write-and-replace).
Singleton via get_state() / update_state(). Async-safe via _LOCK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.state")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
STATE_FILE = DATA_DIR / "state.json"


@dataclass
class AutoTraderState:
    """Mutable global state for the auto-trader loop."""
    # Operator-controlled
    active: bool = False             # default OFF; operator opts in via REST POST /resume
    paused_by: Optional[str] = None  # "operator" | "drawdown_halt" | "circuit_breaker" | None
    pause_reason: str = ""
    paused_at_iso: Optional[str] = None

    # Loop progress
    last_loop_tick_iso: Optional[str] = None
    last_seen_trade_idea_id: Optional[str] = None
    ideas_evaluated_today: int = 0
    ideas_opened_today: int = 0
    ideas_rejected_today: int = 0

    # Drawdown auto-pause (K0c) — set by the loop when drawdown_bucket.band == "halt"
    drawdown_halt_pause: bool = False
    drawdown_halt_band: Optional[str] = None
    drawdown_halt_at_iso: Optional[str] = None

    # Soft counters (reset at UTC midnight)
    counters_date_utc: str = ""

    # Free-form metadata
    metadata: dict = field(default_factory=dict)


_STATE: Optional[AutoTraderState] = None
_LOCK = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _persist(state: AutoTraderState) -> None:
    _ensure_dir()
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(asdict(state), indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[AT-STATE] persist failed: %s", e)


def _load() -> AutoTraderState:
    if not STATE_FILE.exists():
        return AutoTraderState(counters_date_utc=_today_utc())
    try:
        raw = json.loads(STATE_FILE.read_text())
        if not isinstance(raw, dict):
            return AutoTraderState(counters_date_utc=_today_utc())
        field_names = {f for f in AutoTraderState.__dataclass_fields__}  # type: ignore[attr-defined]
        kept = {k: v for k, v in raw.items() if k in field_names}
        return AutoTraderState(**kept)
    except Exception as e:
        log.warning("[AT-STATE] load failed (%s) — using defaults", e)
        return AutoTraderState(counters_date_utc=_today_utc())


def _rollover_counters_if_needed(state: AutoTraderState) -> None:
    today = _today_utc()
    if state.counters_date_utc != today:
        state.counters_date_utc = today
        state.ideas_evaluated_today = 0
        state.ideas_opened_today = 0
        state.ideas_rejected_today = 0


async def get_state() -> AutoTraderState:
    """Return current state (lazy-loaded, async-safe)."""
    global _STATE
    if _STATE is not None:
        async with _LOCK:
            _rollover_counters_if_needed(_STATE)
        return _STATE
    async with _LOCK:
        if _STATE is None:
            _STATE = _load()
            _rollover_counters_if_needed(_STATE)
            log.info(
                "[AT-STATE] loaded — active=%s paused_by=%s drawdown_halt=%s",
                _STATE.active, _STATE.paused_by, _STATE.drawdown_halt_pause,
            )
    return _STATE


async def _update(**fields) -> AutoTraderState:
    """Atomic field update + persist. Returns new state."""
    state = await get_state()
    async with _LOCK:
        _rollover_counters_if_needed(state)
        for k, v in fields.items():
            if hasattr(state, k):
                setattr(state, k, v)
        _persist(state)
    return state


# ── Operator API (REST endpoints call these) ─────────────────────

async def is_active() -> bool:
    """True only when active AND not paused (by anything)."""
    state = await get_state()
    return state.active and state.paused_by is None and not state.drawdown_halt_pause


async def pause(reason: str, by: str = "operator") -> AutoTraderState:
    """Manual pause. by='operator' from REST; loop calls by='drawdown_halt' etc."""
    return await _update(
        paused_by=by,
        pause_reason=reason,
        paused_at_iso=_now_iso(),
    )


async def resume() -> AutoTraderState:
    """Resume from pause. Does NOT clear drawdown_halt_pause — that's
    cleared automatically when band moves back to non-halt."""
    return await _update(
        active=True,
        paused_by=None,
        pause_reason="",
        paused_at_iso=None,
    )


async def set_drawdown_halt(halted: bool, band: Optional[str] = None) -> AutoTraderState:
    """Loop calls this every tick after checking drawdown_bucket.
    Idempotent — only stamps the at_iso on band transition."""
    state = await get_state()
    if halted == state.drawdown_halt_pause and band == state.drawdown_halt_band:
        return state
    fields = {"drawdown_halt_pause": halted, "drawdown_halt_band": band}
    if halted:
        fields["drawdown_halt_at_iso"] = _now_iso()
    else:
        fields["drawdown_halt_at_iso"] = None
    return await _update(**fields)


async def record_tick(
    *,
    evaluated: int = 0,
    opened: int = 0,
    rejected: int = 0,
    last_seen_id: Optional[str] = None,
) -> AutoTraderState:
    """Loop calls this each tick with delta counters."""
    state = await get_state()
    async with _LOCK:
        _rollover_counters_if_needed(state)
        state.last_loop_tick_iso = _now_iso()
        state.ideas_evaluated_today += evaluated
        state.ideas_opened_today += opened
        state.ideas_rejected_today += rejected
        if last_seen_id:
            state.last_seen_trade_idea_id = last_seen_id
        _persist(state)
    return state
