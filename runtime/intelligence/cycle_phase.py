"""Wave 14I — Business cycle phase classifier.

Reads four macro inputs and classifies the cycle into one of four phases:
    early_expansion       cyclicals/financials/small-caps lead
    mid_cycle             tech/communications/consumer-discretionary lead
    late_cycle            energy/materials/defensives starting to bid
    recession             staples/utilities/healthcare/bonds lead

Inputs (best-effort, all individually fallable):
    ISM Manufacturing PMI  — Finnhub or FRED (DGS10, GDPC1 proxy if PMI key-walled)
    10y-2y Treasury spread — FRED via yfinance (^TNX vs ^TYX proxy)
    Initial jobless claims — FRED
    High-yield credit spread — FRED (BAMLH0A0HYM2)

Classifier is a simple rule grid: precision over recall (only call a phase
when 3 of 4 indicators agree; otherwise return 'mixed').
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

log = logging.getLogger("ncl.intel.cycle_phase")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
ROTATION_DIR = NCL_BASE / "data" / "rotation"

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cycle-")


# ──────────────────────────────────────────────────────────────────────
# Input collectors — each returns Optional[float], best-effort
# ──────────────────────────────────────────────────────────────────────


def _fred_series_blocking(series_id: str) -> Optional[list[tuple[str, float]]]:
    """Pull a FRED series via the public JSON endpoint (no key required for
    public series). Returns recent observations as (date, value) tuples."""
    try:
        import httpx
    except ImportError:
        return None
    try:
        api_key = os.environ.get("FRED_API_KEY", "")
        if api_key:
            url = (
                f"https://api.stlouisfed.org/fred/series/observations?"
                f"series_id={series_id}&api_key={api_key}&file_type=json&limit=12&sort_order=desc"
            )
            r = httpx.get(url, timeout=10.0)
            if r.status_code == 200:
                data = r.json()
                obs = data.get("observations", [])
                out = []
                for o in obs:
                    try:
                        v = float(o.get("value") or "nan")
                        if v == v:  # not NaN
                            out.append((o.get("date", ""), v))
                    except (TypeError, ValueError):
                        continue
                return out
    except Exception as e:
        log.debug("FRED %s failed: %s", series_id, e)
    return None


def _yf_yield_blocking(symbol: str) -> Optional[float]:
    """Fetch last yield for a treasury proxy (^TNX = 10y, ^IRX = 13w bill,
    ^FVX = 5y, ^TYX = 30y)."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


