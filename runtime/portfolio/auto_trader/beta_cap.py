"""
Auto-Trader beta-adjusted exposure cap — Wave 14U-2/6

Computes rolling-60d beta to SPY per open position and gates new opens
when portfolio beta-adjusted net exposure exceeds ±50% NAV.

Catches the "5 longs all loaded on momentum factor" failure mode where
the operator THINKS positions are diversified but they all collapse
together when the market dumps.

Beta computation (per ticker):
  rolling-60d beta = cov(ticker_return, spy_return) / var(spy_return)

Beta-adjusted net = sum( position_notional × position_beta × sign )
  where sign = +1 for long, -1 for short

Cap: |beta_adjusted_net| ≤ NAV × NCL_BETA_ADJ_MAX_NET_PCT (default 50%)

Why this matters (Hudson & Thames / AQR canonical pattern):
  - Raw long/short net exposure misses that 5 names with beta=2.0 each
    is equivalent to 10× raw exposure when SPY moves.
  - Beta-adjusted exposure is THE institutional standard for measuring
    real market risk.
  - At retail scale ($36K NAV), the cap protects against momentum
    crowding (most retail growth stocks share a high SPY beta).

Cache:
  data/portfolio/auto_trader/beta_cache.json
    {ticker: {beta, computed_at_iso, sample_n}}
  TTL: 24 hours (beta is stable; daily refresh is plenty)

Tunables (env):
  NCL_BETA_ADJ_MAX_NET_PCT     default 50.0
  NCL_BETA_CACHE_TTL_HOURS     default 24
  NCL_BETA_LOOKBACK_DAYS       default 60
  NCL_BETA_CAP_DISABLED        "1"/"0"  default "0"
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.beta_cap")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
CACHE_FILE = NCL_BASE / "data" / "portfolio" / "auto_trader" / "beta_cache.json"

MAX_NET_PCT = float(os.getenv("NCL_BETA_ADJ_MAX_NET_PCT", "50.0"))
CACHE_TTL_HOURS = float(os.getenv("NCL_BETA_CACHE_TTL_HOURS", "24"))
LOOKBACK_DAYS = int(os.getenv("NCL_BETA_LOOKBACK_DAYS", "60"))
DISABLED = os.getenv("NCL_BETA_CAP_DISABLED", "0") == "1"

_CACHE: dict[str, dict] = {}
_LOCK = asyncio.Lock()
_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_s() -> float:
    return time.time()


def _load_cache() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not CACHE_FILE.exists():
        return
    try:
        raw = json.loads(CACHE_FILE.read_text())
        if isinstance(raw, dict):
            _CACHE.update(raw)
    except Exception as e:
        log.warning("[BETA-CAP] cache load failed: %s", e)


def _persist_cache() -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(_CACHE, indent=2, sort_keys=True))
        tmp.replace(CACHE_FILE)
    except Exception as e:
        log.error("[BETA-CAP] cache persist failed: %s", e)


def _is_cache_fresh(entry: dict) -> bool:
    cached_at = entry.get("cached_at_s") or 0
    return (_now_s() - cached_at) < (CACHE_TTL_HOURS * 3600)


def _compute_beta_blocking(ticker: str) -> Optional[dict]:
    """Pull 60d daily history for ticker + SPY, compute beta via
    cov(t, spy) / var(spy). Returns None on failure."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        # Pull period = LOOKBACK_DAYS + buffer for weekends/holidays
        period_days = LOOKBACK_DAYS + 30
        # SPY is the benchmark — pull both with same time window
        period_str = f"{period_days}d"
        t = yf.Ticker(ticker)
        spy = yf.Ticker("SPY")
        h_t = t.history(period=period_str)
        h_s = spy.history(period=period_str)
        if h_t.empty or h_s.empty:
            return None
        # Align indices (intersect dates)
        common = h_t.index.intersection(h_s.index)
        if len(common) < 20:  # Need at least 20 overlapping days
            return None
        t_closes = [float(h_t.loc[d, "Close"]) for d in common]
        s_closes = [float(h_s.loc[d, "Close"]) for d in common]
        # Compute daily returns
        t_rets = [(t_closes[i] / t_closes[i-1]) - 1 for i in range(1, len(t_closes))]
        s_rets = [(s_closes[i] / s_closes[i-1]) - 1 for i in range(1, len(s_closes))]
        n = len(t_rets)
        if n < 19:  # Need 19 returns
            return None
        # Cap to LOOKBACK_DAYS most recent returns
        t_rets = t_rets[-LOOKBACK_DAYS:]
        s_rets = s_rets[-LOOKBACK_DAYS:]
        n = len(t_rets)
        # cov / var
        mean_t = sum(t_rets) / n
        mean_s = sum(s_rets) / n
        cov_ts = sum((t_rets[i] - mean_t) * (s_rets[i] - mean_s)
                     for i in range(n)) / (n - 1)
        var_s = sum((s_rets[i] - mean_s) ** 2 for i in range(n)) / (n - 1)
        beta = cov_ts / var_s if var_s > 0 else 1.0
        return {
            "ticker": ticker,
            "beta": round(beta, 4),
            "sample_n": n,
            "cached_at_s": _now_s(),
            "cached_at_iso": _now_iso(),
        }
    except Exception as e:
        log.debug("[BETA-CAP] compute %s failed: %s", ticker, e)
        return None


