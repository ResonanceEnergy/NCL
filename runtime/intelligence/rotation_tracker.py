"""Wave 14I — Capital Rotation Tracker.

Daily snapshot of the 11 SPDR sector ETFs vs SPY benchmark:
  - relative price ratio + % change vs prior day
  - JdK RS-Ratio (4-week relative-strength ROC, normalized)
  - JdK RS-Momentum (1-week ROC of RS-Ratio)
  - 4-quadrant RRG classification (Leading / Improving / Weakening / Lagging)
  - sector breadth % (above 50-day SMA)

Persists to data/rotation/YYYY-MM-DD.json. Feeds into the morning brief
prep pack so the Macro Analyst and Chair see the regime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.intel.rotation_tracker")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
ROTATION_DIR = NCL_BASE / "data" / "rotation"

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rotation-")

# 11 SPDR sector ETFs + the SPY benchmark
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
}
BENCHMARK = "SPY"

# RS-Ratio / RS-Momentum windows. JdK defaults are 14 weeks on weekly bars;
# we use daily bars with 20d (≈4w) and 5d (≈1w) windows for tactical reads.
RS_RATIO_WINDOW = 20
RS_MOMENTUM_WINDOW = 5
SMA_WINDOW = 50


def _yf_history_blocking(symbol: str, period: str = "3mo") -> Optional[list[float]]:
    """Fetch daily closes for the symbol over the period."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period=period, interval="1d")
        if hist.empty:
            return None
        closes = hist["Close"].tolist()
        return [float(c) for c in closes if c == c]  # drop NaN
    except Exception as e:
        log.debug("yf history %s failed: %s", symbol, e)
        return None


async def _fetch_closes(symbol: str, period: str = "3mo") -> Optional[list[float]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _yf_history_blocking, symbol, period)


def _pct_change(closes: list[float], window: int) -> Optional[float]:
    """% change over the trailing `window` bars."""
    if not closes or len(closes) < window + 1:
        return None
    try:
        prev = closes[-window - 1]
        curr = closes[-1]
        if prev <= 0:
            return None
        return ((curr - prev) / prev) * 100.0
    except Exception:
        return None


def _above_sma(closes: list[float], window: int = SMA_WINDOW) -> Optional[bool]:
    """Is the latest close above the trailing SMA?"""
    if not closes or len(closes) < window:
        return None
    sma = sum(closes[-window:]) / window
    return closes[-1] > sma


def _compute_rs_metrics(
    sector_closes: list[float],
    bench_closes: list[float],
) -> dict:
    """Compute RS-Ratio + RS-Momentum + 4-quadrant classification.

    Returns dict with:
        ratio_pct_chg_20d   — sector vs benchmark % change over RS_RATIO_WINDOW days
        rs_momentum_5d      — change in the ratio over RS_MOMENTUM_WINDOW days
        quadrant            — Leading / Improving / Weakening / Lagging
        relative_strength   — current_ratio / max(ratio over window)
    """
    out: dict = {
        "ratio_pct_chg_20d": None,
        "rs_momentum_5d": None,
        "quadrant": None,
        "relative_strength": None,
    }
    if not sector_closes or not bench_closes:
        return out
    n = min(len(sector_closes), len(bench_closes))
    if n < RS_RATIO_WINDOW + RS_MOMENTUM_WINDOW + 1:
        return out
    # Align tails
    sc = sector_closes[-n:]
    bc = bench_closes[-n:]
    # Build daily ratio time series
    ratios = []
    for s, b in zip(sc, bc):
        if b > 0:
            ratios.append(s / b)
    if len(ratios) < RS_RATIO_WINDOW + RS_MOMENTUM_WINDOW + 1:
        return out
    # RS-Ratio proxy: ratio % change over 20d (positive → outperforming)
    out["ratio_pct_chg_20d"] = _pct_change(ratios, RS_RATIO_WINDOW)
    # RS-Momentum: 5d change in the ratio (positive → accelerating outperformance)
    out["rs_momentum_5d"] = _pct_change(ratios, RS_MOMENTUM_WINDOW)
    # Relative strength score: current ratio vs max over window
    window_max = max(ratios[-RS_RATIO_WINDOW:])
    if window_max > 0:
        out["relative_strength"] = round(ratios[-1] / window_max, 3)
    # 4-quadrant classification
    rs = out["ratio_pct_chg_20d"]
    mom = out["rs_momentum_5d"]
    if rs is None or mom is None:
        return out
    if rs > 0 and mom > 0:
        out["quadrant"] = "Leading"
    elif rs > 0 and mom <= 0:
        out["quadrant"] = "Weakening"
    elif rs <= 0 and mom > 0:
        out["quadrant"] = "Improving"
    else:
        out["quadrant"] = "Lagging"
    # Round
    if out["ratio_pct_chg_20d"] is not None:
        out["ratio_pct_chg_20d"] = round(out["ratio_pct_chg_20d"], 2)
    if out["rs_momentum_5d"] is not None:
        out["rs_momentum_5d"] = round(out["rs_momentum_5d"], 2)
    return out


