"""
NCL Portfolio Telemetry — Wave 14J Phase 7 (J7b + J7d)

J7a (closed-loop outcome tracking) already lives in trade_idea_tracker.py
from Phase 2. This module adds:

  J7b — Risk-adjusted return scorecard
        Sharpe, Sortino, Calmar, Recovery Factor from the snapshots.jsonl
        NAV series. The audit doc called out that the Brain emits
        qualitative narrative but no quantitative scorecard — fixed.

  J7d — Target-weight drift alerts
        Operator configures target weights per asset class / per
        broker. Daily scan: deviation > tolerance band emits a
        rebalance suggestion. Opportunistic threshold-rebalance beats
        calendar rebalance per Kitces/FA-Mag research.

Reads from data/portfolio/snapshots.jsonl (J0c uses this too).
Target weights persist to data/portfolio/target_weights.json.
"""

from __future__ import annotations

import json
import logging
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.telemetry")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
SNAP_FILE = DATA_DIR / "snapshots.jsonl"
WEIGHTS_FILE = DATA_DIR / "target_weights.json"

RISK_FREE_RATE_ANNUAL = float(os.getenv("NCL_RISK_FREE_RATE", "0.045"))  # 4.5%
TRADING_DAYS = 252
DEFAULT_DRIFT_TOLERANCE_PCT = float(os.getenv("NCL_DRIFT_TOLERANCE_PCT", "5.0"))


# ── J7b: Risk-adjusted return computation ─────────────────────────

def _load_nav_series(lookback_days: int = 365) -> list[tuple[str, float]]:
    """Read snapshots.jsonl tail. Returns [(date, nav_cad), ...] sorted asc."""
    if not SNAP_FILE.exists():
        return []
    out = []
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
                date = row.get("date")
                if not date:
                    continue
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
                if nav_f > 0:
                    out.append((date, nav_f))
    except Exception as e:
        log.warning("[TELEMETRY] snap read failed: %s", e)
    out.sort(key=lambda x: x[0])
    return out[-lookback_days:]


def _daily_returns(series: list[tuple[str, float]]) -> list[float]:
    """Compute simple daily returns r_t = (nav_t / nav_{t-1}) - 1."""
    rets = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        cur = series[i][1]
        if prev > 0:
            rets.append((cur / prev) - 1.0)
    return rets


