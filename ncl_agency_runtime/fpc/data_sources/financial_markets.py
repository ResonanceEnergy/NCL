"""Financial markets ingesters.

APIs: Financial Modeling Prep (FMP), CoinCap, Polygon.io, CoinGecko.
"""

import contextlib
import json
import logging
import os
from datetime import datetime
from typing import Any

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class FMPIngester(BaseIngester):
    """Financial Modeling Prep — stocks, economics, senator trades, COT, technicals."""

    source_name = "fmp"
    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("FMP_API_KEY", "")

    def _url(self, path: str, **params: Any) -> str:
        params["apikey"] = self.api_key
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}/{path}?{qs}"

    def fetch_quotes(self, symbols: list[str] | None = None) -> list[Signal]:
        symbols = symbols or ["SPY", "QQQ", "AAPL", "MSFT", "BTC-USD"]
        signals: list[Signal] = []
        for sym in symbols:
            try:
                data = self._get_json(self._url(f"quote/{sym}"))
                items = data if isinstance(data, list) else [data]
                for q in items:
                    signals.append(self._make_signal(
                        source=f"FMP:quote:{sym}",
                        title=f"{sym} — ${q.get('price', '')}",
                        content=json.dumps(q),
                        url=f"https://financialmodelingprep.com/financial-statements/{sym}",
                        meta={"symbol": sym, "price": q.get("price"), "change_pct": q.get("changesPercentage")},
                    ))
            except Exception:
                logger.warning("FMP quote failed for %s", sym)
        return signals

    def fetch_economic_indicators(self, indicator: str = "GDP") -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = self._get_json(self._url("economic", name=indicator))
            for rec in (data if isinstance(data, list) else []):
                ts = datetime.now()
                if rec.get("date"):
                    with contextlib.suppress(ValueError):
                        ts = datetime.fromisoformat(rec["date"][:10])
                signals.append(self._make_signal(
                    source=f"FMP:econ:{indicator}",
                    title=f"{indicator} — {rec.get('date', '')}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={"indicator": indicator, "value": rec.get("value")},
                ))
        except Exception:
            logger.warning("FMP economic indicator failed: %s", indicator)
        return signals

    def fetch_senate_trades(self, limit: int = 50) -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = self._get_json(self._url("senate-trading", limit=limit))
            for rec in (data if isinstance(data, list) else []):
                signals.append(self._make_signal(
                    source="FMP:senate_trades",
                    title=f"Senator {rec.get('senator', '')} — {rec.get('ticker', '')}",
                    content=json.dumps(rec),
                    meta={
                        "senator": rec.get("senator"),
                        "ticker": rec.get("ticker"),
                        "type": rec.get("type"),
                        "amount": rec.get("amount"),
                    },
                ))
        except Exception:
            logger.warning("FMP senate trades failed")
        return signals

    def fetch_technical_indicator(
        self, symbol: str = "SPY", indicator: str = "sma", period: int = 20
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = self._get_json(self._url(
                f"technical_indicator/daily/{symbol}",
                type=indicator,
                period=period,
            ))
            for rec in (data if isinstance(data, list) else [])[:100]:
                ts = datetime.now()
                if rec.get("date"):
                    with contextlib.suppress(ValueError):
                        ts = datetime.fromisoformat(rec["date"][:10])
                signals.append(self._make_signal(
                    source=f"FMP:tech:{indicator}:{symbol}",
                    title=f"{symbol} {indicator.upper()}({period}) — {rec.get('date', '')}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={"symbol": symbol, "indicator": indicator, "period": period},
                ))
        except Exception:
            logger.warning("FMP technical indicator failed: %s/%s", symbol, indicator)
        return signals

    def fetch_commitment_of_traders(self) -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = self._get_json(self._url("commitment_of_traders_report"))
            for rec in (data if isinstance(data, list) else [])[:50]:
                signals.append(self._make_signal(
                    source="FMP:cot",
                    title=f"COT — {rec.get('market_and_exchange_names', '')}",
                    content=json.dumps(rec),
                    meta={"market": rec.get("market_and_exchange_names")},
                ))
        except Exception:
            logger.warning("FMP COT report failed")
        return signals

    def fetch_esg_ratings(self, symbol: str = "AAPL") -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = self._get_json(self._url("esg-environmental-social-governance-data", symbol=symbol))
            for rec in (data if isinstance(data, list) else []):
                signals.append(self._make_signal(
                    source=f"FMP:esg:{symbol}",
                    title=f"ESG {symbol} — {rec.get('date', '')}",
                    content=json.dumps(rec),
                    meta={"symbol": symbol, "esg_score": rec.get("ESGScore")},
                ))
        except Exception:
            logger.warning("FMP ESG failed for %s", symbol)
        return signals

    def fetch(self, **kwargs: Any) -> list[Signal]:
        if not self.api_key:
            logger.warning("FMP_API_KEY not set — skipping FMP")
            return []
        signals: list[Signal] = []
        signals.extend(self.fetch_quotes())
        for ind in ["GDP", "CPI", "unemploymentRate", "federalFundsRate", "retailSales"]:
            signals.extend(self.fetch_economic_indicators(ind))
        signals.extend(self.fetch_senate_trades())
        signals.extend(self.fetch_commitment_of_traders())
        logger.info("FMP: ingested %d signals total", len(signals))
        return signals


class CoinCapIngester(BaseIngester):
    """CoinCap API v3 — 1000+ crypto assets, real-time pricing, TA."""

    source_name = "coincap"
    BASE_URL = "https://rest.coincap.io/v3"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("COINCAP_API_KEY", "")

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def fetch(
        self,
        assets: list[str] | None = None,
        limit: int = 20,
    ) -> list[Signal]:
        assets = assets or ["bitcoin", "ethereum", "solana", "cardano", "dogecoin"]
        signals: list[Signal] = []

        # Top assets
        try:
            data = self._get_json(f"{self.BASE_URL}/assets?limit={limit}", headers=self._headers())
            for asset in data.get("data", []):
                signals.append(self._make_signal(
                    source=f"CoinCap:{asset.get('id', '')}",
                    title=f"{asset.get('name', '')} — ${asset.get('priceUsd', '')}",
                    content=json.dumps(asset),
                    url=f"https://coincap.io/assets/{asset.get('id', '')}",
                    meta={
                        "id": asset.get("id"),
                        "price": asset.get("priceUsd"),
                        "market_cap": asset.get("marketCapUsd"),
                        "change_24h": asset.get("changePercent24Hr"),
                    },
                ))
        except Exception:
            logger.warning("CoinCap assets fetch failed")

        # Individual asset history
        for a in assets:
            try:
                data = self._get_json(
                    f"{self.BASE_URL}/assets/{a}/history?interval=d1",
                    headers=self._headers(),
                )
                for pt in (data.get("data", []) or [])[-30:]:
                    ts = datetime.now()
                    if pt.get("date"):
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(pt["date"][:19])
                    signals.append(self._make_signal(
                        source=f"CoinCap:{a}:history",
                        title=f"{a} — ${pt.get('priceUsd', '')} — {pt.get('date', '')}",
                        content=json.dumps(pt),
                        timestamp=ts,
                        meta={"asset": a, "price": pt.get("priceUsd")},
                    ))
            except Exception:
                logger.warning("CoinCap history failed for %s", a)

        logger.info("CoinCap: ingested %d signals", len(signals))
        return signals


class PolygonIngester(BaseIngester):
    """Polygon.io — stocks, options, forex, crypto tick data."""

    source_name = "polygon"
    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("POLYGON_API_KEY", "")

    def fetch(
        self,
        tickers: list[str] | None = None,
        timespan: str = "day",
        limit: int = 30,
    ) -> list[Signal]:
        if not self.api_key:
            logger.warning("POLYGON_API_KEY not set — skipping Polygon")
            return []
        tickers = tickers or ["SPY", "QQQ", "AAPL"]
        signals: list[Signal] = []
        for ticker in tickers:
            try:
                url = (
                    f"{self.BASE_URL}/v2/aggs/ticker/{ticker}/range/1/{timespan}"
                    f"/2025-01-01/2026-12-31?adjusted=true&sort=desc&limit={limit}"
                    f"&apiKey={self.api_key}"
                )
                data = self._get_json(url)
                for bar in data.get("results", []):
                    ts = datetime.fromtimestamp(bar["t"] / 1000) if bar.get("t") else datetime.now()
                    signals.append(self._make_signal(
                        source=f"Polygon:{ticker}",
                        title=f"{ticker} — C:{bar.get('c', '')}",
                        content=json.dumps(bar),
                        timestamp=ts,
                        meta={
                            "ticker": ticker,
                            "open": bar.get("o"),
                            "high": bar.get("h"),
                            "low": bar.get("l"),
                            "close": bar.get("c"),
                            "volume": bar.get("v"),
                        },
                    ))
            except Exception:
                logger.warning("Polygon fetch failed for %s", ticker)
        logger.info("Polygon: ingested %d signals", len(signals))
        return signals


class CoinGeckoIngester(BaseIngester):
    """CoinGecko — market data, trending, social metrics."""

    source_name = "coingecko"
    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("COINGECKO_API_KEY", "")
        if self.api_key:
            self.BASE_URL = "https://pro-api.coingecko.com/api/v3"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.api_key:
            h["x-cg-pro-api-key"] = self.api_key
        return h

    def fetch(
        self,
        coins: list[str] | None = None,
        vs_currency: str = "usd",
    ) -> list[Signal]:
        coins = coins or ["bitcoin", "ethereum", "solana"]
        signals: list[Signal] = []

        # Global market overview
        try:
            data = self._get_json(f"{self.BASE_URL}/global", headers=self._headers())
            gd = data.get("data", {})
            signals.append(self._make_signal(
                source="CoinGecko:global",
                title=f"Global Crypto — MCap: ${gd.get('total_market_cap', {}).get('usd', 0):,.0f}",
                content=json.dumps(gd),
                meta={"total_market_cap": gd.get("total_market_cap", {}).get("usd")},
            ))
        except Exception:
            logger.warning("CoinGecko global failed")

        # Trending
        try:
            data = self._get_json(f"{self.BASE_URL}/search/trending", headers=self._headers())
            for coin in data.get("coins", [])[:10]:
                item = coin.get("item", {})
                signals.append(self._make_signal(
                    source="CoinGecko:trending",
                    title=f"Trending: {item.get('name', '')} ({item.get('symbol', '')})",
                    content=json.dumps(item),
                    meta={"name": item.get("name"), "symbol": item.get("symbol"), "market_cap_rank": item.get("market_cap_rank")},
                ))
        except Exception:
            logger.warning("CoinGecko trending failed")

        # Per-coin data
        for coin_id in coins:
            try:
                data = self._get_json(
                    f"{self.BASE_URL}/coins/{coin_id}"
                    f"?localization=false&tickers=false&community_data=true&developer_data=true",
                    headers=self._headers(),
                )
                md = data.get("market_data", {})
                dd = data.get("developer_data", {})
                cd = data.get("community_data", {})
                signals.append(self._make_signal(
                    source=f"CoinGecko:{coin_id}",
                    title=f"{data.get('name', coin_id)} — ${md.get('current_price', {}).get(vs_currency, '')}",
                    content=json.dumps({
                        "price": md.get("current_price", {}).get(vs_currency),
                        "market_cap": md.get("market_cap", {}).get(vs_currency),
                        "ath": md.get("ath", {}).get(vs_currency),
                        "ath_change_pct": md.get("ath_change_percentage", {}).get(vs_currency),
                        "github_stars": dd.get("stars"),
                        "github_forks": dd.get("forks"),
                        "reddit_subscribers": cd.get("reddit_subscribers"),
                        "twitter_followers": cd.get("twitter_followers"),
                    }),
                    meta={
                        "coin": coin_id,
                        "price": md.get("current_price", {}).get(vs_currency),
                        "github_stars": dd.get("stars"),
                        "reddit_subs": cd.get("reddit_subscribers"),
                    },
                ))
            except Exception:
                logger.warning("CoinGecko coin failed for %s", coin_id)

        logger.info("CoinGecko: ingested %d signals", len(signals))
        return signals