async def build_rotation_snapshot() -> dict:
    """Compute full rotation snapshot: per-sector RS metrics + breadth."""
    started = time.time()
    today = date.today().isoformat()

    # Fetch benchmark first
    bench_closes = await _fetch_closes(BENCHMARK, period="6mo")
    if not bench_closes:
        log.warning("[rotation] benchmark fetch failed")
        return {"date": today, "error": "benchmark_unavailable"}

    # Fetch all sectors concurrently
    tasks = {sym: _fetch_closes(sym, period="6mo") for sym in SECTOR_ETFS}
    closes_by_sym = {}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for sym, res in zip(tasks.keys(), results):
        if isinstance(res, Exception):
            closes_by_sym[sym] = None
        else:
            closes_by_sym[sym] = res

    sectors_data: list[dict] = []
    breadth_above_sma = 0
    breadth_total = 0

    for sym, label in SECTOR_ETFS.items():
        closes = closes_by_sym.get(sym)
        if not closes:
            sectors_data.append({
                "symbol": sym, "label": label, "error": "no_data",
            })
            continue
        rs = _compute_rs_metrics(closes, bench_closes)
        sma_pass = _above_sma(closes, SMA_WINDOW)
        if sma_pass is not None:
            breadth_total += 1
            if sma_pass:
                breadth_above_sma += 1
        last = closes[-1]
        prev = closes[-2] if len(closes) > 1 else last
        day_chg = ((last - prev) / prev * 100.0) if prev > 0 else 0.0
        sectors_data.append({
            "symbol": sym,
            "label": label,
            "last": round(last, 2),
            "day_pct": round(day_chg, 2),
            "above_50d_sma": sma_pass,
            **rs,
        })

    # Breadth
    breadth_pct = round((breadth_above_sma / breadth_total) * 100.0, 1) if breadth_total else None

    # Sort sectors by RS-Ratio descending so Leading comes first
    sectors_data.sort(
        key=lambda s: (s.get("ratio_pct_chg_20d") or -999),
        reverse=True,
    )

    # Group by quadrant
    by_quadrant: dict[str, list[str]] = {
        "Leading": [], "Weakening": [], "Improving": [], "Lagging": [],
    }
    for s in sectors_data:
        q = s.get("quadrant")
        if q in by_quadrant:
            by_quadrant[q].append(s["symbol"])

    snapshot = {
        "date": today,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.time() - started, 1),
        "benchmark": BENCHMARK,
        "benchmark_last": round(bench_closes[-1], 2) if bench_closes else None,
        "breadth": {
            "sectors_above_50d_sma": breadth_above_sma,
            "sectors_evaluated": breadth_total,
            "pct": breadth_pct,
            "regime": (
                "broad_uptrend" if breadth_pct and breadth_pct >= 70
                else "narrow" if breadth_pct and breadth_pct <= 30
                else "neutral"
            ),
        },
        "by_quadrant": by_quadrant,
        "sectors": sectors_data,
        "leadership_summary": _summarize_leadership(by_quadrant, sectors_data),
    }

    # Persist
    ROTATION_DIR.mkdir(parents=True, exist_ok=True)
    path = ROTATION_DIR / f"{today}.json"
    try:
        path.write_text(json.dumps(snapshot, indent=2, default=str))
        log.info(
            "[rotation] wrote %s — Leading=%s, breadth=%s%%, elapsed=%.1fs",
            path, by_quadrant["Leading"], breadth_pct, snapshot["elapsed_s"],
        )
    except Exception as e:
        log.warning("[rotation] persist failed: %s", e)

    return snapshot


def _summarize_leadership(by_quadrant: dict, sectors: list[dict]) -> str:
    """One-line plain-text summary of who's leading + the cycle hint."""
    leading = by_quadrant.get("Leading") or []
    weakening = by_quadrant.get("Weakening") or []
    if not leading:
        return "No clear sector leadership — flat regime"
    # Cycle hint
    cyclical_leaders = {"XLI", "XLF", "XLY", "XLB"}
    defensive_leaders = {"XLP", "XLU", "XLV"}
    energy_leading = "XLE" in leading
    growth_leading = "XLK" in leading or "XLC" in leading
    cycle_hint = ""
    if any(t in leading for t in defensive_leaders) and not growth_leading:
        cycle_hint = " (late-cycle defensive bid)"
    elif any(t in leading for t in cyclical_leaders) and not energy_leading:
        cycle_hint = " (early/mid-cycle cyclical bid)"
    elif growth_leading and not any(t in leading for t in defensive_leaders):
        cycle_hint = " (growth/risk-on)"
    elif energy_leading and any(t in leading for t in defensive_leaders):
        cycle_hint = " (late-cycle commodity + defensive)"
    return f"Leading: {', '.join(leading)}{cycle_hint}"


def load_latest_rotation() -> Optional[dict]:
    """Return today's rotation snapshot if cached."""
    today = date.today().isoformat()
    path = ROTATION_DIR / f"{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


__all__ = [
    "build_rotation_snapshot",
    "load_latest_rotation",
    "SECTOR_ETFS",
    "ROTATION_DIR",
]