def risk_adjusted_returns(lookback_days: int = 365) -> dict:
    """Compute Sharpe / Sortino / Calmar / Recovery Factor + max DD.

    All metrics annualized (sqrt(252) scaling for stdev where appropriate).
    Returns:
      {
        "lookback_days": int,
        "sample_count": int,            # actual days in window
        "total_return_pct": float,
        "cagr_pct": float,
        "stdev_annual_pct": float,
        "downside_dev_annual_pct": float,
        "sharpe": float,
        "sortino": float,
        "calmar": float,
        "recovery_factor": float,
        "max_drawdown_pct": float,
        "current_drawdown_pct": float,
        "peak_nav_cad": float,
        "trough_nav_cad": float,
        "as_of": iso
      }
    """
    series = _load_nav_series(lookback_days)
    if len(series) < 2:
        return {
            "lookback_days": lookback_days,
            "sample_count": len(series),
            "note": "insufficient data — need >= 2 daily snapshots",
        }
    rets = _daily_returns(series)
    if not rets:
        return {
            "lookback_days": lookback_days,
            "sample_count": len(series),
            "note": "no usable return periods",
        }
    n = len(rets)
    rf_daily = (1 + RISK_FREE_RATE_ANNUAL) ** (1 / TRADING_DAYS) - 1
    excess = [r - rf_daily for r in rets]
    mean_excess = statistics.mean(excess)
    stdev_daily = statistics.pstdev(rets) if n > 1 else 0.0
    downside = [r for r in rets if r < 0]
    downside_std = statistics.pstdev(downside) if len(downside) > 1 else 0.0

    # Annualize
    stdev_annual = stdev_daily * math.sqrt(TRADING_DAYS)
    downside_annual = downside_std * math.sqrt(TRADING_DAYS)
    mean_annual_excess = mean_excess * TRADING_DAYS

    sharpe = mean_annual_excess / stdev_annual if stdev_annual > 0 else 0.0
    sortino = mean_annual_excess / downside_annual if downside_annual > 0 else 0.0

    # Total return + CAGR
    nav_start = series[0][1]
    nav_end = series[-1][1]
    total_return = (nav_end / nav_start) - 1.0
    days_span = (
        datetime.fromisoformat(series[-1][0]).date()
        - datetime.fromisoformat(series[0][0]).date()
    ).days
    years = max(days_span / 365.25, 1 / 365.25)
    cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else 0.0

    # Max drawdown
    peak = series[0][1]
    max_dd = 0.0
    peak_val = peak
    trough_val = peak
    for d, nav in series:
        if nav > peak:
            peak = nav
        dd = (nav - peak) / peak
        if dd < max_dd:
            max_dd = dd
            peak_val = peak
            trough_val = nav
    current_dd = (nav_end - peak) / peak if peak > 0 else 0.0

    calmar = abs(cagr / max_dd) if max_dd < 0 else 0.0
    recovery_factor = abs(total_return / max_dd) if max_dd < 0 else 0.0

    return {
        "lookback_days": lookback_days,
        "sample_count": len(series),
        "total_return_pct": round(total_return * 100, 4),
        "cagr_pct": round(cagr * 100, 4),
        "stdev_annual_pct": round(stdev_annual * 100, 4),
        "downside_dev_annual_pct": round(downside_annual * 100, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "recovery_factor": round(recovery_factor, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "current_drawdown_pct": round(current_dd * 100, 4),
        "peak_nav_cad": round(peak_val, 2),
        "trough_nav_cad": round(trough_val, 2),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


# ── J7d: Target-weight drift alerts ──────────────────────────────

def load_target_weights() -> dict:
    """Load operator-configured target weights from data/portfolio/target_weights.json.

    Shape:
      {
        "by_asset_class": {"equity": 60.0, "options": 10.0, "crypto": 5.0, "cash": 25.0},
        "by_broker": {"ibkr": 50.0, "moomoo": 30.0, "wealthsimple": 20.0},
        "tolerance_pct": 5.0
      }
    Missing file returns sensible defaults; weights normalized to sum 100.
    """
    if not WEIGHTS_FILE.exists():
        return {"by_asset_class": {}, "by_broker": {}, "tolerance_pct": DEFAULT_DRIFT_TOLERANCE_PCT}
    try:
        return json.loads(WEIGHTS_FILE.read_text())
    except Exception as e:
        log.warning("[TELEMETRY] target_weights read failed: %s", e)
        return {"by_asset_class": {}, "by_broker": {}, "tolerance_pct": DEFAULT_DRIFT_TOLERANCE_PCT}


def save_target_weights(payload: dict) -> dict:
    """Persist operator-set target weights. Returns the saved payload."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("tolerance_pct", DEFAULT_DRIFT_TOLERANCE_PCT)
    tmp = WEIGHTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(WEIGHTS_FILE)
    return payload


def drift_alerts(
    summary: dict,
    target: Optional[dict] = None,
) -> list[dict]:
    """Compare current portfolio allocation vs target weights, emit
    alerts where actual deviates from target by more than tolerance_pct.

    `summary` is the output of PortfolioManager.get_summary(); the key
    we need is `allocation` (dict of % by class + by broker).

    Returns sorted-by-deviation list of:
      {
        "scope": "asset_class" | "broker",
        "bucket": str,
        "actual_pct": float,
        "target_pct": float,
        "deviation_pct": float,         # signed
        "tolerance_pct": float,
        "action": str                    # "TRIM" | "ADD" | "AT-TARGET"
      }
    """
    target = target or load_target_weights()
    tol = float(target.get("tolerance_pct") or DEFAULT_DRIFT_TOLERANCE_PCT)

    out = []
    allocation = summary.get("allocation") or {}

    by_class_actual = allocation.get("by_asset_class") or {}
    by_class_target = target.get("by_asset_class") or {}
    for bucket, target_pct in by_class_target.items():
        actual = float(by_class_actual.get(bucket, 0.0))
        target_pct_f = float(target_pct)
        dev = actual - target_pct_f
        if abs(dev) >= tol:
            out.append({
                "scope": "asset_class",
                "bucket": bucket,
                "actual_pct": round(actual, 2),
                "target_pct": round(target_pct_f, 2),
                "deviation_pct": round(dev, 2),
                "tolerance_pct": tol,
                "action": "TRIM" if dev > 0 else "ADD",
            })

    by_broker_actual = allocation.get("by_broker") or {}
    by_broker_target = target.get("by_broker") or {}
    for bucket, target_pct in by_broker_target.items():
        actual = float(by_broker_actual.get(bucket, 0.0))
        target_pct_f = float(target_pct)
        dev = actual - target_pct_f
        if abs(dev) >= tol:
            out.append({
                "scope": "broker",
                "bucket": bucket,
                "actual_pct": round(actual, 2),
                "target_pct": round(target_pct_f, 2),
                "deviation_pct": round(dev, 2),
                "tolerance_pct": tol,
                "action": "TRIM" if dev > 0 else "ADD",
            })

    return sorted(out, key=lambda r: abs(r["deviation_pct"]), reverse=True)