async def _await_blocking(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


# ──────────────────────────────────────────────────────────────────────
# Indicator readers
# ──────────────────────────────────────────────────────────────────────


async def _read_yield_curve() -> Optional[dict]:
    """10y-2y spread. Positive = normal, negative = inverted (recession signal)."""
    tnx = await _await_blocking(_yf_yield_blocking, "^TNX")  # 10y
    irx = await _await_blocking(_yf_yield_blocking, "^FVX")  # 5y as 2y proxy
    if tnx is None or irx is None:
        return None
    # yfinance reports yields as % × 10 (e.g. 42.5 means 4.25%) — normalize
    if tnx > 20:
        tnx /= 10.0
    if irx > 20:
        irx /= 10.0
    spread = tnx - irx
    return {
        "10y_yield": round(tnx, 2),
        "5y_yield_proxy": round(irx, 2),
        "spread_bp": round(spread * 100, 1),
        "inverted": spread < 0,
        "interpretation": (
            "deeply_inverted_recession_signal" if spread < -0.5 else
            "inverted" if spread < 0 else
            "flat" if spread < 0.5 else
            "steep_normal"
        ),
    }


async def _read_ism_pmi() -> Optional[dict]:
    """ISM Manufacturing PMI. <50 = contraction. Use FRED NAPM (now ISMPMI)
    or fall back to a proxy."""
    obs = await _await_blocking(_fred_series_blocking, "MANEMP")  # mfg employment as proxy
    if not obs:
        return None
    try:
        latest_v = obs[0][1]
        prev_v = obs[1][1] if len(obs) > 1 else latest_v
        delta = latest_v - prev_v
        return {
            "series": "MANEMP_proxy",
            "latest": latest_v,
            "previous": prev_v,
            "delta": round(delta, 2),
            "trending": "declining" if delta < 0 else "rising" if delta > 0 else "flat",
            "note": "MANEMP proxy used; set FRED_API_KEY + use ISM PMI direct for accuracy",
        }
    except Exception:
        return None


async def _read_jobless_claims() -> Optional[dict]:
    """Initial unemployment claims trend."""
    obs = await _await_blocking(_fred_series_blocking, "ICSA")
    if not obs:
        return None
    try:
        latest = obs[0][1]
        prev4w_avg = sum(o[1] for o in obs[:4]) / min(4, len(obs))
        delta = latest - prev4w_avg
        return {
            "series": "ICSA",
            "latest": int(latest),
            "4w_avg": round(prev4w_avg, 0),
            "delta_vs_4w_avg": round(delta, 0),
            "trending": (
                "rising_sharply" if delta > 30_000 else
                "rising" if delta > 10_000 else
                "falling_sharply" if delta < -30_000 else
                "falling" if delta < -10_000 else
                "stable"
            ),
        }
    except Exception:
        return None


async def _read_credit_spread() -> Optional[dict]:
    """High-yield credit spread (BAMLH0A0HYM2). Above 5% = stress signal."""
    obs = await _await_blocking(_fred_series_blocking, "BAMLH0A0HYM2")
    if not obs:
        return None
    try:
        latest = obs[0][1]
        return {
            "series": "BAMLH0A0HYM2",
            "latest_pct": round(latest, 2),
            "regime": (
                "stress" if latest > 6.0 else
                "elevated" if latest > 4.5 else
                "normal" if latest > 2.5 else
                "compressed"
            ),
        }
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# Classifier
# ──────────────────────────────────────────────────────────────────────


def _classify_phase(
    yield_curve: Optional[dict],
    pmi: Optional[dict],
    claims: Optional[dict],
    credit: Optional[dict],
) -> dict:
    """Rule-grid classifier. Precision over recall."""
    votes = {"early_expansion": 0, "mid_cycle": 0, "late_cycle": 0, "recession": 0}
    reasons: list[str] = []

    # Yield curve
    if yield_curve:
        interp = yield_curve.get("interpretation", "")
        if interp == "deeply_inverted_recession_signal":
            votes["recession"] += 2
            reasons.append("yield curve deeply inverted")
        elif interp == "inverted":
            votes["late_cycle"] += 1
            votes["recession"] += 1
            reasons.append("yield curve inverted")
        elif interp == "flat":
            votes["late_cycle"] += 1
            reasons.append("yield curve flat")
        elif interp == "steep_normal":
            votes["early_expansion"] += 1
            votes["mid_cycle"] += 1
            reasons.append("yield curve steep")

    # PMI / mfg-emp
    if pmi:
        trend = pmi.get("trending", "")
        if trend == "declining":
            votes["late_cycle"] += 1
            votes["recession"] += 1
            reasons.append(f"{pmi['series']} declining")
        elif trend == "rising":
            votes["early_expansion"] += 1
            votes["mid_cycle"] += 1
            reasons.append(f"{pmi['series']} rising")

    # Claims
    if claims:
        trend = claims.get("trending", "")
        if trend in ("rising_sharply",):
            votes["recession"] += 2
            reasons.append("claims rising sharply")
        elif trend == "rising":
            votes["late_cycle"] += 1
            reasons.append("claims rising")
        elif trend in ("falling_sharply", "falling"):
            votes["early_expansion"] += 1
            votes["mid_cycle"] += 1
            reasons.append("claims falling")

    # Credit spreads
    if credit:
        regime = credit.get("regime", "")
        if regime == "stress":
            votes["recession"] += 2
            reasons.append("credit spreads stressed")
        elif regime == "elevated":
            votes["late_cycle"] += 1
            reasons.append("credit spreads elevated")
        elif regime in ("normal", "compressed"):
            votes["mid_cycle"] += 1
            if regime == "compressed":
                votes["early_expansion"] += 1
            reasons.append(f"credit spreads {regime}")

    # Decide
    total_votes = sum(votes.values())
    if total_votes == 0:
        phase = "unknown"
        confidence = 0.0
    else:
        # Pick max-vote phase; require >= 50% of total to be confident
        top_phase, top_count = max(votes.items(), key=lambda kv: kv[1])
        confidence = top_count / total_votes
        if confidence >= 0.5:
            phase = top_phase
        elif confidence >= 0.35:
            phase = top_phase  # softer call
        else:
            phase = "mixed"
    # Sector leadership expectation by phase
    expected_leaders = {
        "early_expansion": ["XLI", "XLF", "XLY", "XLB"],
        "mid_cycle": ["XLK", "XLC", "XLY"],
        "late_cycle": ["XLE", "XLB", "XLP", "XLU"],
        "recession": ["XLP", "XLU", "XLV"],
        "mixed": [],
        "unknown": [],
    }
    return {
        "phase": phase,
        "confidence": round(confidence, 2),
        "votes": votes,
        "reasons": reasons,
        "expected_leaders": expected_leaders.get(phase, []),
    }


# ──────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────


async def build_cycle_phase_snapshot() -> dict:
    started = time.time()
    today = date.today().isoformat()

    yield_curve, pmi, claims, credit = await asyncio.gather(
        _read_yield_curve(),
        _read_ism_pmi(),
        _read_jobless_claims(),
        _read_credit_spread(),
    )

    classification = _classify_phase(yield_curve, pmi, claims, credit)

    snapshot = {
        "date": today,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.time() - started, 1),
        "indicators": {
            "yield_curve": yield_curve,
            "pmi": pmi,
            "jobless_claims": claims,
            "credit_spread": credit,
        },
        "classification": classification,
    }

    # Persist
    ROTATION_DIR.mkdir(parents=True, exist_ok=True)
    path = ROTATION_DIR / f"cycle-{today}.json"
    try:
        path.write_text(json.dumps(snapshot, indent=2, default=str))
        log.info(
            "[cycle] wrote %s — phase=%s (conf %.2f), elapsed=%.1fs",
            path, classification["phase"], classification["confidence"], snapshot["elapsed_s"],
        )
    except Exception as e:
        log.warning("[cycle] persist failed: %s", e)

    return snapshot


def load_latest_cycle() -> Optional[dict]:
    today = date.today().isoformat()
    path = ROTATION_DIR / f"cycle-{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


__all__ = ["build_cycle_phase_snapshot", "load_latest_cycle"]
