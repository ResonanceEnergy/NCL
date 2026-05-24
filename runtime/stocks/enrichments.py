"""Scanner enrichments — liquidity, earnings, IVR, options-flow, dark pool.

Shipped 2026-05-22 EOD as part of GOAT/BRAVO hardening (Features 4, 5, 6).

All helpers are *defensive* — they degrade to ``None`` when the underlying
data source is unavailable (no Finnhub key, no UW key, etc). The scanner
treats ``None`` as "data unknown, keep the symbol" for IVR/flow/dark-pool
checks. The hard gates that *exclude* a symbol (liquidity, earnings within
7d) are the only places where missing data leads to rejection.

External dependencies (all optional):
  - yfinance     for ADV/market-cap/IV fallback
  - httpx        for Finnhub + Unusual Whales REST calls
  - FINNHUB_API_KEY env var   → earnings calendar
  - UNUSUAL_WHALES_API_KEY env var → IVR + dark pool
  - data/intelligence/agent_signals.jsonl → cached UW flow (no API hit)

Singleton-ish caches are module-level dicts keyed by ticker + freshness
window. Scanner already caches OHLCV for 5 min; these caches piggyback the
same lifetime so a single scan cycle reuses one fetch per ticker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger("ncl.stocks.enrichments")

# Shared thread pool for blocking yfinance calls
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-enrich")

# ── Tunables ──────────────────────────────────────────────────────────────

GOAT_MIN_ADV = int(os.getenv("NCL_GOAT_MIN_ADV", "500000"))  # 500K shares
BRAVO_MIN_ADV = int(os.getenv("NCL_BRAVO_MIN_ADV", "250000"))  # 250K shares
MIN_MARKET_CAP_USD = float(os.getenv("NCL_MIN_MARKET_CAP", "1000000000"))  # $1B
MIN_OPTION_OI = int(os.getenv("NCL_MIN_OPTION_OI", "1000"))  # 1K contracts

EARNINGS_HORIZON_DAYS = int(os.getenv("NCL_EARNINGS_HORIZON_DAYS", "7"))
EARNINGS_REPORT_HORIZON_DAYS = 30  # only report days_to_earnings if ≤ 30

GOAT_IVR_MAX = float(os.getenv("NCL_GOAT_IVR_MAX", "70.0"))  # reject IVR > 70
BRAVO_IVR_MIN = float(os.getenv("NCL_BRAVO_IVR_MIN", "20.0"))  # reject IVR < 20

FLOW_LOOKBACK_HOURS = int(os.getenv("NCL_FLOW_LOOKBACK_HOURS", "24"))
FLOW_MIN_NET_CALL = float(os.getenv("NCL_FLOW_MIN_NET_CALL", "100000"))
FLOW_MIN_RATIO = float(os.getenv("NCL_FLOW_MIN_RATIO", "1.2"))

DARK_POOL_LOOKBACK_DAYS = 30


# ── Tiny cache (per-process, scan-cycle lifetime) ─────────────────────────


_TTL_S = 300  # 5 min — matches StockScanner OHLCV cache
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any:
    hit = _cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > _TTL_S:
        _cache.pop(key, None)
        return None
    return val


def _cache_set(key: str, val: Any) -> None:
    _cache[key] = (time.time(), val)


# ═══════════════════════════════════════════════════════════════════════════
# LIQUIDITY (Feature 4)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class LiquidityResult:
    pass_liquidity: bool
    avg_daily_volume: Optional[float]
    market_cap_usd: Optional[float]
    option_oi_total: Optional[int]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "liquidity_pass": bool(self.pass_liquidity),
            "avg_daily_volume": self.avg_daily_volume,
            "market_cap_usd": self.market_cap_usd,
            "option_oi_total": self.option_oi_total,
            "liquidity_reason": self.reason or None,
        }


def _yf_liquidity_blocking(ticker: str) -> Optional[dict[str, Any]]:
    """Blocking yfinance probe — runs in thread pool."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        info = getattr(t, "fast_info", None) or {}
        # fast_info returns a SafeNamespace; access .market_cap, .last_price.
        mcap = None
        try:
            mcap = float(info.get("market_cap") or info.get("marketCap") or 0)
        except Exception:
            mcap = None

        # Sum option open interest across all expirations (capped at 6 chains
        # for speed — that's >90% of real OI on most names).
        oi_total = None
        try:
            exps = list(t.options or [])[:6]
            running = 0
            for exp in exps:
                ch = t.option_chain(exp)
                if hasattr(ch, "calls") and hasattr(ch, "puts"):
                    running += int(ch.calls["openInterest"].fillna(0).sum())
                    running += int(ch.puts["openInterest"].fillna(0).sum())
            oi_total = running
        except Exception:
            oi_total = None

        return {
            "market_cap_usd": mcap if mcap and mcap > 0 else None,
            "option_oi_total": oi_total,
        }
    except Exception as e:
        log.debug("yfinance liquidity probe failed for %s: %s", ticker, e)
        return None


