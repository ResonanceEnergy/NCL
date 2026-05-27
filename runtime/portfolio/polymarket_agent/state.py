"""
Polymarket Agent shared state — Wave 14R R1

Mirrors auto_trader/state.py but with polymarket-specific counters.
Default OFF; operator opts in via POST /polymarket-agent/resume.

Storage: data/portfolio/polymarket_agent/state.json (atomic write).
Singleton via get_state(). Async-safe via _LOCK.
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

log = logging.getLogger("ncl.portfolio.polymarket_agent.state")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "polymarket_agent"
STATE_FILE = DATA_DIR / "state.json"


@dataclass
class PolymarketAgentState:
    """Mutable global state for the polymarket-agent loop."""
    active: bool = False
    paused_by: Optional[str] = None  # "operator" | "circuit_breaker" | "capability_gap"
    pause_reason: str = ""
    paused_at_iso: Optional[str] = None

    last_loop_tick_iso: Optional[str] = None
    last_collector_tick_iso: Optional[str] = None
    last_resolution_tick_iso: Optional[str] = None

    # Soft daily counters (reset at UTC midnight)
    edges_evaluated_today: int = 0
    bets_placed_today: int = 0
    bets_skipped_today: int = 0
    resolutions_today: int = 0
    last_counter_reset_date: str = ""

    # Bankroll (paper-only, starts at $1000 — operator can override via REST)
    starting_bankroll_usd: float = 1000.0
    current_bankroll_usd: float = 1000.0

    revision: int = 0
    loaded_at_iso: Optional[str] = None


_STATE: Optional[PolymarketAgentState] = None
_LOCK = asyncio.Lock()
_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_from_disk() -> PolymarketAgentState:
    global _LOADED
    if not STATE_FILE.exists():
        _LOADED = True
        return PolymarketAgentState(loaded_at_iso=_now_iso())
    try:
        raw = json.loads(STATE_FILE.read_text())
        s = PolymarketAgentState(**{
            k: v for k, v in raw.items()
            if k in PolymarketAgentState.__dataclass_fields__
        })
        s.loaded_at_iso = _now_iso()
        _LOADED = True
        return s
    except Exception as e:
        log.warning("[POLY-STATE] load failed (%s), fresh state", e)
        _LOADED = True
        return PolymarketAgentState(loaded_at_iso=_now_iso())


def _persist_unlocked(state: PolymarketAgentState) -> None:
    _ensure_dir()
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(asdict(state), indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[POLY-STATE] persist failed: %s", e)


async def get_state() -> PolymarketAgentState:
    global _STATE
    async with _LOCK:
        if _STATE is None:
            _STATE = _load_from_disk()
            log.info(
                "[POLY-STATE] loaded active=%s paused_by=%s bankroll=$%.2f",
                _STATE.active, _STATE.paused_by, _STATE.current_bankroll_usd,
            )
        # Daily counter reset
        today = _today_utc()
        if _STATE.last_counter_reset_date != today:
            _STATE.edges_evaluated_today = 0
            _STATE.bets_placed_today = 0
            _STATE.bets_skipped_today = 0
            _STATE.resolutions_today = 0
            _STATE.last_counter_reset_date = today
            _persist_unlocked(_STATE)
        return _STATE


async def update_state(**fields) -> PolymarketAgentState:
    global _STATE
    async with _LOCK:
        if _STATE is None:
            _STATE = _load_from_disk()
        for k, v in fields.items():
            if k in PolymarketAgentState.__dataclass_fields__:
                setattr(_STATE, k, v)
        _STATE.revision += 1
        _persist_unlocked(_STATE)
        return _STATE


async def is_active() -> bool:
    s = await get_state()
    return s.active and s.paused_by is None


async def set_paused(by: str = "operator", reason: str = "") -> PolymarketAgentState:
    log.warning("[POLY-STATE] pausing by=%s reason=%s", by, reason)
    return await update_state(
        active=False, paused_by=by, pause_reason=reason,
        paused_at_iso=_now_iso(),
    )


async def set_resumed() -> PolymarketAgentState:
    log.info("[POLY-STATE] resuming")
    return await update_state(
        active=True, paused_by=None, pause_reason="", paused_at_iso=None,
    )


async def record_tick(kind: str) -> None:
    """kind: 'loop' | 'collector' | 'resolution'"""
    key_map = {
        "loop": "last_loop_tick_iso",
        "collector": "last_collector_tick_iso",
        "resolution": "last_resolution_tick_iso",
    }
    if kind in key_map:
        await update_state(**{key_map[kind]: _now_iso()})


async def increment_counter(name: str, delta: int = 1) -> None:
    """name: edges_evaluated_today | bets_placed_today | bets_skipped_today | resolutions_today"""
    s = await get_state()
    async with _LOCK:
        cur = getattr(s, name, 0)
        setattr(s, name, cur + delta)
        _persist_unlocked(s)


async def adjust_bankroll(delta_usd: float, reason: str = "") -> None:
    """Apply realized P/L to paper bankroll."""
    async with _LOCK:
        global _STATE
        if _STATE is None:
            _STATE = _load_from_disk()
        _STATE.current_bankroll_usd = round(_STATE.current_bankroll_usd + delta_usd, 2)
        _persist_unlocked(_STATE)
        log.info(
            "[POLY-STATE] bankroll %+.2f → $%.2f (%s)",
            delta_usd, _STATE.current_bankroll_usd, reason,
        )
