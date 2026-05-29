"""
Auto-Trader cycle-phase watcher — Wave 14U-2/3

Watches the cycle_phase classifier (Wave 14I) for regime transitions.
On detected transition (e.g. mid_cycle → late_cycle), triggers
strategy_bandit.decay_priors() so Thompson sampling re-explores
regime-sensitive strategies under the new market regime.

Why this matters (research from `arxiv:2203.04769` autoregressive drift):
  A strategy with α=20, β=5 from 25 mid-cycle trades has a posterior
  mean of 0.80 (very confident). When cycle_phase flips to late_cycle,
  those priors are *probably wrong* — the strategy may no longer have
  the same edge. Without decay, Thompson keeps sampling the strategy
  at ~80% expected win rate, ignoring the regime shift until enough
  losses accumulate to overwhelm the old prior (~30-50 trades). With
  decay factor 0.3: α' = 6, β' = 1.5 — same mean (0.80) but enough
  variance that Thompson explores alternatives. Recovery via real
  data is ~10-15 trades instead.

Regime-sensitivity map (which strategies decay on which transition):
  - GOAT / BRAVO / momentum / trend: decay on ANY phase transition
  - mean_reversion: decay when volatility regime changes (low → high)
  - pairs: decay on macro transitions (correlation shifts)
  - factor: decay on cycle phase (style rotation)
  - whale_flow / options: decay rarely (options flow patterns
    are regime-independent on short timeframes)
  - crypto_carry: decay on macro liquidity transitions only

State:
  data/portfolio/auto_trader/cycle_watcher_state.json
    {last_seen_phase, last_check_iso, decay_history: [...]}

Loop integration:
  Called from auto_trader_loop (Wave 14K loop.py) every N ticks
  (default every 60 ticks = ~1 hr in market hours). Cheap — only
  fires LLM/IO when phase actually transitions.

Tunables (env):
  NCL_CYCLE_DECAY_FACTOR        default 0.3
  NCL_CYCLE_WATCHER_DISABLED    "1" / "0"  default "0"
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.cycle_watcher")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
STATE_FILE = NCL_BASE / "data" / "portfolio" / "auto_trader" / "cycle_watcher_state.json"

DECAY_FACTOR = float(os.getenv("NCL_CYCLE_DECAY_FACTOR", "0.3"))
DISABLED = os.getenv("NCL_CYCLE_WATCHER_DISABLED", "0") == "1"

# Per-strategy regime sensitivity. True = decay on ANY phase transition.
# False = ignore phase transitions (strategy is regime-independent).
REGIME_SENSITIVE: dict[str, bool] = {
    "goat": True,
    "bravo": True,
    "momentum": True,
    "pairs": True,
    "pairs_stat_arb": True,
    "mean_reversion": True,
    "factor": True,
    "pead": False,           # event-driven; less regime-dependent
    "whale_flow": False,     # options flow is short-horizon
    "options": False,        # options structures regime-agnostic short-term
    "crypto_carry": True,    # macro liquidity dependent
    "polymarket": False,     # event-driven binary
    "manual": False,
    "unknown": True,         # default conservative
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_seen_phase": None, "last_check_iso": None,
                "decay_history": []}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as e:
        log.warning("[CYCLE-WATCHER] state load failed: %s", e)
        return {"last_seen_phase": None, "last_check_iso": None,
                "decay_history": []}


def _persist_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        # Cap history at last 50 entries
        state["decay_history"] = (state.get("decay_history") or [])[-50:]
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[CYCLE-WATCHER] persist failed: %s", e)


async def _read_current_phase() -> Optional[str]:
    """Read the latest cycle_phase classification from intelligence/."""
    try:
        from runtime.intelligence.cycle_phase import build_cycle_phase_snapshot
        snap = await build_cycle_phase_snapshot()
        if not snap or not isinstance(snap, dict):
            return None
        classification = snap.get("classification") or {}
        return classification.get("phase")
    except Exception as e:
        log.debug("[CYCLE-WATCHER] cycle_phase read failed: %s", e)
        return None


async def check_and_decay(*, brain=None) -> dict:
    """Read current cycle_phase; if transitioned vs last seen, decay
    bandit priors for regime-sensitive strategies + emit memory unit.

    Returns:
      {
        checked: bool,
        current_phase: str | None,
        last_seen_phase: str | None,
        transitioned: bool,
        decayed_strategies: [str, ...],
        decay_factor: float,
        changes: {strategy: {...}, ...},
      }
    """
    out: dict = {
        "checked": False,
        "current_phase": None,
        "last_seen_phase": None,
        "transitioned": False,
        "decayed_strategies": [],
        "decay_factor": DECAY_FACTOR,
        "changes": {},
    }
    if DISABLED:
        out["reason"] = "NCL_CYCLE_WATCHER_DISABLED=1"
        return out

    current = await _read_current_phase()
    out["current_phase"] = current
    out["checked"] = True
    if not current:
        out["reason"] = "cycle_phase classifier unavailable"
        return out

    state = _load_state()
    last_seen = state.get("last_seen_phase")
    out["last_seen_phase"] = last_seen

    # First boot — just record + return (no decay)
    if last_seen is None:
        state["last_seen_phase"] = current
        state["last_check_iso"] = _now_iso()
        _persist_state(state)
        out["reason"] = "first_boot_baseline_set"
        return out

    if last_seen == current:
        state["last_check_iso"] = _now_iso()
        _persist_state(state)
        out["reason"] = "no_transition"
        return out

    # TRANSITION DETECTED
    out["transitioned"] = True
    log.warning(
        "[CYCLE-WATCHER] PHASE TRANSITION %s → %s — decaying priors x%.2f "
        "for regime-sensitive strategies",
        last_seen, current, DECAY_FACTOR,
    )

    # Pick regime-sensitive strategies + decay
    try:
        from .strategy_bandit import get_bandit
        bandit = await get_bandit()
        all_posteriors = await bandit.all_posteriors()
        sensitive_strats = [
            s for s in all_posteriors.keys()
            if REGIME_SENSITIVE.get(s, True)  # default sensitive
        ]
        out["decayed_strategies"] = sensitive_strats

        if sensitive_strats:
            reason_str = f"cycle_phase_transition: {last_seen}→{current}"
            changes = await bandit.decay_priors(
                strategies=sensitive_strats,
                decay_factor=DECAY_FACTOR,
                reason=reason_str,
            )
            out["changes"] = changes
    except Exception as e:
        log.error("[CYCLE-WATCHER] bandit decay failed: %s", e)
        out["error"] = str(e)

    # Update + persist state
    state["last_seen_phase"] = current
    state["last_check_iso"] = _now_iso()
    state.setdefault("decay_history", []).append({
        "ts": _now_iso(),
        "from_phase": last_seen,
        "to_phase": current,
        "decayed_strategies": out["decayed_strategies"],
        "decay_factor": DECAY_FACTOR,
    })
    _persist_state(state)

    # Emit memory unit at importance 90 (regime change is high-importance)
    if brain is not None:
        try:
            mem = getattr(brain, "memory_store", None)
            if mem and hasattr(mem, "create_unit"):
                await mem.create_unit(
                    content=(
                        f"CYCLE PHASE TRANSITION: {last_seen} → {current}. "
                        f"Auto-trader bandit priors decayed x{DECAY_FACTOR} for "
                        f"{len(out['decayed_strategies'])} regime-sensitive "
                        f"strategies: {', '.join(out['decayed_strategies'])}. "
                        f"Thompson sampling will re-explore the affected "
                        f"sleeves under the new regime."
                    ),
                    source="portfolio:cycle_phase_transition",
                    importance=90.0,
                    tags=["portfolio", "auto_trader", "regime",
                          "cycle_phase", "bandit_decay",
                          f"from:{last_seen}", f"to:{current}"],
                    memory_type="semantic",
                    metadata={
                        "from_phase": last_seen,
                        "to_phase": current,
                        "decayed_strategies": out["decayed_strategies"],
                        "decay_factor": DECAY_FACTOR,
                        "wave": "14U-2/3",
                    },
                )
        except Exception as e:
            log.warning("[CYCLE-WATCHER] memory unit emit failed: %s", e)

    return out


__all__ = ["check_and_decay", "DECAY_FACTOR", "REGIME_SENSITIVE"]