async def check_liquidity(
    ticker: str,
    avg_daily_volume: Optional[float],
    min_adv: int,
    *,
    require_options_oi: bool = True,
) -> LiquidityResult:
    """Check a symbol clears the liquidity bar.

    Parameters
    ----------
    ticker : str
        Symbol to probe.
    avg_daily_volume : float | None
        Pre-computed ADV-20 from the scanner's own OHLCV (cheap — already
        loaded). If supplied we skip a yfinance roundtrip for volume.
    min_adv : int
        GOAT uses 500K, BRAVO uses 250K.
    require_options_oi : bool
        Skip the option-OI probe for spot-only scans (faster).

    Returns LiquidityResult with reason string when the gate fails.
    """
    cache_key = f"liq:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        # Re-evaluate against the requested ADV threshold (cheap)
        adv = avg_daily_volume if avg_daily_volume is not None else cached.get("adv")
        return _evaluate_liquidity(
            adv=adv,
            mcap=cached.get("market_cap_usd"),
            oi=cached.get("option_oi_total"),
            min_adv=min_adv,
            require_options_oi=require_options_oi,
        )

    loop = asyncio.get_event_loop()
    fast = await loop.run_in_executor(_executor, _yf_liquidity_blocking, ticker)
    if fast is None:
        return LiquidityResult(
            pass_liquidity=False,
            avg_daily_volume=avg_daily_volume,
            market_cap_usd=None,
            option_oi_total=None,
            reason="liquidity_data_unavailable",
        )

    fast["adv"] = avg_daily_volume
    _cache_set(cache_key, fast)
    return _evaluate_liquidity(
        adv=avg_daily_volume,
        mcap=fast.get("market_cap_usd"),
        oi=fast.get("option_oi_total"),
        min_adv=min_adv,
        require_options_oi=require_options_oi,
    )


def _evaluate_liquidity(
    *,
    adv: Optional[float],
    mcap: Optional[float],
    oi: Optional[int],
    min_adv: int,
    require_options_oi: bool,
) -> LiquidityResult:
    reasons: list[str] = []
    if adv is None or adv <= 0:
        reasons.append("adv_unknown")
    elif adv < min_adv:
        reasons.append(f"adv_below_min({int(adv)}<{min_adv})")
    if mcap is None:
        reasons.append("mcap_unknown")
    elif mcap < MIN_MARKET_CAP_USD:
        reasons.append(f"mcap_below_min(${mcap:,.0f}<${MIN_MARKET_CAP_USD:,.0f})")
    if require_options_oi:
        if oi is None:
            reasons.append("option_oi_unknown")
        elif oi < MIN_OPTION_OI:
            reasons.append(f"option_oi_below_min({oi}<{MIN_OPTION_OI})")

    return LiquidityResult(
        pass_liquidity=not reasons,
        avg_daily_volume=adv,
        market_cap_usd=mcap,
        option_oi_total=oi,
        reason=",".join(reasons),
    )


# ═══════════════════════════════════════════════════════════════════════════
# EARNINGS CALENDAR (Feature 5)
# ═══════════════════════════════════════════════════════════════════════════


_EARNINGS_CACHE_KEY = "earnings:all"
_EARNINGS_CACHE_TTL_S = 6 * 3600  # 6 hours — earnings dates don't shift much


