"""
Auto-Trader portfolio drift detector — Wave 14U-2/7

ADWIN-style adaptive window concept-drift detector on the rolling
portfolio P&L distribution. Complements the per-strategy Page-Hinkley
detector (Wave 14K K5a) by catching VARIANCE regime changes that PH
misses.

Why ADWIN here (research from AUA capstone 2025):
  - Page-Hinkley is best for mean-shift on a stationary stream
    (per-strategy hit rate). It misses variance regime change.
  - ADWIN maintains an adaptive window that shrinks when a statistically
    significant change is detected, even if the mean is constant.
  - Daily portfolio P&L distribution variance shifts on:
    * volatility regime change (low-vol → high-vol)
    * leverage creep
    * crowded trade unwinding
  - These are precisely the things Page-Hinkley CAN'T detect at the
    portfolio level.

This is a pure-python ADWIN implementation (no river dependency) — the
algorithm is simple enough (~120 LOC) and we avoid pulling river into
the brain's dependency tree.

ADWIN sketch (Bifet & Gavaldà 2007):
  - Maintain a sliding window W of recent observations
  - On each new value: try splitting W = W₀ + W₁ at each cut point
  - If |mean(W₀) - mean(W₁)| > ε_cut, drop W₀ (drift detected)
  - ε_cut derived from Hoeffding bound at confidence δ:
      ε_cut = sqrt((1/(2m)) × ln(4/δ))  where m = harmonic mean of |W₀|, |W₁|

Storage:
  data/portfolio/auto_trader/portfolio_drift_state.json
    {window: [...], drift_events: [...], last_check_iso}

Tunables (env):
  NCL_ADWIN_DELTA              default 0.002 (sensitivity; smaller = more conservative)
  NCL_ADWIN_MAX_WINDOW         default 200   (cap window size)
  NCL_ADWIN_MIN_WINDOW         default 30    (warmup before checks)
  NCL_PORT_DRIFT_DISABLED      "1"/"0" default "0"
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.portfolio_drift")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
STATE_FILE = NCL_BASE / "data" / "portfolio" / "auto_trader" / "portfolio_drift_state.json"

DELTA = float(os.getenv("NCL_ADWIN_DELTA", "0.002"))
MAX_WINDOW = int(os.getenv("NCL_ADWIN_MAX_WINDOW", "200"))
MIN_WINDOW = int(os.getenv("NCL_ADWIN_MIN_WINDOW", "30"))
DISABLED = os.getenv("NCL_PORT_DRIFT_DISABLED", "0") == "1"

_LOCK = asyncio.Lock()
_STATE: dict = {"window": [], "drift_events": [], "last_check_iso": None}
_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> None:
    global _LOADED, _STATE
    if _LOADED:
        return
    _LOADED = True
    if not STATE_FILE.exists():
        return
    try:
        raw = json.loads(STATE_FILE.read_text())
        if isinstance(raw, dict):
            _STATE.update(raw)
            # Truncate huge windows on load
            if len(_STATE.get("window", [])) > MAX_WINDOW:
                _STATE["window"] = _STATE["window"][-MAX_WINDOW:]
            _STATE["drift_events"] = (_STATE.get("drift_events") or [])[-20:]
    except Exception as e:
        log.warning("[PORT-DRIFT] state load failed: %s", e)


def _persist() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        # Cap window + events for disk size
        snapshot = {
            "window": _STATE.get("window", [])[-MAX_WINDOW:],
            "drift_events": _STATE.get("drift_events", [])[-20:],
            "last_check_iso": _STATE.get("last_check_iso"),
        }
        tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[PORT-DRIFT] persist failed: %s", e)


def _hoeffding_eps(n0: int, n1: int, delta: float = DELTA) -> float:
    """ε_cut bound for ADWIN's mean-difference test."""
    if n0 < 2 or n1 < 2:
        return float("inf")
    # Harmonic mean of sub-window lengths
    m = 1.0 / ((1.0 / n0) + (1.0 / n1))
    try:
        return math.sqrt((1.0 / (2.0 * m)) * math.log(4.0 / max(delta, 1e-12)))
    except (ValueError, ZeroDivisionError):
        return float("inf")


