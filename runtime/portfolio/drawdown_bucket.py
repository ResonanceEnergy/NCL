"""
NCL Drawdown Bucket — Wave 14J Phase 1 (J0c)

Single source of truth for the portfolio's current drawdown band. Read
by all autonomous loops + scanners + brief pipeline + paper trading
BEFORE proposing or executing any new sizing. The whole point of this
module is that the throttle is enforced in ONE place — adding a new
scanner doesn't require re-implementing drawdown logic.

Bands (computed from current portfolio NAV vs trailing peak):
  green     :  0%  to  -3%        sizing multiplier 1.00
  caution   : -3%  to  -7%        sizing multiplier 0.75
  warning   : -7%  to -12%        sizing multiplier 0.50
  halt      : worse than -12%     sizing multiplier 0.00

Drawdown reference is the trailing high-water-mark over the rolling
lookback window (default 90 days, matching the snapshots.jsonl
retention window). Operator can override the HWM manually (e.g. to
fence a known historical event) via the REST surface.

Behavior:
  - Loop ncl-drawdown-bucket runs every 60s
  - Reads PortfolioManager.get_summary() for current NAV (in CAD)
  - Replays the trailing 90 days of data/portfolio/snapshots.jsonl to
    find the peak NAV
  - Computes current drawdown_pct = (current - peak) / peak * 100
  - Maps to band → sizing_multiplier
  - Persists to data/health/drawdown.json
  - On band transition: emits portfolio:drawdown_band_change MemUnit
    at importance 95 (NATRIX tier) via the existing memory bridge

Public surface:
  - get_drawdown_state() -> DrawdownState        (singleton accessor)
  - get_sizing_multiplier() -> float             (cheap accessor for
                                                  hot-path callers — every
                                                  scanner can call this
                                                  every request without
                                                  worrying about cost)
  - drawdown_bucket_loop()                       (registered as
                                                  ncl-drawdown-bucket
                                                  scheduler task)

The compute is intentionally simple — no Calmar, no rolling Sortino,
no vol-targeting. Those are J7b telemetry concerns (Wave 14J Phase 7).
This is the throttle gate. Keep it boring and reliable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.drawdown_bucket")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
SNAP_FILE = NCL_BASE / "data" / "portfolio" / "snapshots.jsonl"
HEALTH_DIR = NCL_BASE / "data" / "health"
DRAWDOWN_FILE = HEALTH_DIR / "drawdown.json"


# Band thresholds + sizing multipliers.
# (max_dd_pct_inclusive, band_name, sizing_multiplier)
BANDS = [
    (-3.0, "green", 1.00),
    (-7.0, "caution", 0.75),
    (-12.0, "warning", 0.50),
    (-100.0, "halt", 0.00),  # worse than warning ceiling
]


def _classify(drawdown_pct: float) -> tuple[str, float]:
    """drawdown_pct is typically negative (e.g. -5.2). Returns (band, mult)."""
    for threshold, band, mult in BANDS:
        if drawdown_pct >= threshold:
            return band, mult
    return "halt", 0.0


@dataclass
class DrawdownState:
    """Snapshot of the current drawdown bucket state."""

    computed_at: str = ""
    current_nav_cad: float = 0.0
    peak_nav_cad: float = 0.0
    peak_date: Optional[str] = None
    drawdown_pct: float = 0.0
    band: str = "green"
    sizing_multiplier: float = 1.0
    lookback_days: int = 90
    sample_count: int = 0
    last_transition_at: Optional[str] = None
    last_transition_from: Optional[str] = None
    manual_peak_override: Optional[float] = None
    notes: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _peak_from_snapshots(lookback_days: int = 90) -> tuple[float, Optional[str], int]:
    """Replay snapshots.jsonl, find the max total_value_cad in the
    trailing N days.

    Returns (peak_nav_cad, peak_date_iso, sample_count). When the file
    doesn't exist or holds no usable entries, returns (0.0, None, 0).
    """
    if not SNAP_FILE.exists():
        return 0.0, None, 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    peak = 0.0
    peak_date: Optional[str] = None
    count = 0
    try:
        with open(SNAP_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                date = row.get("date") or row.get("snapshot_date")
                if not date:
                    continue
                if date < cutoff:
                    continue
                count += 1
                # Prefer CAD; fall back to USD * fx_rate; fall back to USD only.
                nav = row.get("total_value_cad")
                if nav is None or nav == 0:
                    usd = row.get("total_value_usd") or 0
                    fx = row.get("fx_rate_usd_cad") or row.get("fx_rate") or 1.0
                    try:
                        nav = float(usd) * float(fx)
                    except (TypeError, ValueError):
                        nav = 0
                try:
                    nav_f = float(nav or 0)
                except (TypeError, ValueError):
                    continue
                if nav_f > peak:
                    peak = nav_f
                    peak_date = date
    except Exception as e:
        log.warning("[DRAWDOWN] snapshot replay failed: %s", e)
    return peak, peak_date, count


class DrawdownBucket:
    """Singleton holding current drawdown state."""

    def __init__(self) -> None:
        self._state = DrawdownState()
        self._lock = asyncio.Lock()
        self._initialized: bool = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            HEALTH_DIR.mkdir(parents=True, exist_ok=True)
            await self._load_persisted()
            self._initialized = True

    async def _load_persisted(self) -> None:
        if not DRAWDOWN_FILE.exists():
            return
        try:
            payload = json.loads(DRAWDOWN_FILE.read_text())
            if not isinstance(payload, dict):
                return
            field_names = {f for f in DrawdownState.__dataclass_fields__}  # type: ignore[attr-defined]
            kept = {k: v for k, v in payload.items() if k in field_names}
            self._state = DrawdownState(**kept)
        except Exception as e:
            log.warning("[DRAWDOWN] failed to load persisted state: %s", e)

    async def _persist(self) -> None:
        try:
            DRAWDOWN_FILE.write_text(json.dumps(asdict(self._state), indent=2, sort_keys=True))
        except Exception as e:
            log.error("[DRAWDOWN] persist failed: %s", e)

    async def get_state(self) -> dict:
        await self.initialize()
        async with self._lock:
            return asdict(self._state)

    def sizing_multiplier(self) -> float:
        """Cheap synchronous accessor — readable by sizing math without
        awaiting. Returns the last computed multiplier; defaults to 1.0
        when the bucket hasn't computed yet (fail-open, NOT fail-closed,
        on cold start because halting sizing on boot is worse than
        running once at full size)."""
        return float(self._state.sizing_multiplier or 1.0)

    async def set_manual_peak(self, peak_cad: Optional[float], note: str = "") -> dict:
        """Operator override — pin the HWM to a known level (e.g.
        following a deliberate withdrawal or capital injection). Pass
        None to clear the override."""
        await self.initialize()
        async with self._lock:
            self._state.manual_peak_override = peak_cad if peak_cad is not None else None
            self._state.notes = note or ""
            await self._persist()
            return asdict(self._state)

    async def compute(self, current_nav_cad: float) -> dict:
        """Recompute drawdown from current NAV + snapshots peak.

        On band transition: stamps last_transition_at + last_transition_from.
        Emission of the portfolio:drawdown_band_change MemUnit lives in
        the loop wrapper below (so this function stays import-safe / no
        side-effects on brain or memory store).
        """
        await self.initialize()
        async with self._lock:
            peak, peak_date, count = _peak_from_snapshots(self._state.lookback_days)
            # Apply manual override if pinned.
            override = self._state.manual_peak_override
            if override is not None and override > 0:
                peak = float(override)
                peak_date = peak_date or "manual_override"
            # Treat the current value itself as a candidate HWM — if the
            # portfolio just hit a new high we don't want to report a
            # paper drawdown.
            if current_nav_cad and current_nav_cad > peak:
                peak = float(current_nav_cad)
                peak_date = _today()
            if peak <= 0:
                # Insufficient data — stay in green; sizing unchanged.
                self._state.computed_at = _now_iso()
                self._state.current_nav_cad = float(current_nav_cad or 0.0)
                self._state.peak_nav_cad = peak
                self._state.peak_date = peak_date
                self._state.sample_count = count
                self._state.drawdown_pct = 0.0
                self._state.band = "green"
                self._state.sizing_multiplier = 1.0
                await self._persist()
                return asdict(self._state)
            # NAV<100 guard — almost certainly a transient data-source
            # outage (broker adapter disconnected, FX fetch failed, etc).
            # Reporting a -100% drawdown and halting all trading on the
            # back of a single bad read is far worse than holding the
            # last-known good band. Just touch computed_at and bail.
            if (current_nav_cad or 0) < 100:
                log.warning(
                    "[DRAWDOWN] suspicious NAV $%.2f — holding band=%s "
                    "(peak=$%.2f); skipping band update",
                    current_nav_cad or 0, self._state.band, peak,
                )
                self._state.computed_at = _now_iso()
                self._state.peak_nav_cad = float(peak)
                self._state.peak_date = peak_date
                self._state.sample_count = count
                await self._persist()
                return asdict(self._state)
            dd_pct = ((current_nav_cad or 0.0) - peak) / peak * 100.0
            band, mult = _classify(dd_pct)
            prev_band = self._state.band
            if band != prev_band:
                self._state.last_transition_at = _now_iso()
                self._state.last_transition_from = prev_band
                log.warning(
                    "[DRAWDOWN] band transition %s -> %s (dd=%.2f%%, nav=$%.2f, peak=$%.2f @ %s)",
                    prev_band, band, dd_pct, current_nav_cad, peak, peak_date,
                )
            self._state.computed_at = _now_iso()
            self._state.current_nav_cad = float(current_nav_cad or 0.0)
            self._state.peak_nav_cad = float(peak)
            self._state.peak_date = peak_date
            self._state.sample_count = count
            self._state.drawdown_pct = round(dd_pct, 4)
            self._state.band = band
            self._state.sizing_multiplier = mult
            await self._persist()
            return asdict(self._state)


# ── Singleton ───────────────────────────────────────────────────────────

_BUCKET_SINGLETON: Optional[DrawdownBucket] = None
_BUCKET_LOCK = asyncio.Lock()


async def get_drawdown_bucket() -> DrawdownBucket:
    global _BUCKET_SINGLETON
    if _BUCKET_SINGLETON is not None:
        await _BUCKET_SINGLETON.initialize()
        return _BUCKET_SINGLETON
    async with _BUCKET_LOCK:
        if _BUCKET_SINGLETON is None:
            _BUCKET_SINGLETON = DrawdownBucket()
            await _BUCKET_SINGLETON.initialize()
    return _BUCKET_SINGLETON


async def get_drawdown_state() -> dict:
    bucket = await get_drawdown_bucket()
    return await bucket.get_state()


def get_sizing_multiplier_sync() -> float:
    """Cheap synchronous accessor for hot-path sizing math. Reads the
    in-process singleton's last computed multiplier; defaults to 1.0
    when uninitialized (fail-open on cold start)."""
    global _BUCKET_SINGLETON
    if _BUCKET_SINGLETON is None:
        return 1.0
    return _BUCKET_SINGLETON.sizing_multiplier()


# ── Autonomous loop ──────────────────────────────────────────────────

async def drawdown_bucket_loop(brain) -> None:
    """ncl-drawdown-bucket scheduler task.

    Every 60s: read current NAV from PortfolioManager.get_summary(),
    recompute the drawdown band, persist + emit band-transition events
    to memory bridge.

    `brain` is the NCL Brain instance — used to reach
    `brain.portfolio_manager` and `brain.memory_store` (best-effort).
    """
    log.info("[DRAWDOWN] loop started — 60s cadence")
    bucket = await get_drawdown_bucket()
    prev_band = (await bucket.get_state()).get("band", "green")

    while True:
        try:
            await asyncio.sleep(60)
            pm = getattr(brain, "portfolio_manager", None) or getattr(brain, "_portfolio_mgr", None)
            current_nav = 0.0
            if pm is not None:
                try:
                    summary = pm.get_summary("CAD")
                    current_nav = float(summary.get("total_value", 0) or 0)
                except Exception as e:
                    log.debug("[DRAWDOWN] get_summary failed (will retry): %s", e)
                    continue
            state = await bucket.compute(current_nav)
            new_band = state.get("band", "green")
            if new_band != prev_band:
                # Emit band transition as a MemUnit via the memory bridge.
                try:
                    mem_store = getattr(brain, "memory_store", None)
                    if mem_store is not None and hasattr(mem_store, "create_unit"):
                        await mem_store.create_unit(
                            content=(
                                f"Portfolio drawdown band transition: {prev_band} -> {new_band}. "
                                f"dd={state.get('drawdown_pct'):.2f}% nav=${state.get('current_nav_cad'):.2f} "
                                f"peak=${state.get('peak_nav_cad'):.2f} @ {state.get('peak_date')}"
                            ),
                            source="portfolio:drawdown_band_change",
                            importance=95.0,
                            tags=[
                                "portfolio",
                                "drawdown",
                                f"band:{new_band}",
                                f"from:{prev_band}",
                            ],
                            memory_type="episodic",
                            metadata={
                                "from_band": prev_band,
                                "to_band": new_band,
                                "sizing_multiplier": state.get("sizing_multiplier"),
                                "drawdown_pct": state.get("drawdown_pct"),
                                "wave": "14J-J0c",
                            },
                        )
                except Exception as e:
                    log.warning("[DRAWDOWN] memory emission failed (non-fatal): %s", e)
                prev_band = new_band
        except asyncio.CancelledError:
            log.info("[DRAWDOWN] loop cancelled")
            return
        except Exception as e:
            log.warning("[DRAWDOWN] loop tick error (will continue): %s", e)
            await asyncio.sleep(60)
