"""FRED & Alpha Vantage economic data ingesters."""

import json
import logging
import os
import urllib.request
from datetime import datetime

from .ingestion import Signal

logger = logging.getLogger(__name__)


class FREDIngester:
    """Fetch economic indicator series from the Federal Reserve (FRED).

    Requires env var ``FRED_API_KEY`` — https://fred.stlouisfed.org/docs/api/
    """

    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("FRED_API_KEY", "")

    def fetch_series(
        self,
        series_id: str,
        limit: int = 100,
        sort_order: str = "desc",
    ) -> list[Signal]:
        if not self.api_key:
            logger.warning("FRED_API_KEY not set — skipping FRED ingestion")
            return []

        url = (
            f"{self.BASE_URL}/series/observations"
            f"?series_id={series_id}"
            f"&api_key={self.api_key}"
            f"&file_type=json"
            f"&sort_order={sort_order}"
            f"&limit={limit}"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FPC/0.3"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            logger.warning("Failed to fetch FRED series: %s", series_id)
            return []

        signals: list[Signal] = []
        for obs in data.get("observations", []):
            signals.append(
                Signal(
                    source=f"FRED:{series_id}",
                    title=f"{series_id} — {obs.get('date', '')}",
                    content=obs.get("value", ""),
                    url=f"https://fred.stlouisfed.org/series/{series_id}",
                    timestamp=datetime.fromisoformat(obs["date"]) if obs.get("date") else datetime.now(),
                    meta={"series_id": series_id, "value": obs.get("value", ".")},
                )
            )
        logger.info("Ingested %d observations from FRED/%s", len(signals), series_id)
        return signals

    def fetch_many(self, series_ids: list[str], limit: int = 100) -> list[Signal]:
        all_signals: list[Signal] = []
        for sid in series_ids:
            all_signals.extend(self.fetch_series(sid, limit=limit))
        return all_signals


# Default economic indicators useful for forecasting
FRED_INDICATORS = [
    "GDP",         # Gross Domestic Product
    "CPIAUCSL",    # Consumer Price Index
    "UNRATE",      # Unemployment Rate
    "DFF",         # Federal Funds Rate
    "T10Y2Y",     # 10-Year minus 2-Year Treasury Spread (recession signal)
    "VIXCLS",      # VIX Volatility Index
    "DCOILWTICO",  # Crude Oil WTI
    "GOLDAMGBD228NLBM",  # Gold Price
]


class AlphaVantageIngester:
    """Fetch stock/crypto/forex data from Alpha Vantage.

    Requires env var ``ALPHA_VANTAGE_KEY`` — https://www.alphavantage.co/
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ALPHA_VANTAGE_KEY", "")

    def _fetch(self, params: dict) -> dict:
        params["apikey"] = self.api_key
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.BASE_URL}?{qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FPC/0.3"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            logger.warning("Alpha Vantage request failed: %s", params.get("function"))
            return {}

    def fetch_daily(self, symbol: str, outputsize: str = "compact") -> list[Signal]:
        if not self.api_key:
            logger.warning("ALPHA_VANTAGE_KEY not set — skipping")
            return []

        data = self._fetch({
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize,
        })

        ts = data.get("Time Series (Daily)", {})
        signals: list[Signal] = []
        for date_str, ohlcv in ts.items():
            signals.append(
                Signal(
                    source=f"AlphaVantage:{symbol}",
                    title=f"{symbol} — {date_str}",
                    content=json.dumps(ohlcv),
                    url=f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}",
                    timestamp=datetime.fromisoformat(date_str),
                    meta={
                        "symbol": symbol,
                        "open": ohlcv.get("1. open"),
                        "high": ohlcv.get("2. high"),
                        "low": ohlcv.get("3. low"),
                        "close": ohlcv.get("4. close"),
                        "volume": ohlcv.get("5. volume"),
                    },
                )
            )
        logger.info("Ingested %d daily bars for %s", len(signals), symbol)
        return signals

    def fetch_crypto(self, symbol: str = "BTC", market: str = "USD") -> list[Signal]:
        if not self.api_key:
            logger.warning("ALPHA_VANTAGE_KEY not set — skipping")
            return []

        data = self._fetch({
            "function": "DIGITAL_CURRENCY_DAILY",
            "symbol": symbol,
            "market": market,
        })

        ts = data.get("Time Series (Digital Currency Daily)", {})
        signals: list[Signal] = []
        for date_str, vals in ts.items():
            close_key = f"4a. close ({market})"
            signals.append(
                Signal(
                    source=f"AlphaVantage:crypto:{symbol}",
                    title=f"{symbol}/{market} — {date_str}",
                    content=json.dumps(vals),
                    url="",
                    timestamp=datetime.fromisoformat(date_str),
                    meta={
                        "symbol": symbol,
                        "market": market,
                        "close": vals.get(close_key, ""),
                    },
                )
            )
        logger.info("Ingested %d crypto bars for %s/%s", len(signals), symbol, market)
        return signals
