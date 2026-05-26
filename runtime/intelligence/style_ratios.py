"""Wave 14I — Style + market-cap rotation ratios.

Tracks the four cleanest regime gauges:
    IWM / SPY    — small-cap vs large-cap risk appetite
    IWD / IWF    — value vs growth tilt
    XLU / SPY    — defensive leadership signal
    RSP / SPY    — equal-weight vs cap-weight (mega-cap concentration check)
    ARKK / SPY   — speculative-risk appetite

Each ratio is logged with daily + 5-day + 20-day % changes so the Macro
Analyst can read the regime shift over multiple horizons.

Persists to data/rotation/style-YYYY-MM-DD.json alongside the sector
rotation snapshot.
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

log = logging.getLogger("ncl.intel.style_ratios")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
ROTATION_DIR = NCL_BASE / "data" / "rotation"

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="style-")

# (numerator, denominator, label, interpretation)
STYLE_RATIOS = [
    ("IWM", "SPY", "Small-cap vs Large-cap", "Rising = risk-on small-cap leadership"),
    ("IWD", "IWF", "Value vs Growth", "Rising = value rotation in play"),
    ("XLU", "SPY", "Defensive vs Market", "Rising = defensive bid (late-cycle/risk-off)"),
    ("RSP", "SPY", "Equal-weight vs Cap-weight", "Rising = broadening (mega-cap concentration easing)"),
    ("ARKK", "SPY", "Speculative vs Market", "Rising = speculative appetite (risk-on growth)"),
]


def _yf_closes_blocking(symbol: str, period: str = "3mo") -> Optional[list[float]]:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        hist = yf.Ticker(symbol).history(period=period, interval="1d")
        if hist.empty:
            return None
        return [float(c) for c in hist["Close"].tolist() if c == c]
    except Exception as e:
        log.debug("yf %s failed: %s", symbol, e)
        return None


async def _fetch_closes(symbol: str) -> Optional[list[float]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _yf_closes_blocking, symbol, "3mo")


def _pct_chg(values: list[float], window: int) -> Optional[float]:
    if not values or len(values) < window + 1:
        return None
    prev = values[-window - 1]
    curr = values[-1]
    if prev <= 0:
        return None
    return round(((curr - prev) / prev) * 100.0, 2)


def _ratio_series(num: list[float], den: list[float]) -> list[float]:
    n = min(len(num), len(den))
    if n == 0:
        return []
    out = []
    for s, b in zip(num[-n:], den[-n:]):
        if b > 0:
            out.append(s / b)
    return out


async def build_style_snapshot() -> dict:
    started = time.time()
    today = date.today().isoformat()

    # Collect every distinct symbol we need
    symbols = set()
    for n, d, *_ in STYLE_RATIOS:
        symbols.add(n)
        symbols.add(d)

    closes_by_sym = {}
    tasks = {s: _fetch_closes(s) for s in symbols}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for sym, res in zip(tasks.keys(), results):
        closes_by_sym[sym] = None if isinstance(res, Exception) else res

    ratios_out = []
    for num, den, label, interp in STYLE_RATIOS:
        nc = closes_by_sym.get(num)
        dc = closes_by_sym.get(den)
        if not nc or not dc:
            ratios_out.append({
                "ratio": f"{num}/{den}", "label": label,
                "error": "no_data",
            })
            continue
        series = _ratio_series(nc, dc)
        if len(series) < 25:
            ratios_out.append({
                "ratio": f"{num}/{den}", "label": label,
                "error": "insufficient_history",
            })
            continue
        d1 = _pct_chg(series, 1)
        d5 = _pct_chg(series, 5)
        d20 = _pct_chg(series, 20)
        # Direction tag
        if d5 is not None and d20 is not None:
            if d5 > 0.5 and d20 > 1.0:
                direction = "rotating_in"
            elif d5 < -0.5 and d20 < -1.0:
                direction = "rotating_out"
            elif d5 > 0.3 and d20 > 0:
                direction = "trending_up"
            elif d5 < -0.3 and d20 < 0:
                direction = "trending_down"
            else:
                direction = "neutral"
        else:
            direction = "unknown"
        ratios_out.append({
            "ratio": f"{num}/{den}",
            "label": label,
            "interpretation": interp,
            "last": round(series[-1], 4),
            "day_pct": d1,
            "5d_pct": d5,
            "20d_pct": d20,
            "direction": direction,
        })

    # Derive top-line regime read
    regime_signals: list[str] = []
    for r in ratios_out:
        if r.get("direction") in ("rotating_in", "trending_up"):
            regime_signals.append(f"{r['ratio']} rotating in (+{r.get('5d_pct')}% 5d)")
        elif r.get("direction") == "rotating_out":
            regime_signals.append(f"{r['ratio']} rotating out ({r.get('5d_pct')}% 5d)")

    snapshot = {
        "date": today,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.time() - started, 1),
        "ratios": ratios_out,
        "regime_signals": regime_signals,
    }

    # Persist
    ROTATION_DIR.mkdir(parents=True, exist_ok=True)
    path = ROTATION_DIR / f"style-{today}.json"
    try:
        path.write_text(json.dumps(snapshot, indent=2, default=str))
        log.info(
            "[style] wrote %s — %d active rotations, elapsed=%.1fs",
            path, len(regime_signals), snapshot["elapsed_s"],
        )
    except Exception as e:
        log.warning("[style] persist failed: %s", e)

    return snapshot


def load_latest_style() -> Optional[dict]:
    today = date.today().isoformat()
    path = ROTATION_DIR / f"style-{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


__all__ = ["build_style_snapshot", "load_latest_style", "STYLE_RATIOS"]