async def _fetch_finnhub_earnings(horizon_days: int = 35) -> Optional[dict[str, str]]:
    """Pull next-earnings dates for the next ``horizon_days`` from Finnhub.

    Returns ``{ticker: 'YYYY-MM-DD'}`` for the *earliest* upcoming date per
    ticker. Returns None when FINNHUB_API_KEY is unset (data unavailable).
    """
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        return None
    try:
        import httpx
    except ImportError:
        return None

    today = date.today()
    end = today + timedelta(days=horizon_days)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "token": api_key,
                },
            )
            if resp.status_code != 200:
                log.warning("Finnhub earnings API returned %d", resp.status_code)
                return None
            data = resp.json()
    except Exception as e:
        log.warning("Finnhub earnings fetch failed: %s", e)
        return None

    out: dict[str, str] = {}
    for row in (data or {}).get("earningsCalendar", []) or []:
        sym = (row.get("symbol") or "").upper().strip()
        d = (row.get("date") or "").strip()
        if not sym or not d:
            continue
        # Keep earliest date per symbol
        if sym not in out or d < out[sym]:
            out[sym] = d
    return out


async def get_earnings_map(force_refresh: bool = False) -> Optional[dict[str, str]]:
    """Cached batch earnings map. None when Finnhub unavailable."""
    if not force_refresh:
        cached = _cache_get(_EARNINGS_CACHE_KEY)
        if cached is not None:
            return cached
    data = await _fetch_finnhub_earnings(horizon_days=EARNINGS_REPORT_HORIZON_DAYS + 5)
    if data is None:
        return None
    # Override TTL for this specific key — earnings calendar is 6h not 5m
    _cache[_EARNINGS_CACHE_KEY] = (time.time() + (_EARNINGS_CACHE_TTL_S - _TTL_S), data)
    return data


