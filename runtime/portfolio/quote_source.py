"""
NCL Quote Source Abstraction — Wave 14J out-of-scope finisher

Tiny protocol + fallback chain so a future quote-source swap (Polygon,
IEX, OPRA) is a one-file change instead of a hunt through every adapter.

Today's quote-fill chain is hard-coded in portfolio_manager.py
_fill_missing_quotes(): broker fast_info -> broker info.currentPrice ->
yfinance history -> zero. This module formalizes that chain as a
sequence of QuoteSource instances + a circuit-broken composite.

NOT a new paid feed. Just the abstraction layer. The audit said a paid
feed is premature; that's still true. This module ensures that when
the day comes, we're ready.

Usage in PortfolioManager._fill_missing_quotes():

    from .quote_source import default_quote_chain
    chain = default_quote_chain()
    for sym in missing_symbols:
        px = await chain.get(sym)
        if px is not None:
            apply_to_position(sym, px)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger("ncl.portfolio.quote_source")


@runtime_checkable
class QuoteSource(Protocol):
    """Protocol every quote source implements."""
    name: str

    async def get(self, symbol: str) -> Optional[float]: ...


# ── Built-in sources ─────────────────────────────────────────────

class YFinanceSource:
    name = "yfinance"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, float]] = {}  # symbol -> (price, ts)
        self._cache_ttl = float(os.getenv("NCL_QUOTE_CACHE_TTL_S", "30"))
        self._lock = asyncio.Lock()

    async def get(self, symbol: str) -> Optional[float]:
        async with self._lock:
            now = time.monotonic()
            cached = self._cache.get(symbol)
            if cached and (now - cached[1]) < self._cache_ttl:
                return cached[0]
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            # 3-tier read like portfolio_manager.py uses
            px = None
            try:
                fi = t.fast_info
                px = float(fi.get("last_price") or fi.get("regular_market_price") or 0) or None
            except Exception:
                pass
            if px is None or px <= 0:
                try:
                    info = t.info or {}
                    px = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0) or None
                except Exception:
                    pass
            if px is None or px <= 0:
                try:
                    h = t.history(period="1d")
                    if not h.empty:
                        px = float(h["Close"].iloc[-1])
                except Exception:
                    pass
            if px and px > 0:
                async with self._lock:
                    self._cache[symbol] = (px, time.monotonic())
                return px
        except Exception as e:
            log.debug("[YFINANCE-QS] %s: %s", symbol, e)
        return None


class StaticOverrideSource:
    """For tests + operator overrides — exact prices wins over computed."""
    name = "static_override"

    def __init__(self, overrides: Optional[dict[str, float]] = None) -> None:
        self.overrides = overrides or {}

    async def get(self, symbol: str) -> Optional[float]:
        return self.overrides.get(symbol.upper())


class CachedSource:
    """Wraps any QuoteSource with a TTL cache (per-source memoization)."""
    def __init__(self, inner: QuoteSource, ttl_s: float = 30.0) -> None:
        self.inner = inner
        self.name = f"cached:{inner.name}"
        self._ttl = ttl_s
        self._cache: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, symbol: str) -> Optional[float]:
        async with self._lock:
            now = time.monotonic()
            cached = self._cache.get(symbol)
            if cached and (now - cached[1]) < self._ttl:
                return cached[0]
        v = await self.inner.get(symbol)
        if v is not None:
            async with self._lock:
                self._cache[symbol] = (v, time.monotonic())
        return v


# ── Composite chain ──────────────────────────────────────────────

class QuoteChain:
    """Try each source in order until one returns a non-None price.
    Records which source served each quote in `last_source` for
    observability."""

    def __init__(self, sources: list[QuoteSource]) -> None:
        self.sources = sources
        self.last_source: dict[str, str] = {}
        self.miss_count: dict[str, int] = {}

    async def get(self, symbol: str) -> Optional[float]:
        for src in self.sources:
            try:
                px = await src.get(symbol)
            except Exception as e:
                log.warning("[QC] %s raised on %s: %s", src.name, symbol, e)
                continue
            if px is not None and px > 0:
                self.last_source[symbol.upper()] = src.name
                return px
        self.miss_count[symbol.upper()] = self.miss_count.get(symbol.upper(), 0) + 1
        return None

    def stats(self) -> dict:
        return {
            "sources": [s.name for s in self.sources],
            "last_source_counts": _count_values(self.last_source),
            "miss_total": sum(self.miss_count.values()),
            "miss_top10": sorted(
                self.miss_count.items(), key=lambda kv: -kv[1]
            )[:10],
        }


def _count_values(d: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in d.values():
        out[v] = out.get(v, 0) + 1
    return out


_DEFAULT: Optional[QuoteChain] = None
_DEFAULT_LOCK = asyncio.Lock()


def default_quote_chain() -> QuoteChain:
    """Process-wide default chain. Sources, in order:
       1. operator static overrides (file-loaded)
       2. yfinance (cached 30s)
       3. (future: Polygon / IEX when wired)
    """
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = QuoteChain([
            StaticOverrideSource(_load_static_overrides()),
            CachedSource(YFinanceSource(), ttl_s=30.0),
        ])
    return _DEFAULT


def _load_static_overrides() -> dict[str, float]:
    """Optional operator-set price overrides from
    data/portfolio/quote_overrides.json. Empty/missing returns {}."""
    from pathlib import Path
    import json as _json
    p = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    f = p / "data" / "portfolio" / "quote_overrides.json"
    if not f.exists():
        return {}
    try:
        raw = _json.loads(f.read_text())
        return {k.upper(): float(v) for k, v in raw.items() if isinstance(v, (int, float))}
    except Exception:
        return {}