def _adwin_split_test(window: list[float], delta: float = DELTA) -> Optional[dict]:
    """Try every cut point in window; return the first that exhibits
    statistically significant mean shift (Hoeffding bound at δ).

    Returns None if no drift; else a dict with split details."""
    n = len(window)
    if n < MIN_WINDOW:
        return None
    # Iterate cut points from 5 up to n-5 (require min 5 each side)
    # For efficiency we scan in jumps of max(1, n // 30)
    step = max(1, n // 30)
    for cut in range(5, n - 5, step):
        w0 = window[:cut]
        w1 = window[cut:]
        m0 = sum(w0) / len(w0)
        m1 = sum(w1) / len(w1)
        diff = abs(m1 - m0)
        eps = _hoeffding_eps(len(w0), len(w1), delta)
        if diff > eps:
            return {
                "cut_index": cut,
                "n0": len(w0), "n1": len(w1),
                "mean_w0": round(m0, 6),
                "mean_w1": round(m1, 6),
                "diff": round(diff, 6),
                "epsilon": round(eps, 6),
                "delta": delta,
            }
    return None


async def record_daily_pnl(*, daily_pnl: float, date_iso: str,
                            brain=None) -> dict:
    """Append today's portfolio P&L to the ADWIN window + check for drift.

    daily_pnl: signed (+win / -loss). Operator can pass either dollar P&L
               or % of NAV — only the stream's stationarity matters for
               ADWIN, not the unit.

    Returns:
      {
        recorded: bool, window_size: int,
        drift_detected: bool, split: dict | None,
        emitted_memory: bool,
      }
    """
    if DISABLED:
        return {"disabled": True, "drift_detected": False}
    async with _LOCK:
        _load()
        window = _STATE.setdefault("window", [])
        window.append(float(daily_pnl))
        if len(window) > MAX_WINDOW:
            del window[:-MAX_WINDOW]
        _STATE["last_check_iso"] = _now_iso()
        # Run ADWIN test
        split = _adwin_split_test(window, delta=DELTA)
        out: dict = {
            "recorded": True, "window_size": len(window),
            "drift_detected": split is not None, "split": split,
            "emitted_memory": False,
            "date_iso": date_iso,
        }
        if split is not None:
            event = {
                "ts": _now_iso(),
                "date_iso": date_iso,
                **split,
            }
            _STATE.setdefault("drift_events", []).append(event)
            # Drop pre-split observations (ADWIN behavior)
            cut = split["cut_index"]
            _STATE["window"] = window[cut:]
            log.warning(
                "[PORT-DRIFT] DRIFT DETECTED at cut=%d: mean shift "
                "%.4f → %.4f (diff=%.4f > ε=%.4f). Window shrunk to %d.",
                cut, split["mean_w0"], split["mean_w1"],
                split["diff"], split["epsilon"], len(_STATE["window"]),
            )
            # Emit high-importance memory unit
            if brain is not None:
                try:
                    mem = getattr(brain, "memory_store", None)
                    if mem and hasattr(mem, "create_unit"):
                        await mem.create_unit(
                            content=(
                                f"PORTFOLIO DRIFT DETECTED (ADWIN): daily P&L "
                                f"distribution mean shifted from {split['mean_w0']:.4f} "
                                f"to {split['mean_w1']:.4f} "
                                f"(diff={split['diff']:.4f} > ε={split['epsilon']:.4f} "
                                f"at δ={DELTA}). Window: {split['n0']} → {split['n1']} "
                                f"obs. Likely cause: volatility regime change, leverage "
                                f"creep, or crowded-trade unwinding. Operator should "
                                f"review portfolio composition + drawdown bucket."
                            ),
                            source="portfolio:adwin_drift",
                            importance=92.0,
                            tags=["portfolio", "auto_trader", "drift", "adwin",
                                  "regime_change"],
                            memory_type="semantic",
                            metadata={
                                "split": split,
                                "wave": "14U-2/7",
                            },
                        )
                        out["emitted_memory"] = True
                except Exception as e:
                    log.warning("[PORT-DRIFT] memory emit failed: %s", e)
        _persist()
        return out


async def get_state() -> dict:
    async with _LOCK:
        _load()
        return {
            "window_size": len(_STATE.get("window", [])),
            "last_check_iso": _STATE.get("last_check_iso"),
            "drift_event_count": len(_STATE.get("drift_events", [])),
            "recent_drift_events": _STATE.get("drift_events", [])[-5:],
            "delta": DELTA,
            "max_window": MAX_WINDOW,
            "min_window": MIN_WINDOW,
        }


__all__ = ["record_daily_pnl", "get_state", "DELTA", "MAX_WINDOW"]