def days_until(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    delta = (target - date.today()).days
    return delta if delta >= 0 else None


# ═══════════════════════════════════════════════════════════════════════════
# IVR (Feature 6A)
# ═══════════════════════════════════════════════════════════════════════════


def _yf_iv_blocking(ticker: str) -> Optional[float]:
    """Approximate ATM-IV via yfinance options chain (nearest expiration)."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        exps = list(t.options or [])
        if not exps:
            return None
        # Nearest expiration
        ch = t.option_chain(exps[0])
        spot = float((t.fast_info or {}).get("last_price") or 0)
        if spot <= 0:
            return None
        # Pick ATM call by min |strike - spot|
        calls = ch.calls
        if calls.empty:
            return None
        idx = (calls["strike"] - spot).abs().idxmin()
        iv = float(calls.loc[idx, "impliedVolatility"] or 0)
        if iv <= 0:
            return None
        return iv * 100.0  # to percent
    except Exception as e:
        log.debug("IV probe failed for %s: %s", ticker, e)
        return None


async def compute_ivr(ticker: str) -> Optional[float]:
    """Compute IVR (Implied Volatility Rank).

    Prefers Unusual Whales ``/api/stock/{ticker}/iv-rank`` (returns ready
    IVR 0-100). Falls back to a yfinance approximation that returns the
    *current* ATM IV as a coarse rank approximation (better than nothing).

    Returns None when no source is available.
    """
    cache_key = f"ivr:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    uw_key = os.environ.get("UNUSUAL_WHALES_API_KEY", "")
    if uw_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.unusualwhales.com/api/stock/{ticker.upper()}/iv-rank",
                    headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json"},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    data = body.get("data") if isinstance(body, dict) else None
                    if isinstance(data, list) and data:
                        row = data[-1]
                    elif isinstance(data, dict):
                        row = data
                    else:
                        row = None
                    if row:
                        try:
                            ivr = float(row.get("iv_rank") or row.get("ivr") or 0)
                            if ivr > 0:
                                _cache_set(cache_key, ivr)
                                return ivr
                        except (TypeError, ValueError):
                            pass
        except Exception as e:
            log.debug("UW IVR fetch failed for %s: %s", ticker, e)

    # yfinance fallback — current ATM IV as a coarse proxy
    loop = asyncio.get_event_loop()
    iv_pct = await loop.run_in_executor(_executor, _yf_iv_blocking, ticker)
    if iv_pct is not None:
        # Without a 52w window we can't compute true rank — surface the
        # current IV directly so the gate at least has signal. Most equity
        # IVs land in the 15-80% range, so treating raw IV as ~IVR isn't
        # crazy as a stop-gap.
        _cache_set(cache_key, iv_pct)
        return iv_pct
    return None


# ═══════════════════════════════════════════════════════════════════════════
# OPTIONS FLOW (Feature 6B) — read from agent_signals.jsonl
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FlowSummary:
    net_call_premium_24h: float
    call_put_ratio: float
    flow_confirms: Optional[bool]  # True/False/None when no data
    squeeze_candidate: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "net_call_premium_24h": self.net_call_premium_24h,
            "call_put_ratio": self.call_put_ratio,
            "flow_confirms": self.flow_confirms,
            "squeeze_candidate": self.squeeze_candidate,
        }


def _resolve_signals_file() -> Path:
    data_root = Path(os.getenv("NCL_DATA_DIR", "data"))
    if not data_root.is_absolute():
        # runtime/stocks/enrichments.py -> parents[2] = NCL root
        data_root = Path(__file__).resolve().parents[2] / data_root
    return data_root / "intelligence" / "agent_signals.jsonl"


_FLOW_CACHE_KEY = "flow:by_ticker"


def _read_recent_flow_blocking(hours: int) -> dict[str, dict[str, float]]:
    """Tail agent_signals.jsonl, aggregate UW options_flow by ticker.

    Returns ``{ticker: {call_prem, put_prem, n_signals}}``.
    """
    path = _resolve_signals_file()
    if not path.exists():
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: dict[str, dict[str, float]] = {}
    try:
        with open(path, "rb") as f:
            # Tail last 4MB — same as portfolio_routes.options-flow uses
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4 * 1024 * 1024))
            if size > 4 * 1024 * 1024:
                f.readline()
            raw = f.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.debug("flow tail failed: %s", e)
        return {}

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            sig = json.loads(line)
        except json.JSONDecodeError:
            continue
        if sig.get("source") != "options_flow":
            continue
        ts = sig.get("timestamp")
        if ts:
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        # Extract ticker from tags (cheaper than parsing the title regex)
        tags = sig.get("tags") or []
        ticker = None
        for tag in tags:
            if isinstance(tag, str) and tag.isupper() and 1 <= len(tag) <= 6:
                ticker = tag
                break
            # tag is often lowercase ticker
            if isinstance(tag, str) and 1 <= len(tag) <= 6 and tag.isalpha():
                ticker = tag.upper()
                break
        if not ticker:
            # Fall back to symbol field
            ticker = (sig.get("symbol") or sig.get("ticker") or "").upper()
        if not ticker:
            continue

        direction = (sig.get("direction") or "neutral").lower()
        meta = sig.get("metadata") or {}
        ask_prem = float(meta.get("ask_premium") or 0)
        bid_prem = float(meta.get("bid_premium") or 0)
        if not ask_prem and not bid_prem:
            value = float(sig.get("value") or 0)
            if direction == "bullish":
                ask_prem = value
            elif direction == "bearish":
                bid_prem = value
            else:
                ask_prem = bid_prem = value / 2.0

        # Direction-aware call/put attribution mirrors portfolio_routes
        if direction == "bullish":
            call_prem, put_prem = ask_prem, bid_prem
        elif direction == "bearish":
            call_prem, put_prem = bid_prem, ask_prem
        else:
            split = (ask_prem + bid_prem) / 2.0
            call_prem = put_prem = split

        slot = out.setdefault(ticker, {"call_prem": 0.0, "put_prem": 0.0, "n_signals": 0})
        slot["call_prem"] += call_prem
        slot["put_prem"] += put_prem
        slot["n_signals"] += 1

    return out


async def get_flow_map(hours: int = FLOW_LOOKBACK_HOURS) -> dict[str, dict[str, float]]:
    """Cached per-ticker flow aggregation."""
    cached = _cache_get(_FLOW_CACHE_KEY)
    if cached is not None:
        return cached
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(_executor, _read_recent_flow_blocking, hours)
    _cache_set(_FLOW_CACHE_KEY, data)
    return data


def summarize_flow(
    ticker: str,
    flow_map: dict[str, dict[str, float]],
    *,
    bullish_setup: bool,
) -> FlowSummary:
    """Decide flow_confirms / squeeze_candidate for one symbol.

    For BULLISH setups (GOAT, BRAVO buy signals):
      flow_confirms = (net_call > FLOW_MIN_NET_CALL AND call/put >= FLOW_MIN_RATIO)
      squeeze_candidate = high put premium with bullish technicals

    Returns flow_confirms=None when we have zero flow data — never penalize
    on missing data.
    """
    row = flow_map.get(ticker.upper())
    if not row or row.get("n_signals", 0) == 0:
        return FlowSummary(
            net_call_premium_24h=0.0,
            call_put_ratio=0.0,
            flow_confirms=None,
            squeeze_candidate=False,
        )

    call = float(row.get("call_prem") or 0.0)
    put = float(row.get("put_prem") or 0.0)
    net_call = call - put
    ratio = (call / put) if put > 0 else (float("inf") if call > 0 else 0.0)

    if bullish_setup:
        confirms = (net_call >= FLOW_MIN_NET_CALL) and (ratio >= FLOW_MIN_RATIO)
        # Squeeze: bullish technicals + heavy put flow (institutions short into a
        # rising setup — the technicals winning forces a cover).
        squeeze = (put > call * 1.3) and (put >= FLOW_MIN_NET_CALL)
    else:
        # For a bearish/neutral setup we just surface the numbers; mark
        # confirms None (the scanner caller decides interpretation).
        confirms = None
        squeeze = False

    # round() ratio for clean JSON
    ratio_clean = round(ratio, 3) if ratio not in (float("inf"), float("-inf")) else None
    return FlowSummary(
        net_call_premium_24h=round(net_call, 2),
        call_put_ratio=ratio_clean if ratio_clean is not None else 999.0,
        flow_confirms=confirms,
        squeeze_candidate=bool(squeeze),
    )


# ═══════════════════════════════════════════════════════════════════════════
# DARK POOL SUPPORT (Feature 6C)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DarkPoolSupport:
    price: Optional[float]
    volume: Optional[float]
    date_str: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dark_pool_support": self.price,
            "dark_pool_volume": self.volume,
            "dark_pool_date": self.date_str,
        }


async def fetch_dark_pool_support(ticker: str, current_price: float) -> DarkPoolSupport:
    """Largest off-exchange print in the last 30d below current price.

    Uses UW ``/api/darkpool/{ticker}`` if the API key is set. Returns
    all-None when unavailable — the scanner keeps its ATR-based stop.
    """
    uw_key = os.environ.get("UNUSUAL_WHALES_API_KEY", "")
    if not uw_key:
        return DarkPoolSupport(None, None, None)

    cache_key = f"dp:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.unusualwhales.com/api/darkpool/{ticker.upper()}",
                params={"limit": 200},
                headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json"},
            )
            if resp.status_code != 200:
                out = DarkPoolSupport(None, None, None)
                _cache_set(cache_key, out)
                return out
            body = resp.json()
            rows = body.get("data") if isinstance(body, dict) else None
            if not rows:
                out = DarkPoolSupport(None, None, None)
                _cache_set(cache_key, out)
                return out
    except Exception as e:
        log.debug("dark pool fetch failed for %s: %s", ticker, e)
        return DarkPoolSupport(None, None, None)

    cutoff = datetime.now(timezone.utc) - timedelta(days=DARK_POOL_LOOKBACK_DAYS)
    best: Optional[dict] = None
    for trade in rows:
        try:
            if trade.get("canceled"):
                continue
            price = float(trade.get("price") or 0)
            if price <= 0 or price >= current_price:
                continue
            size = float(trade.get("size") or 0)
            premium = float(trade.get("premium") or (price * size))
            ts_raw = trade.get("executed_at") or trade.get("timestamp") or ""
            if ts_raw:
                try:
                    t = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    if t < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            if best is None or premium > float(best.get("premium") or 0):
                best = {
                    "price": price,
                    "size": size,
                    "premium": premium,
                    "ts": ts_raw,
                }
        except (TypeError, ValueError):
            continue

    if best is None:
        out = DarkPoolSupport(None, None, None)
        _cache_set(cache_key, out)
        return out

    date_str: Optional[str] = None
    if best.get("ts"):
        try:
            t = datetime.fromisoformat(str(best["ts"]).replace("Z", "+00:00"))
            date_str = t.date().isoformat()
        except (ValueError, TypeError):
            date_str = None

    out = DarkPoolSupport(
        price=round(float(best["price"]), 2),
        volume=float(best.get("size") or 0),
        date_str=date_str,
    )
    _cache_set(cache_key, out)
    return out
