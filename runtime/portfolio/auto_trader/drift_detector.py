"""
Auto-Trader concept-drift detector — Wave 14K Phase 6 (K5a + K5b)

Per-strategy hit-rate drift detection on the closed-trade stream.

The full ADDM paper covers an AR(p) residual test. For a binary
win/loss stream of paper trades, the simpler Page-Hinkley sequential
mean-shift test is both well-established in the streaming literature
AND directly interpretable to the operator. We implement Page-Hinkley
with two cumulative test statistics (one for downward drift, one for
upward), reset on signal, and a rolling-window fallback for
"is the recent N-window meaningfully different from the long-run mean"
sanity check.

States returned:
  STABLE       — no drift detected
  DRIFT_DOWN   — hit-rate has trended materially below the running mean
                 (this is the bad case — auto-pause trigger)
  DRIFT_UP     — hit-rate has trended materially ABOVE the running mean
                 (informational — strategy is on a hot streak)

Outputs are deterministic given the input stream; persisted state is
just for warm-start across Brain bounces.

Storage:
  data/portfolio/auto_trader/drift_state.json    — per-strategy detector state
  data/portfolio/auto_trader/drift_events.jsonl  — every signal (append-only)

Tunables (env):
  NCL_DRIFT_PH_DELTA       — Page-Hinkley magnitude tolerance (default 0.005)
  NCL_DRIFT_PH_LAMBDA      — Page-Hinkley alarm threshold (default 0.50)
  NCL_DRIFT_MIN_N          — minimum observations before drift can fire (default 20)
  NCL_DRIFT_WINDOW         — rolling sanity-check window (default 15)
  NCL_DRIFT_AUTOPAUSE_REASON— string used when auto-pausing on DRIFT_DOWN
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.portfolio.auto_trader.drift_detector")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
STATE_FILE = DATA_DIR / "drift_state.json"
EVENTS_FILE = DATA_DIR / "drift_events.jsonl"

PH_DELTA = float(os.getenv("NCL_DRIFT_PH_DELTA", "0.005"))
PH_LAMBDA = float(os.getenv("NCL_DRIFT_PH_LAMBDA", "0.50"))
MIN_N = int(os.getenv("NCL_DRIFT_MIN_N", "20"))
WINDOW = int(os.getenv("NCL_DRIFT_WINDOW", "15"))

# Allowed status values
STABLE = "STABLE"
DRIFT_DOWN = "DRIFT_DOWN"
DRIFT_UP = "DRIFT_UP"


@dataclass
class PHState:
    """Page-Hinkley state per strategy.

    Tracks two cumulative test statistics. m_down builds when actual
    hit-rate (rolling) falls BELOW the long-run running mean (we use
    a sliding window for the local mean). m_up does the reverse.
    Either statistic crossing PH_LAMBDA triggers a drift signal, and
    the corresponding statistic resets.
    """

    n: int = 0  # total observations
    running_mean: float = 0.5  # exponential running mean of wins (0/1)
    m_down: float = 0.0  # cumulative sum for downward drift
    m_up: float = 0.0  # cumulative sum for upward drift
    last_status: str = STABLE
    last_status_iso: Optional[str] = None
    recent_window: list = field(default_factory=list)  # last WINDOW outcomes (1=win)
    drift_down_count: int = 0  # lifetime DRIFT_DOWN signals
    drift_up_count: int = 0  # lifetime DRIFT_UP signals
    last_drift_iso: Optional[str] = None
    last_drift_reason: str = ""


_STATE: dict[str, PHState] = {}
_LOCK = asyncio.Lock()
_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> None:
    """Lazy-load state from disk. Idempotent."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not STATE_FILE.exists():
        return
    try:
        raw = json.loads(STATE_FILE.read_text())
        if not isinstance(raw, dict):
            return
        field_names = {f for f in PHState.__dataclass_fields__}  # type: ignore[attr-defined]
        for strat, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            kept = {k: v for k, v in payload.items() if k in field_names}
            try:
                _STATE[strat] = PHState(**kept)
            except Exception as e:
                log.warning("[DRIFT] skipping malformed state for %s: %s", strat, e)
    except Exception as e:
        log.warning("[DRIFT] state load failed: %s", e)


