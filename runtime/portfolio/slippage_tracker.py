"""
NCL Slippage Tracker — Wave 14J J7c

Per-fill slippage measurement. Records two reference prices around the
fill window:
  arrival     : quote at order-submit time
  benchmark   : VWAP over the fill window (or twap fallback)

Computes:
  arrival_slippage_bps = (fill - arrival) / arrival * 10000   (long)
                       = (arrival - fill) / arrival * 10000   (short)
  vwap_slippage_bps    = same vs benchmark

Positive bps = paid more (or sold lower) = adverse slippage = cost
Negative bps = price improvement (rare; means we filled better than quote)

Storage: data/portfolio/slippage.jsonl (append-only).

Per-strategy rollup: mean_arrival_bps, median_arrival_bps, p90_arrival_bps,
mean_vwap_bps, n_fills, total_notional_usd.

Operator records fills manually (or via future broker fill-handler);
trade_idea_id wires fills to the originating brief idea so per-idea
slippage feeds J1d expectancy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.slippage_tracker")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
SLIP_FILE = DATA_DIR / "slippage.jsonl"


@dataclass
class FillEntry:
    fill_id: str                       # operator-supplied or auto-generated
    timestamp_iso: str
    symbol: str
    side: str                          # buy / sell / buy_to_cover / sell_short
    qty: float
    fill_price: float
    arrival_price: Optional[float]     # quote at order submit
    vwap_benchmark_price: Optional[float]  # VWAP over fill window
    broker: Optional[str] = None
    strategy: Optional[str] = None
    trade_idea_id: Optional[str] = None
    arrival_slippage_bps: Optional[float] = None
    vwap_slippage_bps: Optional[float] = None
    notional_usd: float = 0.0
    notes: str = ""
    metadata: dict = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_arrival_bps(fill_price: float, arrival: Optional[float], side: str) -> Optional[float]:
    if arrival is None or arrival <= 0:
        return None
    s = side.lower()
    if s in ("buy", "buy_to_cover"):
        return ((fill_price - arrival) / arrival) * 10000.0
    if s in ("sell", "sell_short"):
        return ((arrival - fill_price) / arrival) * 10000.0
    return None


class SlippageTracker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._initialized = True

    async def record_fill(
        self,
        *,
        fill_id: str,
        symbol: str,
        side: str,
        qty: float,
        fill_price: float,
        arrival_price: Optional[float] = None,
        vwap_benchmark_price: Optional[float] = None,
        timestamp_iso: Optional[str] = None,
        broker: Optional[str] = None,
        strategy: Optional[str] = None,
        trade_idea_id: Optional[str] = None,
        notes: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        await self.initialize()
        arrival_bps = _compute_arrival_bps(fill_price, arrival_price, side)
        vwap_bps = _compute_arrival_bps(fill_price, vwap_benchmark_price, side)
        entry = FillEntry(
            fill_id=fill_id,
            timestamp_iso=timestamp_iso or _now(),
            symbol=symbol.upper(),
            side=side.lower(),
            qty=float(qty),
            fill_price=float(fill_price),
            arrival_price=arrival_price,
            vwap_benchmark_price=vwap_benchmark_price,
            broker=broker,
            strategy=strategy,
            trade_idea_id=trade_idea_id,
            arrival_slippage_bps=(
                round(arrival_bps, 3) if arrival_bps is not None else None
            ),
            vwap_slippage_bps=(
                round(vwap_bps, 3) if vwap_bps is not None else None
            ),
            notional_usd=round(abs(qty) * fill_price, 4),
            notes=notes,
            metadata=metadata or {},
        )
        async with self._lock:
            try:
                with open(SLIP_FILE, "a") as f:
                    f.write(json.dumps(asdict(entry)) + "\n")
            except Exception as e:
                log.error("[SLIP] append failed: %s", e)
        return asdict(entry)

    async def by_strategy(self, lookback_days: int = 90) -> dict:
        await self.initialize()
        if not SLIP_FILE.exists():
            return {}
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        by_strat: dict[str, list[FillEntry]] = {}
        try:
            with open(SLIP_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = row.get("timestamp_iso", "")
                    try:
                        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if ts_dt < cutoff:
                        continue
                    strat = row.get("strategy") or "unknown"
                    by_strat.setdefault(strat, []).append(row)
        except Exception as e:
            log.warning("[SLIP] read failed: %s", e)

        def _stats(rows: list[dict]) -> dict:
            n = len(rows)
            arrivals = [r["arrival_slippage_bps"] for r in rows
                        if r.get("arrival_slippage_bps") is not None]
            vwaps = [r["vwap_slippage_bps"] for r in rows
                     if r.get("vwap_slippage_bps") is not None]
            notional = sum(r.get("notional_usd", 0.0) for r in rows)
            out = {
                "n_fills": n,
                "total_notional_usd": round(notional, 2),
            }
            if arrivals:
                arr_sorted = sorted(arrivals)
                p90_idx = max(0, int(0.90 * len(arr_sorted)) - 1)
                out["arrival_mean_bps"] = round(statistics.mean(arrivals), 3)
                out["arrival_median_bps"] = round(statistics.median(arrivals), 3)
                out["arrival_p90_bps"] = round(arr_sorted[p90_idx], 3)
            if vwaps:
                vwap_sorted = sorted(vwaps)
                p90_idx = max(0, int(0.90 * len(vwap_sorted)) - 1)
                out["vwap_mean_bps"] = round(statistics.mean(vwaps), 3)
                out["vwap_median_bps"] = round(statistics.median(vwaps), 3)
                out["vwap_p90_bps"] = round(vwap_sorted[p90_idx], 3)
            return out

        out = {strat: _stats(rows) for strat, rows in by_strat.items()}
        # _all rollup
        all_rows = [r for group in by_strat.values() for r in group]
        if all_rows:
            out["_all"] = _stats(all_rows)
        return out


_SLIP: Optional[SlippageTracker] = None
_SLIP_LOCK = asyncio.Lock()


async def get_slippage_tracker() -> SlippageTracker:
    global _SLIP
    if _SLIP is not None:
        await _SLIP.initialize()
        return _SLIP
    async with _SLIP_LOCK:
        if _SLIP is None:
            _SLIP = SlippageTracker()
            await _SLIP.initialize()
    return _SLIP
