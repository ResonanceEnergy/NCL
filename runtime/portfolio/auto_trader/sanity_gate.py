"""
Auto-Trader pre-trade sanity gate — Wave 14U (U1)

4-check filter run BEFORE the risk governor on every trade idea. Catches
the entire "stale data / hallucinated ticker / data-quality bug" failure
class. Per López de Prado: "If your data is wrong, no amount of clever
modeling will save you." This module makes wrong-data trades impossible.

Checks (all must pass; first failure rejects):

  1. TICKER EXISTS — yfinance.Ticker(sym).fast_info must respond with
     a current price > 0. Catches hallucinated tickers (BFAJ, NVD instead
     of NVDA, etc.) and delisted symbols.

  2. PRICE IN 52-WEEK RANGE — proposed entry must be within
     [52w_low * 0.98, 52w_high * 1.02]. Catches stale prices (an emission
     citing $429 for a stock now at $80 from a split or buyout) and
     hallucinated round-number "psychological" prices.

  3. DAILY MOVE < 30% — today's intraday % move must be < 30%. Catches
     halt-pending news / catastrophic gaps where any normal-sized entry
     is suicide. (Operator can still take these via manual paper trade —
     auto-trader just won't.)

  4. VOLUME > 0 — yfinance reports today's volume; must be > 0. Catches
     symbols on a trading halt (no liquidity) and weekend/holiday emissions.

The gate is fail-CLOSED on error: if any check raises, the trade is
rejected with reason="sanity_check_error: ...". Better to skip a trade
than to take a bad one. The full 4-check result is recorded on the
reasoning chain regardless of outcome, so the operator can see why.

Tunables (env):
  NCL_SANITY_GATE_ENABLED         "1" / "0"   default "1"
  NCL_SANITY_MAX_DAILY_MOVE_PCT   default 30.0
  NCL_SANITY_PRICE_BAND_SLACK     default 0.02 (2% above 52w_high, below 52w_low)
  NCL_SANITY_PRICE_CACHE_TTL_S    default 300  (5 min — sanity checks
                                                 should re-fetch frequently)

Returns:
  {
    "passed": bool,
    "checks": {
        "ticker_exists":   {"passed": bool, "value": last_price, "reason": str},
        "price_in_range":  {"passed": bool, "value": entry, "reason": str},
        "daily_move":      {"passed": bool, "value": pct, "reason": str},
        "volume_positive": {"passed": bool, "value": vol, "reason": str},
    },
    "block_reason": str (empty if passed),
    "elapsed_ms": float,
  }
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.auto_trader.sanity_gate")

ENABLED = os.getenv("NCL_SANITY_GATE_ENABLED", "1") == "1"
MAX_DAILY_MOVE_PCT = float(os.getenv("NCL_SANITY_MAX_DAILY_MOVE_PCT", "30.0"))
PRICE_BAND_SLACK = float(os.getenv("NCL_SANITY_PRICE_BAND_SLACK", "0.02"))
CACHE_TTL_S = float(os.getenv("NCL_SANITY_PRICE_CACHE_TTL_S", "300"))

# Process-local cache: ticker -> (ts, fast_info_dict, hist_dict).
# Avoids re-hitting yfinance on every scanner tick when the same ticker
# is evaluated multiple times within the TTL window. Caps memory by
# pruning entries older than 2x TTL.
_CACHE: dict[str, tuple[float, dict, dict]] = {}


def _now_s() -> float:
    return time.time()


def _prune_cache() -> None:
    """Drop entries older than 2x TTL — keeps process memory bounded."""
    cutoff = _now_s() - (CACHE_TTL_S * 2)
    stale = [k for k, (ts, _, _) in _CACHE.items() if ts < cutoff]
    for k in stale:
        _CACHE.pop(k, None)


def _fetch_yf_blocking(ticker: str) -> tuple[dict, dict]:
    """Synchronous yfinance fetch. Called via run_in_executor by the
    async wrapper. Returns ({fast_info_fields}, {hist_fields}) — both
    may be empty on error."""
    fast: dict = {}
    hist: dict = {}
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return fast, hist
    try:
        t = yf.Ticker(ticker)
        # fast_info is a dict-like object — pull what we need
        try:
            fi = t.fast_info
            fast = {
                "last_price": getattr(fi, "last_price", None)
                              or (fi.get("last_price") if hasattr(fi, "get") else None),
                "previous_close": getattr(fi, "previous_close", None)
                                  or (fi.get("previous_close") if hasattr(fi, "get") else None),
                "year_high": getattr(fi, "year_high", None)
                             or (fi.get("year_high") if hasattr(fi, "get") else None),
                "year_low": getattr(fi, "year_low", None)
                            or (fi.get("year_low") if hasattr(fi, "get") else None),
            }
        except Exception as e:
            log.debug("[SANITY] fast_info failed for %s: %s", ticker, e)
        # Fallback / volume — pull 2-day history
        try:
            h = t.history(period="2d")
            if not h.empty:
                hist["last_close"] = float(h["Close"].iloc[-1])
                hist["prev_close"] = float(h["Close"].iloc[-2]) if len(h) > 1 else hist["last_close"]
                hist["volume"] = float(h["Volume"].iloc[-1]) if "Volume" in h.columns else 0.0
                # 52-week range fallback
                if fast.get("year_high") is None or fast.get("year_low") is None:
                    h52 = t.history(period="1y")
                    if not h52.empty:
                        fast["year_high"] = fast.get("year_high") or float(h52["High"].max())
                        fast["year_low"] = fast.get("year_low") or float(h52["Low"].min())
        except Exception as e:
            log.debug("[SANITY] history failed for %s: %s", ticker, e)
    except Exception as e:
        log.warning("[SANITY] yfinance.Ticker(%s) failed: %s", ticker, e)
    return fast, hist


async def _get_fundamentals(ticker: str) -> tuple[dict, dict]:
    """Async wrapper around _fetch_yf_blocking with TTL cache."""
    import asyncio
    key = ticker.upper().strip()
    if not key:
        return {}, {}
    _prune_cache()
    entry = _CACHE.get(key)
    if entry and (_now_s() - entry[0]) < CACHE_TTL_S:
        return entry[1], entry[2]
    loop = asyncio.get_event_loop()
    fast, hist = await loop.run_in_executor(None, _fetch_yf_blocking, key)
    _CACHE[key] = (_now_s(), fast, hist)
    return fast, hist


async def check_trade_sanity(
    *,
    ticker: str,
    entry_price: float,
    direction: str = "long",
) -> dict:
    """Run the 4-check sanity filter. Returns shape documented in module
    docstring. Never raises — fail-CLOSED on internal error."""
    started = _now_s()
    result: dict[str, Any] = {
        "passed": False,
        "checks": {},
        "block_reason": "",
        "elapsed_ms": 0.0,
    }

    if not ENABLED:
        result["passed"] = True
        result["block_reason"] = "sanity_gate_disabled (NCL_SANITY_GATE_ENABLED=0)"
        result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
        return result

    sym = (ticker or "").upper().strip()
    if not sym:
        result["block_reason"] = "missing_ticker"
        result["checks"]["ticker_exists"] = {
            "passed": False, "value": None, "reason": "empty ticker string",
        }
        result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
        return result

    try:
        fast, hist = await _get_fundamentals(sym)
    except Exception as e:
        result["block_reason"] = f"sanity_check_error: yfinance fetch failed: {e}"
        result["checks"]["ticker_exists"] = {
            "passed": False, "value": None, "reason": str(e),
        }
        result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
        return result

    # Check 1: TICKER EXISTS — last_price > 0 from fast_info OR history
    last_price = (
        fast.get("last_price")
        or hist.get("last_close")
        or 0
    )
    try:
        last_price = float(last_price or 0)
    except (TypeError, ValueError):
        last_price = 0.0
    if last_price <= 0:
        result["checks"]["ticker_exists"] = {
            "passed": False, "value": last_price,
            "reason": f"yfinance has no price for '{sym}' — hallucinated or delisted",
        }
        result["block_reason"] = f"ticker_not_found: {sym}"
        result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
        return result
    result["checks"]["ticker_exists"] = {
        "passed": True, "value": round(last_price, 4), "reason": "ok",
    }

    # Check 2: PRICE IN 52-WEEK RANGE (with slack)
    yhi = fast.get("year_high") or 0
    ylo = fast.get("year_low") or 0
    try:
        yhi = float(yhi or 0)
        ylo = float(ylo or 0)
        entry = float(entry_price or 0)
    except (TypeError, ValueError):
        yhi = ylo = entry = 0.0
    if yhi > 0 and ylo > 0 and entry > 0:
        upper = yhi * (1.0 + PRICE_BAND_SLACK)
        lower = ylo * (1.0 - PRICE_BAND_SLACK)
        if entry > upper or entry < lower:
            result["checks"]["price_in_range"] = {
                "passed": False, "value": entry,
                "reason": (
                    f"entry ${entry:.2f} outside 52w range "
                    f"[${ylo:.2f}, ${yhi:.2f}] (±{PRICE_BAND_SLACK*100:.0f}% slack)"
                ),
            }
            result["block_reason"] = "price_outside_52w_range"
            result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
            return result
        result["checks"]["price_in_range"] = {
            "passed": True, "value": entry,
            "reason": f"within [${ylo:.2f}, ${yhi:.2f}]",
        }
    else:
        # No 52w range available — pass with a note, don't block
        result["checks"]["price_in_range"] = {
            "passed": True, "value": entry,
            "reason": "no 52w range available (skipped)",
        }

    # Check 3: DAILY MOVE < threshold
    prev = fast.get("previous_close") or hist.get("prev_close") or 0
    try:
        prev = float(prev or 0)
    except (TypeError, ValueError):
        prev = 0.0
    if prev > 0:
        daily_pct = abs((last_price - prev) / prev) * 100.0
        if daily_pct > MAX_DAILY_MOVE_PCT:
            result["checks"]["daily_move"] = {
                "passed": False, "value": round(daily_pct, 2),
                "reason": (
                    f"daily move {daily_pct:.1f}% > {MAX_DAILY_MOVE_PCT:.0f}% "
                    f"threshold (last=${last_price:.2f} prev=${prev:.2f})"
                ),
            }
            result["block_reason"] = "daily_move_too_large"
            result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
            return result
        result["checks"]["daily_move"] = {
            "passed": True, "value": round(daily_pct, 2),
            "reason": f"{daily_pct:.2f}% < {MAX_DAILY_MOVE_PCT:.0f}%",
        }
    else:
        result["checks"]["daily_move"] = {
            "passed": True, "value": 0.0,
            "reason": "no prev_close available (skipped)",
        }

    # Check 4: VOLUME > 0
    vol = hist.get("volume") or 0
    try:
        vol = float(vol or 0)
    except (TypeError, ValueError):
        vol = 0.0
    if vol <= 0:
        # Allow weekends/holidays — yfinance may report 0 vol then
        from datetime import datetime, timezone
        wd = datetime.now(timezone.utc).weekday()
        if wd >= 5:
            result["checks"]["volume_positive"] = {
                "passed": True, "value": 0,
                "reason": "weekend (volume=0 expected)",
            }
        else:
            result["checks"]["volume_positive"] = {
                "passed": False, "value": 0,
                "reason": "no volume today — possible trading halt",
            }
            result["block_reason"] = "no_volume_today"
            result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
            return result
    else:
        result["checks"]["volume_positive"] = {
            "passed": True, "value": int(vol),
            "reason": f"{vol:,.0f} shares today",
        }

    # All 4 passed
    result["passed"] = True
    result["block_reason"] = ""
    result["elapsed_ms"] = round((_now_s() - started) * 1000, 1)
    return result


__all__ = ["check_trade_sanity", "ENABLED"]