def _persist_state() -> None:
    _ensure_dir()
    snapshot = {strat: asdict(s) for strat, s in _STATE.items()}
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[DRIFT] state persist failed: %s", e)


def _append_event(strategy: str, status: str, ph_state: PHState, reason: str) -> None:
    row = {
        "ts": _now_iso(),
        "strategy": strategy,
        "status": status,
        "n": ph_state.n,
        "running_mean": round(ph_state.running_mean, 4),
        "m_down": round(ph_state.m_down, 4),
        "m_up": round(ph_state.m_up, 4),
        "reason": reason,
    }
    try:
        _ensure_dir()
        with open(EVENTS_FILE, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("[DRIFT] event append failed: %s", e)


async def update(
    strategy: str,
    *,
    win: bool,
) -> dict:
    """Feed a new closed-trade observation into the Page-Hinkley detector.

    Returns a dict:
      {
        strategy, status (STABLE | DRIFT_DOWN | DRIFT_UP),
        n, running_mean, m_down, m_up,
        recent_hit_rate, transition (bool)
      }
    """
    async with _LOCK:
        _load_state()
        s = _STATE.get(strategy)
        if s is None:
            s = PHState()
            _STATE[strategy] = s

        x = 1.0 if win else 0.0

        # Update sliding window first (for recent-hit-rate report + reset check)
        s.recent_window.append(x)
        if len(s.recent_window) > WINDOW:
            s.recent_window.pop(0)

        s.n += 1

        # Incremental (true) sample mean — the canonical Page-Hinkley
        # reference. Welford-style update: mean_n = mean_{n-1} + (x - mean_{n-1})/n.
        # This is unbiased and self-correcting against the global rate,
        # so alternating 0/1 converges to exactly 0.5 instead of drifting
        # like an EWMA bootstrap.
        s.running_mean = s.running_mean + (x - s.running_mean) / s.n

        # Page-Hinkley deviation against the (now-updated) sample mean,
        # with magnitude tolerance PH_DELTA. Symmetric: m_down tracks
        # accumulated below-mean evidence, m_up tracks above-mean.
        # Either crossing PH_LAMBDA triggers a drift signal.
        dev_down = (s.running_mean - x) - PH_DELTA
        s.m_down = max(0.0, s.m_down + dev_down)
        dev_up = (x - s.running_mean) - PH_DELTA
        s.m_up = max(0.0, s.m_up + dev_up)

        # Determine status
        new_status = STABLE
        reason = ""
        if s.n >= MIN_N:
            if s.m_down >= PH_LAMBDA:
                new_status = DRIFT_DOWN
                reason = (
                    f"PH down statistic crossed lambda "
                    f"(m_down={s.m_down:.3f} >= {PH_LAMBDA:.3f}); "
                    f"running mean {s.running_mean:.2%}, "
                    f"recent hit rate {sum(s.recent_window)/len(s.recent_window):.2%}"
                )
                s.m_down = 0.0  # reset on signal
                s.drift_down_count += 1
                s.last_drift_iso = _now_iso()
                s.last_drift_reason = reason
            elif s.m_up >= PH_LAMBDA:
                new_status = DRIFT_UP
                reason = (
                    f"PH up statistic crossed lambda "
                    f"(m_up={s.m_up:.3f} >= {PH_LAMBDA:.3f}); "
                    f"running mean {s.running_mean:.2%}, "
                    f"recent hit rate {sum(s.recent_window)/len(s.recent_window):.2%}"
                )
                s.m_up = 0.0
                s.drift_up_count += 1
                s.last_drift_iso = _now_iso()
                s.last_drift_reason = reason

        transition = new_status != s.last_status
        s.last_status = new_status
        s.last_status_iso = _now_iso()
        _persist_state()

        if new_status != STABLE:
            _append_event(strategy, new_status, s, reason)
            log.warning(
                "[DRIFT] %s -> %s (n=%d) %s",
                strategy,
                new_status,
                s.n,
                reason,
            )

        # Wave 14W-E: on DRIFT_DOWN *transition* (not every tick after),
        # fire an intel_request(council.spawn) so a contrarian debate
        # opens. Previously drift terminated at a MemUnit; the agent
        # never asked the council why the edge dropped. Bounded
        # fire-and-forget so any failure here can't stall the loop.
        if (
            transition
            and new_status == DRIFT_DOWN
            and os.getenv("NCL_AGENT_BUS_DRIFT_COUNCIL", "1") == "1"
        ):
            try:
                from ...agent_bus import intel_request as _bus

                # Schedule on the running loop without awaiting; we don't
                # want the council debate (~30s+) to block outcome attribution.
                asyncio.get_event_loop().create_task(
                    _bus.intel_request(
                        kind=_bus.RequestKind.COUNCIL_SPAWN,
                        caller=f"auto_trader:drift_detector:{strategy}",
                        urgency="high",
                        topic=f"Drift detected on '{strategy}' — why is edge dropping?",
                        prompt=(
                            f"The auto-trader's drift detector just flagged "
                            f"DRIFT_DOWN on strategy '{strategy}'.\n\n"
                            f"Evidence: {reason}\n\n"
                            "Debate (i) the most-likely root cause "
                            "(regime change, recipe degradation, data drift, "
                            "execution drift), (ii) whether the auto-pause "
                            "should be lifted after a recovery threshold "
                            "or the strategy retired, and (iii) one "
                            "concrete next action to take TODAY."
                        ),
                        reason=f"drift_detected:{strategy}",
                        panel="delphi_mad_4",
                    )
                )
            except Exception as _e:
                log.debug("[DRIFT] council intel_request failed: %s", _e)

        recent_hr = sum(s.recent_window) / len(s.recent_window) if s.recent_window else 0.0
        return {
            "strategy": strategy,
            "status": new_status,
            "n": s.n,
            "running_mean": round(s.running_mean, 4),
            "m_down": round(s.m_down, 4),
            "m_up": round(s.m_up, 4),
            "recent_hit_rate": round(recent_hr, 4),
            "transition": transition,
            "reason": reason,
        }


async def get_strategy_state(strategy: str) -> Optional[dict]:
    async with _LOCK:
        _load_state()
        s = _STATE.get(strategy)
        if s is None:
            return None
        recent_hr = sum(s.recent_window) / len(s.recent_window) if s.recent_window else 0.0
        d = asdict(s)
        d["recent_hit_rate"] = round(recent_hr, 4)
        return d


async def all_states() -> dict:
    async with _LOCK:
        _load_state()
        out = {}
        for strat, s in _STATE.items():
            recent_hr = sum(s.recent_window) / len(s.recent_window) if s.recent_window else 0.0
            d = asdict(s)
            d["recent_hit_rate"] = round(recent_hr, 4)
            out[strat] = d
        return out


async def reset_strategy(strategy: str) -> bool:
    """Operator-initiated reset (e.g. after intentional re-spec). True
    if the strategy existed and was cleared."""
    async with _LOCK:
        _load_state()
        if strategy not in _STATE:
            return False
        _STATE[strategy] = PHState()
        _persist_state()
        _append_event(strategy, "RESET", _STATE[strategy], "operator reset")
        log.info("[DRIFT] %s state reset by operator", strategy)
        return True


# ── Auto-pause hook (K5b) ─────────────────────────────────────────


async def maybe_auto_pause(strategy: str, drift_result: dict) -> dict:
    """If drift_result indicates DRIFT_DOWN, set drawdown-style pause
    on AutoTraderState so the loop stops opening new trades. Existing
    paper trades continue to mark-to-market and close normally.

    Returns: {paused: bool, reason: str}.
    """
    if drift_result.get("status") != DRIFT_DOWN:
        return {"paused": False, "reason": "no drift-down signal"}
    if not drift_result.get("transition"):
        return {"paused": False, "reason": "no state transition (already drifting)"}
    try:
        from .state import pause

        reason = os.getenv(
            "NCL_DRIFT_AUTOPAUSE_REASON",
            f"K5b auto-pause on DRIFT_DOWN for strategy={strategy} "
            f"(running_mean {drift_result['running_mean']:.2%}, "
            f"recent_hit_rate {drift_result['recent_hit_rate']:.2%})",
        )
        await pause(reason=reason, by="drift_detector")
        log.warning(
            "[DRIFT] AUTO-PAUSED auto-trader due to %s drift: %s",
            strategy,
            reason,
        )
        return {"paused": True, "reason": reason}
    except Exception as e:
        log.error("[DRIFT] auto-pause failed: %s", e)
        return {"paused": False, "reason": f"auto-pause exception: {e}"}
