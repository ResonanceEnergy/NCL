#!/usr/bin/env python3
"""
IBKR Market Data Provider for NCL Scanners
============================================
Wraps ib_insync market data methods to provide real-time and historical
data for GOAT Academy and Johnny Bravo scanners.

Falls back to yfinance when IBKR is not connected.

Usage:
    provider = IBKRMarketData(ibkr_adapter)
    bars = await provider.get_historical_bars("AAPL", period="6mo", interval="1d")
    quote = await provider.get_quote("AAPL")
    universe = await provider.scan_universe("TOP_PERC_GAIN", limit=50)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger("ncl.portfolio.ibkr_market_data")

# ── ib_insync types — lazy loaded via ibkr_adapter ────────────────
# We import from ibkr_adapter to reuse its lazy import mechanism
# that handles Python 3.14 event loop compatibility.

_yfinance_available = False
try:
    import yfinance as yf

    _yfinance_available = True
except ImportError:
    pass

try:
    import numpy as np

    _numpy_available = True
except ImportError:
    _numpy_available = False


class IBKRMarketData:
    """
    Market data provider that prefers IBKR when connected,
    falls back to yfinance otherwise.

    Designed to be a drop-in data source for scanner.py.
    """

    def __init__(self, ibkr_adapter=None):
        """
        Args:
            ibkr_adapter: IBKRAdapter instance (can be None for yfinance-only mode)
        """
        self._adapter = ibkr_adapter
        self._quote_cache: Dict[str, Tuple[float, Dict]] = {}  # symbol -> (timestamp, data)
        self._cache_ttl = 5.0  # 5 second quote cache

    @property
    def ibkr_connected(self) -> bool:
        return self._adapter is not None and self._adapter.connected

    @property
    def source(self) -> str:
        return "IBKR" if self.ibkr_connected else "yfinance"

    # ── Historical Bars ───────────────────────────────────────────

    async def get_historical_bars(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> Optional[Any]:
        """
        Get historical OHLCV bars as a pandas-like structure.

        Returns a dict with numpy arrays matching what scanner.py expects:
        {Open, High, Low, Close, Volume} as numpy arrays, plus dates.

        Falls back to yfinance if IBKR unavailable.
        """
        if self.ibkr_connected:
            try:
                return await self._ibkr_historical(symbol, period, interval)
            except Exception as e:
                logger.warning(
                    "IBKR historical failed for %s, falling back to yfinance: %s", symbol, e
                )

        if _yfinance_available:
            return await self._yfinance_historical(symbol, period, interval)

        logger.error("No data source available for historical bars")
        return None

    async def _ibkr_historical(self, symbol: str, period: str, interval: str) -> Optional[Dict]:
        """Fetch historical bars via IBKR API."""
        from .ibkr_adapter import IB_INSYNC_AVAILABLE, Stock

        if not IB_INSYNC_AVAILABLE:
            return None

        ib = self._adapter._ib

        # Map period strings to IBKR duration format
        duration_map = {
            "1mo": "1 M",
            "3mo": "3 M",
            "6mo": "6 M",
            "1y": "1 Y",
            "2y": "2 Y",
            "5y": "5 Y",
            "ytd": "1 Y",  # approximate
        }
        duration = duration_map.get(period, "6 M")

        # Map interval to IBKR bar size
        bar_map = {
            "1m": "1 min",
            "5m": "5 mins",
            "15m": "15 mins",
            "30m": "30 mins",
            "1h": "1 hour",
            "1d": "1 day",
            "1wk": "1 week",
            "1mo": "1 month",
        }
        bar_size = bar_map.get(interval, "1 day")

        contract = Stock(symbol, "SMART", "USD")

        bars = await asyncio.to_thread(
            ib.reqHistoricalData,
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        if not bars:
            return None

        # Convert to dict of numpy arrays (matching yfinance DataFrame shape)
        if _numpy_available:
            result = {
                "Open": np.array([b.open for b in bars]),
                "High": np.array([b.high for b in bars]),
                "Low": np.array([b.low for b in bars]),
                "Close": np.array([b.close for b in bars]),
                "Volume": np.array([b.volume for b in bars]),
                "dates": [b.date for b in bars],
                "source": "IBKR",
            }
            return result

        return None

    async def _yfinance_historical(self, symbol: str, period: str, interval: str) -> Optional[Dict]:
        """Fetch historical bars via yfinance (fallback)."""
        try:
            df = await asyncio.to_thread(
                lambda: yf.download(symbol, period=period, interval=interval, progress=False)
            )
            if df is None or df.empty:
                return None

            # Handle MultiIndex columns from yfinance
            if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
                df = df.droplevel(level=1, axis=1)

            if _numpy_available:
                return {
                    "Open": df["Open"].values,
                    "High": df["High"].values,
                    "Low": df["Low"].values,
                    "Close": df["Close"].values,
                    "Volume": df["Volume"].values,
                    "dates": df.index.tolist(),
                    "source": "yfinance",
                }
            return None
        except Exception as e:
            logger.error("yfinance historical failed for %s: %s", symbol, e)
            return None

    # ── Real-time Quotes ──────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current quote for a symbol.

        Returns: {price, bid, ask, volume, vwap, high, low, open, close,
                  change, change_pct, timestamp, source}
        """
        # Check cache
        import time

        now = time.time()
        if symbol in self._quote_cache:
            ts, data = self._quote_cache[symbol]
            if now - ts < self._cache_ttl:
                return data

        quote = None
        if self.ibkr_connected:
            try:
                quote = await self._ibkr_quote(symbol)
            except Exception as e:
                logger.warning("IBKR quote failed for %s: %s", symbol, e)

        if quote is None and _yfinance_available:
            quote = await self._yfinance_quote(symbol)

        if quote:
            self._quote_cache[symbol] = (now, quote)

        return quote

    async def _ibkr_quote(self, symbol: str) -> Optional[Dict]:
        """Get real-time quote from IBKR."""
        from .ibkr_adapter import IB_INSYNC_AVAILABLE, Stock

        if not IB_INSYNC_AVAILABLE:
            return None

        ib = self._adapter._ib
        contract = Stock(symbol, "SMART", "USD")

        # Request snapshot (no streaming subscription needed)
        ticker = await asyncio.to_thread(ib.reqMktData, contract, "", True, False)

        # Wait briefly for data
        await asyncio.sleep(0.5)

        if ticker.last != ticker.last:  # NaN check
            return None

        return {
            "price": ticker.last or ticker.close or 0,
            "bid": ticker.bid or 0,
            "ask": ticker.ask or 0,
            "volume": ticker.volume or 0,
            "vwap": getattr(ticker, "vwap", 0) or 0,
            "high": ticker.high or 0,
            "low": ticker.low or 0,
            "open": ticker.open or 0,
            "close": ticker.close or 0,
            "change": (ticker.last or 0) - (ticker.close or 0),
            "change_pct": (
                ((ticker.last - ticker.close) / ticker.close * 100)
                if ticker.close and ticker.last
                else 0
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "IBKR",
        }

    async def _yfinance_quote(self, symbol: str) -> Optional[Dict]:
        """Get quote from yfinance (delayed)."""
        try:
            ticker = yf.Ticker(symbol)
            info = await asyncio.to_thread(lambda: ticker.fast_info)

            price = getattr(info, "last_price", 0) or 0
            prev_close = getattr(info, "previous_close", 0) or 0
            change = price - prev_close if price and prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0

            return {
                "price": price,
                "bid": 0,
                "ask": 0,
                "volume": getattr(info, "last_volume", 0) or 0,
                "vwap": 0,
                "high": getattr(info, "day_high", 0) or 0,
                "low": getattr(info, "day_low", 0) or 0,
                "open": getattr(info, "open", 0) or 0,
                "close": prev_close,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "yfinance",
            }
        except Exception as e:
            logger.error("yfinance quote failed for %s: %s", symbol, e)
            return None

    # ── Batch Quotes ──────────────────────────────────────────────

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get quotes for multiple symbols. Returns {symbol: quote_dict}."""
        results = {}
        # Run in parallel batches
        tasks = [self.get_quote(s) for s in symbols]
        quotes = await asyncio.gather(*tasks, return_exceptions=True)
        for symbol, quote in zip(symbols, quotes):
            if isinstance(quote, dict):
                results[symbol] = quote
        return results

    # ── Market Scanner (IBKR-only) ────────────────────────────────

    async def scan_universe(
        self,
        scan_code: str = "TOP_PERC_GAIN",
        instrument: str = "STK",
        location: str = "STK.US.MAJOR",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Run an IBKR built-in market scanner.

        Useful scan codes for GOAT/Bravo:
        - TOP_PERC_GAIN: Biggest % gainers (GOAT Rule 1)
        - TOP_PERC_LOSE: Biggest % losers
        - MOST_ACTIVE: Highest volume (GOAT Rule 6)
        - HOT_BY_VOLUME: Unusual volume surge
        - HOT_BY_OPT_VOLUME: Unusual options activity
        - HIGH_VS_52W_HL: Near 52-week highs (GOAT breakout)
        - TOP_TRADE_COUNT: Most trades
        - TOP_TRADE_RATE: Fastest trading

        Returns list of {symbol, price, change_pct, volume, ...} dicts.
        Falls back to empty list if IBKR not connected.
        """
        if not self.ibkr_connected:
            logger.info("IBKR not connected — scanner unavailable, returning empty")
            return []

        try:
            from .ibkr_adapter import IB_INSYNC_AVAILABLE

            if not IB_INSYNC_AVAILABLE:
                return []

            from ib_insync import ScannerSubscription

            ib = self._adapter._ib

            sub = ScannerSubscription(
                instrument=instrument,
                locationCode=location,
                scanCode=scan_code,
                numberOfRows=limit,
            )

            scan_results = await asyncio.to_thread(ib.reqScannerData, sub, [])

            results = []
            for item in scan_results:
                contract = item.contractDetails.contract
                results.append(
                    {
                        "symbol": contract.symbol,
                        "sec_type": contract.secType,
                        "exchange": contract.exchange,
                        "currency": contract.currency,
                        "rank": item.rank,
                        "scan_code": scan_code,
                        "source": "IBKR_SCANNER",
                    }
                )

            logger.info("IBKR scanner %s returned %d results", scan_code, len(results))
            return results

        except Exception as e:
            logger.error("IBKR scanner failed (%s): %s", scan_code, e)
            return []

    # ── VIX / Market Indicators ───────────────────────────────────

    async def get_vix(self) -> float:
        """Get current VIX value. Uses IBKR if available, else yfinance."""
        if self.ibkr_connected:
            try:
                from .ibkr_adapter import Contract

                ib = self._adapter._ib
                vix_contract = Contract(
                    secType="IND", symbol="VIX", exchange="CBOE", currency="USD"
                )
                ticker = await asyncio.to_thread(ib.reqMktData, vix_contract, "", True, False)
                await asyncio.sleep(0.3)
                if ticker.last and ticker.last == ticker.last:  # not NaN
                    return ticker.last
            except Exception as e:
                logger.warning("IBKR VIX fetch failed: %s", e)

        # Fallback to yfinance
        if _yfinance_available:
            try:
                vix = yf.Ticker("^VIX")
                info = await asyncio.to_thread(lambda: vix.fast_info)
                return getattr(info, "last_price", 20.0) or 20.0
            except Exception:
                pass

        return 20.0  # Default if all sources fail