async def _get_beta(ticker: str) -> float:
    """Get cached or freshly-computed beta for ticker. SPY always = 1.0."""
    sym = (ticker or "").upper().strip()
    if not sym:
        return 1.0
    if sym == "SPY":
        return 1.0
    async with _LOCK:
        _load_cache()
        entry = _CACHE.get(sym)
        if entry and _is_cache_fresh(entry):
            return float(entry.get("beta") or 1.0)
        # Compute fresh
        loop = asyncio.get_event_loop()
        fresh = await loop.run_in_executor(None, _compute_beta_blocking, sym)
        if fresh:
            _CACHE[sym] = fresh
            _persist_cache()
            return float(fresh["beta"])
        # Fallback: default beta = 1.0 if compute fails
        return 1.0


async def compute_portfolio_beta_net(
    *,
    open_positions: list[dict],
    proposed_ticker: Optional[str] = None,
    proposed_notional: float = 0.0,
    proposed_direction: str = "long",
    nav_cad: float = 0.0,
) -> dict:
    """Compute portfolio beta-adjusted net exposure.

    open_positions: list of {ticker, notional, direction} for currently
                    open positions.
    proposed_*: optionally include a proposed new position in the calc
                so callers can preview "would this open breach the cap?"
    nav_cad: current portfolio NAV in CAD (for the % cap check)

    Returns:
      {
        beta_adjusted_net: float (signed: + long-tilt, - short-tilt)
        beta_adjusted_long: float
        beta_adjusted_short: float
        nav: float
        cap_pct: float (configured cap)
        cap_dollars: float (cap × nav)
        net_pct_of_nav: float (current beta-adj net as % NAV)
        within_cap: bool
        breach_amount: float (how much over the cap, 0 if within)
        positions_with_beta: [{ticker, notional, direction, beta, beta_adj}]
      }
    """
    if DISABLED:
        return {"disabled": True, "within_cap": True}

    positions_with_beta: list[dict] = []
    long_sum = 0.0
    short_sum = 0.0

    # Existing positions
    for p in open_positions or []:
        ticker = str(p.get("ticker") or "").upper()
        notional = float(p.get("notional") or 0)
        direction = str(p.get("direction") or "long").lower()
        beta = await _get_beta(ticker)
        sign = 1.0 if direction == "long" else -1.0
        beta_adj = notional * beta * sign
        positions_with_beta.append({
            "ticker": ticker, "notional": round(notional, 2),
            "direction": direction, "beta": round(beta, 3),
            "beta_adj": round(beta_adj, 2),
        })
        if direction == "long":
            long_sum += notional * beta
        else:
            short_sum += notional * beta

    # Optional proposed position
    if proposed_ticker and proposed_notional > 0:
        beta = await _get_beta(proposed_ticker)
        sign = 1.0 if proposed_direction == "long" else -1.0
        beta_adj = float(proposed_notional) * beta * sign
        positions_with_beta.append({
            "ticker": str(proposed_ticker).upper(),
            "notional": round(float(proposed_notional), 2),
            "direction": proposed_direction,
            "beta": round(beta, 3),
            "beta_adj": round(beta_adj, 2),
            "proposed": True,
        })
        if proposed_direction == "long":
            long_sum += float(proposed_notional) * beta
        else:
            short_sum += float(proposed_notional) * beta

    beta_adj_net = long_sum - short_sum
    cap_dollars = float(nav_cad or 0) * (MAX_NET_PCT / 100.0)
    net_pct = (abs(beta_adj_net) / nav_cad * 100.0) if nav_cad > 0 else 0.0
    within = abs(beta_adj_net) <= cap_dollars
    breach = max(0.0, abs(beta_adj_net) - cap_dollars)

    return {
        "beta_adjusted_net": round(beta_adj_net, 2),
        "beta_adjusted_long": round(long_sum, 2),
        "beta_adjusted_short": round(short_sum, 2),
        "nav": round(float(nav_cad or 0), 2),
        "cap_pct": MAX_NET_PCT,
        "cap_dollars": round(cap_dollars, 2),
        "net_pct_of_nav": round(net_pct, 2),
        "within_cap": within,
        "breach_amount": round(breach, 2),
        "positions_with_beta": positions_with_beta,
    }


async def check_proposed_open_against_beta_cap(
    *,
    proposed_ticker: str,
    proposed_notional: float,
    proposed_direction: str = "long",
    open_positions: Optional[list[dict]] = None,
    nav_cad: float = 36000.0,
) -> dict:
    """Convenience gate: returns {allowed: bool, reason: str, ...details}.
    Use from loop.py before opening a new trade."""
    res = await compute_portfolio_beta_net(
        open_positions=open_positions or [],
        proposed_ticker=proposed_ticker,
        proposed_notional=proposed_notional,
        proposed_direction=proposed_direction,
        nav_cad=nav_cad,
    )
    if res.get("disabled"):
        return {"allowed": True, "disabled": True}
    if res.get("within_cap"):
        return {
            "allowed": True,
            "reason": (
                f"beta-adj net ${res['beta_adjusted_net']:.0f} within "
                f"cap ${res['cap_dollars']:.0f} ({MAX_NET_PCT:.0f}% NAV)"
            ),
            "details": res,
        }
    return {
        "allowed": False,
        "reason": (
            f"beta-adj net ${res['beta_adjusted_net']:.0f} would breach cap "
            f"${res['cap_dollars']:.0f} by ${res['breach_amount']:.0f} "
            f"({res['net_pct_of_nav']:.1f}% NAV vs {MAX_NET_PCT:.0f}% limit)"
        ),
        "details": res,
    }


__all__ = [
    "check_proposed_open_against_beta_cap",
    "compute_portfolio_beta_net",
    "MAX_NET_PCT",
]
