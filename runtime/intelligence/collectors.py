"""Data source collectors for NCL Intelligence Engine.

Each collector fetches structured data from a specific source,
returning typed IntelSignal objects with real quantitative data.

Sources:
  - Google Trends (pytrends — no API key needed)
  - Polymarket (public REST API — no key needed)
  - News (NewsAPI, GNews, or RSS)
  - Crypto market data (CoinGecko — free tier)
  - X / YouTube / Reddit (existing scanner, re-wrapped)

All collectors share:
  - async interface
  - httpx client with retry
  - rate limiting per source
  - structured signal output
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from .models import (
    IntelSignal,
    TrendSignal,
    PredictionMarketSignal,
    MarketSignal,
    NewsSignal,
    SocialSignal,
    SignalDirection,
    SourceType,
)

log = logging.getLogger("ncl.intelligence.collectors")


# ═══════════════════════════════════════════════════════════════════════════
# SHARED HTTP UTILITIES
# ═══════════════════════════════════════════════════════════════════════════


class _RateLimiter:
    """Token-bucket rate limiter."""

    def __init__(self, calls_per_minute: int = 10):
        self.calls_per_minute = calls_per_minute
        self._timestamps: list[float] = []

    async def acquire(self) -> None:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self.calls_per_minute:
            wait = 60 - (now - self._timestamps[0])
            if wait > 0:
                await asyncio.sleep(wait)
        self._timestamps.append(time.monotonic())


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    limiter: Optional[_RateLimiter] = None,
    retries: int = 3,
) -> Any:
    """GET JSON with retry and rate limiting."""
    if limiter:
        await limiter.acquire()
    last_err = None
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 429:
                wait = int(resp.headers.get("retry-after", 2 ** attempt))
                log.warning(f"Rate limited on {url}, waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            last_err = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
                raise
            await asyncio.sleep(2 ** attempt)
    raise last_err or Exception(f"Failed after {retries} retries: {url}")


# ═══════════════════════════════════════════════════════════════════════════
# 1. GOOGLE TRENDS COLLECTOR
# ═══════════════════════════════════════════════════════════════════════════


class GoogleTrendsCollector:
    """
    Fetch trending searches and interest-over-time from Google Trends.

    Uses the unofficial trends API endpoints (same as pytrends).
    No API key required.
    """

    TRENDING_URL = "https://trends.google.com/trending/rss"
    DAILY_TRENDS_URL = "https://trends.google.com/trends/api/dailytrends"
    REALTIME_URL = "https://trends.google.com/trends/api/realtimetrends"

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NCL-Intelligence/1.0",
            },
            follow_redirects=True,
        )
        self._limiter = _RateLimiter(calls_per_minute=5)

    async def collect_daily_trends(self, geo: str = "US") -> list[TrendSignal]:
        """
        Fetch today's trending searches from Google Trends.

        Primary: RSS feed (reliable, always works).
        Fallback: dailytrends JSON API (sometimes returns 404).
        """
        signals = []

        # ── Primary: RSS feed ─────────────────────────────────────
        try:
            resp = await self._client.get(
                self.TRENDING_URL,
                params={"geo": geo},
            )
            if resp.status_code == 200 and resp.text.strip().startswith("<?xml"):
                signals = self._parse_rss_trends(resp.text, geo)
                if signals:
                    log.info(f"Google Trends RSS: {len(signals)} trending items")
                    return signals
        except Exception as e:
            log.warning(f"Google Trends RSS failed: {e}")

        # ── Fallback: JSON API ────────────────────────────────────
        try:
            resp = await self._client.get(
                self.DAILY_TRENDS_URL,
                params={"hl": "en-US", "tz": "-240", "geo": geo, "ns": "15"},
            )
            if resp.status_code != 200:
                log.warning(f"Google Trends JSON API returned {resp.status_code}")
                return signals

            # Google prepends ")]}'" to JSON responses
            text = resp.text
            if text.startswith(")]}'"):
                text = text[5:]

            data = json.loads(text)
            days = data.get("default", {}).get("trendingSearchesDays", [])

            for day in days[:2]:  # Today and yesterday
                for trend in day.get("trendingSearches", []):
                    title_data = trend.get("title", {})
                    query = title_data.get("query", "")
                    traffic = trend.get("formattedTraffic", "0")
                    traffic_num = self._parse_traffic(traffic)

                    related = [
                        r.get("query", "")
                        for r in trend.get("relatedQueries", [])
                    ]

                    articles = trend.get("articles", [])
                    snippet = articles[0].get("snippet", "") if articles else ""

                    signals.append(TrendSignal(
                        source=SourceType.GOOGLE_TRENDS,
                        category="trending",
                        title=query,
                        content=snippet[:500] if snippet else f"Trending: {query}",
                        search_term=query,
                        trend_direction="rising",
                        related_queries=related[:5],
                        geo=geo,
                        value=traffic_num,
                        volume=traffic_num,
                        confidence=min(0.9, 0.3 + (traffic_num / 1_000_000) * 0.6),
                        direction=SignalDirection.EMERGING,
                        tags=["trending", "google", geo.lower()],
                        metadata={"formatted_traffic": traffic, "article_count": len(articles)},
                    ))

        except Exception as e:
            log.warning(f"Google Trends daily collection failed: {e}")

        return signals

    def _parse_rss_trends(self, xml_text: str, geo: str = "US") -> list[TrendSignal]:
        """Parse Google Trends RSS feed into TrendSignal objects."""
        import xml.etree.ElementTree as ET

        signals = []
        try:
            root = ET.fromstring(xml_text)
            # RSS items are in channel/item
            ns = {"ht": "https://trends.google.com/trending/rss"}
            items = root.findall(".//item")

            for i, item in enumerate(items[:30]):  # Cap at 30
                title_el = item.find("title")
                title = title_el.text if title_el is not None else ""
                if not title:
                    continue

                # Extract traffic volume from ht:approx_traffic
                traffic_el = item.find("ht:approx_traffic", ns)
                traffic_str = traffic_el.text if traffic_el is not None else "0"
                traffic_num = self._parse_traffic(traffic_str)

                # Description / snippet
                desc_el = item.find("description")
                desc = desc_el.text if desc_el is not None else ""

                # Link
                link_el = item.find("link")
                link = link_el.text if link_el is not None else ""

                # News items within the trend
                news_items = item.findall("ht:news_item", ns)
                snippets = []
                for ni in news_items[:2]:
                    ni_title = ni.find("ht:news_item_title", ns)
                    if ni_title is not None and ni_title.text:
                        snippets.append(ni_title.text)

                content = " | ".join(snippets) if snippets else f"Trending: {title}"

                signals.append(TrendSignal(
                    source=SourceType.GOOGLE_TRENDS,
                    category="trending",
                    title=title,
                    content=content[:500],
                    search_term=title,
                    trend_direction="rising",
                    related_queries=[],
                    geo=geo,
                    value=traffic_num,
                    volume=traffic_num,
                    confidence=min(0.9, 0.3 + (traffic_num / 1_000_000) * 0.6),
                    direction=SignalDirection.EMERGING,
                    tags=["trending", "google", geo.lower()],
                    url=link if link else None,
                    metadata={"formatted_traffic": traffic_str, "rss_rank": i + 1},
                ))

        except ET.ParseError as e:
            log.warning(f"RSS XML parse error: {e}")

        return signals

    async def collect_interest(self, keywords: list[str], timeframe: str = "now 7-d", geo: str = "US") -> list[TrendSignal]:
        """
        Fetch interest-over-time for specific keywords.

        Uses pytrends if available, falls back to basic API call.
        """
        signals = []
        try:
            from pytrends.request import TrendReq
            pt = TrendReq(hl="en-US", tz=240)
            pt.build_payload(keywords[:5], cat=0, timeframe=timeframe, geo=geo)
            iot = pt.interest_over_time()

            if iot is not None and not iot.empty:
                for kw in keywords[:5]:
                    if kw in iot.columns:
                        values = iot[kw].tolist()
                        if len(values) >= 2:
                            current = values[-1]
                            previous = values[-2] if values[-2] > 0 else 1
                            change = ((current - previous) / previous) * 100
                            avg_val = sum(values) / len(values)

                            if change > 20:
                                direction = SignalDirection.EXPANDING
                            elif change < -20:
                                direction = SignalDirection.CONTRACTING
                            else:
                                direction = SignalDirection.NEUTRAL

                            signals.append(TrendSignal(
                                source=SourceType.GOOGLE_TRENDS,
                                category="interest",
                                title=f"Google Trends: {kw}",
                                content=f"{kw} interest {'up' if change > 0 else 'down'} {abs(change):.0f}% over period. Current={current}, avg={avg_val:.0f}",
                                search_term=kw,
                                trend_direction="rising" if change > 10 else "declining" if change < -10 else "stable",
                                geo=geo,
                                value=float(current),
                                change_pct=change,
                                volume=avg_val,
                                confidence=0.7,
                                direction=direction,
                                tags=["interest", "google_trends", kw.lower().replace(" ", "_")],
                            ))
        except ImportError:
            log.info("pytrends not installed — skipping interest_over_time (pip install pytrends)")
        except Exception as e:
            log.warning(f"Google Trends interest collection failed: {e}")

        return signals

    def _parse_traffic(self, traffic_str: str) -> float:
        """Parse '500K+', '2M+' etc. to float."""
        s = traffic_str.replace("+", "").replace(",", "").strip()
        if s.endswith("K"):
            return float(s[:-1]) * 1_000
        elif s.endswith("M"):
            return float(s[:-1]) * 1_000_000
        elif s.endswith("B"):
            return float(s[:-1]) * 1_000_000_000
        try:
            return float(s)
        except ValueError:
            return 0.0

    async def close(self):
        await self._client.aclose()


# ═══════════════════════════════════════════════════════════════════════════
# 2. POLYMARKET COLLECTOR
# ═══════════════════════════════════════════════════════════════════════════


class PolymarketCollector:
    """
    Fetch prediction market data from Polymarket's public APIs.

    Extracts crowd-implied probabilities and high-volume markets
    as forward-looking intelligence signals.
    No API key required for read access.
    """

    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "NCL-Intelligence/1.0"},
        )
        self._limiter = _RateLimiter(calls_per_minute=15)

    async def collect_trending_markets(self, limit: int = 30) -> list[PredictionMarketSignal]:
        """Fetch highest-volume active markets as probability signals."""
        signals = []
        try:
            data = await _fetch_json(
                self._client,
                f"{self.GAMMA_API}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "order": "volume24hr",
                    "ascending": "false",
                    "limit": limit,
                },
                limiter=self._limiter,
            )

            if not isinstance(data, list):
                return signals

            for event in data:
                title = event.get("title", "")
                markets = event.get("markets", [])
                vol_24h = float(event.get("volume_24hr", 0) or 0)
                total_vol = float(event.get("volume", 0) or 0)
                liquidity = float(event.get("liquidity", 0) or 0)
                tags_raw = event.get("tags", [])
                tag_labels = [t.get("label", "") for t in tags_raw if isinstance(t, dict)]
                slug = event.get("slug", "")

                # ── Deduplicate: pick ONE representative market per event ──
                # For multi-outcome events (e.g. "Who wins the election?"
                # with markets for each candidate), pick the highest-volume
                # individual market. For binary events, there's typically
                # just one market anyway.
                best_mkt = None
                best_mkt_vol = -1.0
                for mkt in markets:
                    mkt_vol = float(mkt.get("volume", 0) or 0)
                    if mkt_vol > best_mkt_vol:
                        best_mkt = mkt
                        best_mkt_vol = mkt_vol

                # If no individual market volumes, just take the first
                if best_mkt is None and markets:
                    best_mkt = markets[0]

                if best_mkt is None:
                    continue

                question = best_mkt.get("question", title)
                raw_prices = best_mkt.get("outcomePrices", "0.5,0.5")
                yes_price = self._parse_yes_price(raw_prices)
                no_price = 1.0 - yes_price

                # Price change from 24h ago (if available)
                price_change_24h = None
                prev_price_str = best_mkt.get("oneDayPriceChange")
                if prev_price_str:
                    try:
                        price_change_24h = float(prev_price_str) * 100  # to percentage
                    except (ValueError, TypeError):
                        pass

                # Determine direction from probability
                if yes_price > 0.7:
                    direction = SignalDirection.BULLISH
                elif yes_price < 0.3:
                    direction = SignalDirection.BEARISH
                else:
                    direction = SignalDirection.NEUTRAL

                signals.append(PredictionMarketSignal(
                    source=SourceType.POLYMARKET,
                    category=self._categorize_event(title, tag_labels),
                    title=question[:200],
                    content=f"Polymarket: {question} — YES={yes_price:.1%}, NO={no_price:.1%}, 24h vol=${vol_24h:,.0f}",
                    market_question=question,
                    yes_price=yes_price,
                    no_price=no_price,
                    market_volume=total_vol,
                    volume_24h=vol_24h,
                    price_change_24h=price_change_24h,
                    value=yes_price,
                    volume=vol_24h,
                    change_pct=price_change_24h,
                    direction=direction,
                    confidence=min(0.9, 0.3 + (vol_24h / 1_000_000) * 0.3 + (liquidity / 500_000) * 0.2),
                    tags=["polymarket", "prediction"] + [t.lower() for t in tag_labels[:5]],
                    url=f"https://polymarket.com/event/{slug}",
                    metadata={
                        "event_slug": slug,
                        "liquidity": liquidity,
                        "total_volume": total_vol,
                        "num_outcomes": len(markets),
                    },
                ))

        except Exception as e:
            log.warning(f"Polymarket collection failed: {e}")

        return signals

    async def collect_specific_markets(self, keywords: list[str]) -> list[PredictionMarketSignal]:
        """Search Polymarket for specific topic markets."""
        signals = []
        for kw in keywords:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.GAMMA_API}/markets",
                    params={"_q": kw, "active": "true", "closed": "false", "limit": 5},
                    limiter=self._limiter,
                )
                if isinstance(data, list):
                    for mkt in data:
                        question = mkt.get("question", "")
                        yes_price = self._parse_yes_price(mkt.get("outcomePrices", "0.5,0.5"))
                        vol = float(mkt.get("volume", 0) or 0)

                        signals.append(PredictionMarketSignal(
                            source=SourceType.POLYMARKET,
                            category=kw.lower(),
                            title=question[:200],
                            content=f"{question} — {yes_price:.1%} YES, vol=${vol:,.0f}",
                            market_question=question,
                            yes_price=yes_price,
                            no_price=1.0 - yes_price,
                            market_volume=vol,
                            value=yes_price,
                            volume=vol,
                            confidence=min(0.85, 0.4 + (vol / 500_000) * 0.3),
                            tags=["polymarket", kw.lower()],
                        ))
            except Exception as e:
                log.warning(f"Polymarket search for '{kw}' failed: {e}")

        return signals

    def _parse_yes_price(self, raw: Any) -> float:
        """Parse outcomePrices field (JSON array string, CSV, or list)."""
        if isinstance(raw, list) and raw:
            try:
                return float(raw[0])
            except (ValueError, TypeError):
                return 0.5
        if isinstance(raw, str):
            cleaned = raw.strip().strip("[]")
            parts = [p.strip().strip('"\'') for p in cleaned.split(",")]
            if parts:
                try:
                    return float(parts[0])
                except ValueError:
                    pass
        return 0.5

    def _categorize_event(self, title: str, tags: list[str]) -> str:
        """Categorize event by topic with comprehensive keyword matching."""
        title_lower = title.lower()
        tag_str = " ".join(tags).lower()
        combined = title_lower + " " + tag_str

        # Quick pattern: "Team A vs. Team B" is almost always sports
        if " vs " in title_lower or " vs. " in title_lower:
            # Unless it's clearly something else
            if not any(k in combined for k in ["crypto", "bitcoin", "election", "ai ", "fed "]):
                return "sports"

        # Order matters — more specific categories first
        if any(k in combined for k in [
            "crypto", "bitcoin", "ethereum", "solana", "btc", "eth",
            "defi", "nft", "token", "blockchain", "web3", "stablecoin",
        ]):
            return "crypto"
        if any(k in combined for k in [
            "fed ", "federal reserve", "inflation", "interest rate", "gdp",
            "economy", "recession", "treasury", "cpi", "unemployment",
            "tariff", "trade war", "debt ceiling", "s&p", "dow jones",
            "nasdaq", "stock market", "bond", "yield curve",
        ]):
            return "macro"
        if any(k in combined for k in [
            "ai ", "artificial intelligence", "openai", "gpt", "llm",
            "machine learning", "anthropic", "deepmind", "nvidia ai",
            "agi", "chatgpt", "gemini ai", "claude",
        ]):
            return "ai_tech"
        if any(k in combined for k in [
            "election", "president", "congress", "senate", "governor",
            "politics", "democrat", "republican", "trump", "biden",
            "vote", "poll", "legislation", "supreme court", "geopolit",
            "war", "ceasefire", "ukraine", "russia", "china", "israel",
            "nato", "sanctions", "missile", "nuclear", "military",
            "hezbollah", "hamas", "iran",
        ]):
            return "politics"
        if any(k in combined for k in [
            "tech", "apple", "google", "microsoft", "amazon", "meta",
            "spacex", "tesla", "semiconductor", "chip", "iphone",
            "startup", "ipo", "acquisition", "merger",
        ]):
            return "tech"
        if any(k in combined for k in [
            "sport", "nba", "nfl", "mlb", "nhl", "soccer", "football",
            "cricket", "tennis", "golf", "ufc", "boxing", "mma",
            "world cup", "fifa", "olympics", "f1", "formula",
            "playoffs", "championship", "win the", "super bowl",
            "world series", "premier league", "champions league",
            "grand slam", "march madness",
        ]):
            return "sports"
        if any(k in combined for k in [
            "entertainment", "movie", "film", "oscars", "emmy",
            "grammy", "album", "song", "music", "artist",
            "eurovision", "gta", "game release", "box office",
            "streaming", "netflix", "disney", "tv show", "celebrity",
            "kardashian", "taylor swift", "drake", "kanye",
        ]):
            return "entertainment"
        if any(k in combined for k in [
            "climate", "weather", "hurricane", "earthquake", "wildfire",
            "temperature", "carbon", "renewable", "energy",
        ]):
            return "climate"
        if any(k in combined for k in [
            "covid", "pandemic", "vaccine", "fda", "drug",
            "health", "disease", "outbreak", "who ",
        ]):
            return "health"
        if any(k in combined for k in [
            "crude oil", "wti", "brent", "gold", "silver", "commodity",
            "wheat", "corn", "natural gas", "copper", "futures",
            "s&p 500", "nasdaq", "dow jones", "stock", "share price",
            "earnings", "market cap", "ipo", "etf", "index",
        ]):
            return "markets"
        # "hit $X" or "above $X" patterns suggest market/price events
        import re
        if re.search(r'(hit|above|below|reach|exceed)\s*\$[\d,]+', title_lower):
            return "markets"
        return "general"

    async def close(self):
        await self._client.aclose()


# ═══════════════════════════════════════════════════════════════════════════
# 3. NEWS COLLECTOR
# ═══════════════════════════════════════════════════════════════════════════


class NewsCollector:
    """
    Collect news headlines from free news APIs.

    Supports: GNews (free, no key needed for limited use),
    NewsAPI (requires key), or RSS fallback.
    """

    GNEWS_URL = "https://gnews.io/api/v4"

    def __init__(self, gnews_api_key: Optional[str] = None, newsapi_key: Optional[str] = None):
        self._gnews_key = gnews_api_key
        self._newsapi_key = newsapi_key
        self._client = httpx.AsyncClient(timeout=30.0)
        self._limiter = _RateLimiter(calls_per_minute=10)

    async def collect_top_headlines(self, category: str = "general", lang: str = "en") -> list[NewsSignal]:
        """Fetch top headlines."""
        signals = []

        # Try GNews first
        if self._gnews_key:
            signals = await self._collect_gnews(category, lang)

        # Try NewsAPI as fallback
        if not signals and self._newsapi_key:
            signals = await self._collect_newsapi(category, lang)

        return signals

    async def collect_topic_news(self, query: str, lang: str = "en") -> list[NewsSignal]:
        """Search news for a specific topic."""
        signals = []

        if self._gnews_key:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.GNEWS_URL}/search",
                    params={"q": query, "lang": lang, "max": 10, "apikey": self._gnews_key},
                    limiter=self._limiter,
                )
                for article in data.get("articles", []):
                    signals.append(self._article_to_signal(article, query))
            except Exception as e:
                log.warning(f"GNews topic search for '{query}' failed: {e}")

        if not signals and self._newsapi_key:
            try:
                data = await _fetch_json(
                    self._client,
                    "https://newsapi.org/v2/everything",
                    params={"q": query, "language": lang, "pageSize": 10, "sortBy": "relevancy"},
                    headers={"X-Api-Key": self._newsapi_key},
                    limiter=self._limiter,
                )
                for article in data.get("articles", []):
                    signals.append(self._article_to_signal(article, query))
            except Exception as e:
                log.warning(f"NewsAPI topic search for '{query}' failed: {e}")

        return signals

    async def _collect_gnews(self, category: str, lang: str) -> list[NewsSignal]:
        signals = []
        try:
            data = await _fetch_json(
                self._client,
                f"{self.GNEWS_URL}/top-headlines",
                params={"category": category, "lang": lang, "max": 10, "apikey": self._gnews_key},
                limiter=self._limiter,
            )
            for article in data.get("articles", []):
                signals.append(self._article_to_signal(article, category))
        except Exception as e:
            log.warning(f"GNews headlines failed: {e}")
        return signals

    async def _collect_newsapi(self, category: str, lang: str) -> list[NewsSignal]:
        signals = []
        try:
            data = await _fetch_json(
                self._client,
                "https://newsapi.org/v2/top-headlines",
                params={"category": category, "language": lang, "pageSize": 10},
                headers={"X-Api-Key": self._newsapi_key},
                limiter=self._limiter,
            )
            for article in data.get("articles", []):
                signals.append(self._article_to_signal(article, category))
        except Exception as e:
            log.warning(f"NewsAPI headlines failed: {e}")
        return signals

    def _article_to_signal(self, article: dict, topic: str) -> NewsSignal:
        title = article.get("title", "")
        description = article.get("description", "") or ""
        source_name = article.get("source", {}).get("name", "") if isinstance(article.get("source"), dict) else str(article.get("source", ""))

        # Basic sentiment from title keywords
        sentiment = self._quick_sentiment(title + " " + description)

        if sentiment > 0.3:
            direction = SignalDirection.BULLISH
        elif sentiment < -0.3:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL

        return NewsSignal(
            source=SourceType.NEWS,
            category=topic,
            title=title[:200],
            content=description[:500],
            headline=title,
            source_name=source_name,
            sentiment=sentiment,
            direction=direction,
            confidence=0.5,
            url=article.get("url", ""),
            tags=["news", topic.lower()],
        )

    def _quick_sentiment(self, text: str) -> float:
        """Ultra-simple keyword sentiment. -1 to 1."""
        text_lower = text.lower()
        positive = ["surge", "rally", "boom", "soar", "gain", "record high", "breakthrough",
                     "bullish", "growth", "expand", "optimis", "strong"]
        negative = ["crash", "plunge", "crisis", "collapse", "sell-off", "bearish", "recession",
                     "decline", "fear", "risk", "warning", "drop", "fall", "worst"]

        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return (pos_count - neg_count) / total

    async def close(self):
        await self._client.aclose()


# ═══════════════════════════════════════════════════════════════════════════
# 4. CRYPTO MARKET COLLECTOR (CoinGecko free tier)
# ═══════════════════════════════════════════════════════════════════════════


class CryptoMarketCollector:
    """
    Fetch crypto market data from CoinGecko (free, no key needed).

    Includes price, volume, market cap, and basic technical indicators.
    """

    BASE_URL = "https://api.coingecko.com/api/v3"

    TRACKED_COINS = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "solana": "SOL",
        "cardano": "ADA",
        "ripple": "XRP",
        "dogecoin": "DOGE",
        "avalanche-2": "AVAX",
        "chainlink": "LINK",
    }

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        self._limiter = _RateLimiter(calls_per_minute=10)  # CoinGecko free = ~10-30/min

    async def collect_market_overview(self) -> list[MarketSignal]:
        """Fetch current prices and 24h changes for tracked coins."""
        signals = []
        try:
            ids = ",".join(self.TRACKED_COINS.keys())
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": ids,
                    "order": "market_cap_desc",
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h,7d,30d",
                },
                limiter=self._limiter,
            )

            if not isinstance(data, list):
                return signals

            for coin in data:
                coin_id = coin.get("id", "")
                symbol = self.TRACKED_COINS.get(coin_id, coin.get("symbol", "").upper())
                price = float(coin.get("current_price", 0) or 0)
                change_24h = float(coin.get("price_change_percentage_24h", 0) or 0)
                change_7d = float(coin.get("price_change_percentage_7d_in_currency", 0) or 0)
                change_30d = float(coin.get("price_change_percentage_30d_in_currency", 0) or 0)
                volume = float(coin.get("total_volume", 0) or 0)
                market_cap = float(coin.get("market_cap", 0) or 0)
                high_24h = float(coin.get("high_24h", 0) or 0)
                low_24h = float(coin.get("low_24h", 0) or 0)
                ath = float(coin.get("ath", 0) or 0)

                # Direction from 7d trend
                if change_7d > 10:
                    direction = SignalDirection.BULLISH
                elif change_7d < -10:
                    direction = SignalDirection.BEARISH
                elif change_7d > 3:
                    direction = SignalDirection.EXPANDING
                elif change_7d < -3:
                    direction = SignalDirection.CONTRACTING
                else:
                    direction = SignalDirection.NEUTRAL

                signals.append(MarketSignal(
                    source=SourceType.CRYPTO,
                    category="crypto",
                    title=f"{symbol} ${price:,.2f} ({change_24h:+.1f}%)",
                    content=(
                        f"{symbol}: ${price:,.2f} | 24h: {change_24h:+.1f}% | "
                        f"7d: {change_7d:+.1f}% | 30d: {change_30d:+.1f}% | "
                        f"Vol: ${volume:,.0f} | MCap: ${market_cap:,.0f}"
                    ),
                    symbol=symbol,
                    current_price=price,
                    high_period=high_24h,
                    low_period=low_24h,
                    market_cap=market_cap,
                    value=price,
                    change_pct=change_24h,
                    volume=volume,
                    direction=direction,
                    confidence=0.85,  # Hard data, high confidence
                    tags=["crypto", symbol.lower(), "market_data"],
                    metadata={
                        "change_7d": change_7d,
                        "change_30d": change_30d,
                        "ath": ath,
                        "ath_distance_pct": ((price - ath) / ath * 100) if ath > 0 else 0,
                    },
                ))

        except Exception as e:
            log.warning(f"CoinGecko market overview failed: {e}")

        return signals

    async def collect_trending(self) -> list[MarketSignal]:
        """Fetch CoinGecko trending coins (what's hot in crypto)."""
        signals = []
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/search/trending",
                limiter=self._limiter,
            )
            coins = data.get("coins", [])
            for item in coins[:10]:
                coin = item.get("item", {})
                name = coin.get("name", "")
                symbol = coin.get("symbol", "")
                score = coin.get("score", 0)
                price_btc = float(coin.get("price_btc", 0) or 0)
                market_cap_rank = coin.get("market_cap_rank")

                signals.append(MarketSignal(
                    source=SourceType.CRYPTO,
                    category="crypto_trending",
                    title=f"Trending: {name} ({symbol})",
                    content=f"{name} ({symbol}) trending on CoinGecko. Rank #{score+1}. MCap rank: {market_cap_rank}",
                    symbol=symbol,
                    value=float(score),
                    direction=SignalDirection.EMERGING,
                    confidence=0.6,
                    tags=["crypto", "trending", symbol.lower()],
                    metadata={"market_cap_rank": market_cap_rank, "price_btc": price_btc},
                ))

        except Exception as e:
            log.warning(f"CoinGecko trending failed: {e}")

        return signals

    async def collect_global_metrics(self) -> list[IntelSignal]:
        """Fetch global crypto market metrics (total mcap, dominance, etc)."""
        signals = []
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/global",
                limiter=self._limiter,
            )
            gdata = data.get("data", {})

            total_mcap = float(gdata.get("total_market_cap", {}).get("usd", 0) or 0)
            total_vol = float(gdata.get("total_volume", {}).get("usd", 0) or 0)
            btc_dom = float(gdata.get("market_cap_percentage", {}).get("btc", 0) or 0)
            eth_dom = float(gdata.get("market_cap_percentage", {}).get("eth", 0) or 0)
            mcap_change = float(gdata.get("market_cap_change_percentage_24h_usd", 0) or 0)

            if mcap_change > 3:
                direction = SignalDirection.EXPANDING
            elif mcap_change < -3:
                direction = SignalDirection.CONTRACTING
            else:
                direction = SignalDirection.NEUTRAL

            signals.append(IntelSignal(
                source=SourceType.CRYPTO,
                category="crypto_global",
                title=f"Crypto Market: ${total_mcap/1e12:.2f}T ({mcap_change:+.1f}%)",
                content=(
                    f"Total crypto market cap: ${total_mcap/1e12:.2f}T ({mcap_change:+.1f}% 24h). "
                    f"BTC dominance: {btc_dom:.1f}%. ETH dominance: {eth_dom:.1f}%. "
                    f"24h volume: ${total_vol/1e9:.1f}B."
                ),
                value=total_mcap,
                change_pct=mcap_change,
                volume=total_vol,
                direction=direction,
                confidence=0.9,
                tags=["crypto", "global", "market_cap"],
                metadata={"btc_dominance": btc_dom, "eth_dominance": eth_dom},
            ))

        except Exception as e:
            log.warning(f"CoinGecko global metrics failed: {e}")

        return signals

    async def close(self):
        await self._client.aclose()


# ═══════════════════════════════════════════════════════════════════════════
# RSI/MACD helpers (from AAC daily_recommendation_engine pattern)
# ═══════════════════════════════════════════════════════════════════════════

def compute_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index. Returns 0-100 or None."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema(prices: list[float], period: int) -> Optional[float]:
    """Exponential Moving Average."""
    if len(prices) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def compute_macd(prices: list[float]) -> Optional[tuple[float, float, float]]:
    """MACD line, signal line, histogram."""
    if len(prices) < 35:
        return None
    fast_ema = compute_ema(prices, 12)
    slow_ema = compute_ema(prices, 26)
    if fast_ema is None or slow_ema is None:
        return None
    macd_line = fast_ema - slow_ema
    macd_vals = []
    for i in range(26, len(prices)):
        subset = prices[:i + 1]
        f = compute_ema(subset, 12)
        s = compute_ema(subset, 26)
        if f is not None and s is not None:
            macd_vals.append(f - s)
    if len(macd_vals) < 9:
        return None
    signal_line = sum(macd_vals[-9:]) / 9
    return macd_line, signal_line, macd_line - signal_line


# ═══════════════════════════════════════════════════════════════════════════
# 5. REDDIT COLLECTOR (Public JSON API — no key needed)
# ═══════════════════════════════════════════════════════════════════════════


class RedditCollector:
    """
    Scan Reddit subreddits for retail investor sentiment and emerging signals.

    Uses Reddit's public JSON endpoints (append .json to any URL).
    No API key required. Rate limit: ~30 req/min with User-Agent.

    Primary targets: r/wallstreetbets, r/Superstonk
    These subreddits are leading indicators for:
      - Retail squeeze plays and YOLO momentum
      - GME/meme stock sentiment shifts
      - Options flow sentiment (gain/loss porn = conviction gauge)
      - Emerging ticker mentions before mainstream coverage
    """

    BASE_URL = "https://www.reddit.com"

    # ── Tiered subreddit network ──────────────────────────────────
    # TIER 1: Scanned every cycle (hot + top + rising) — core alpha sources
    TIER1_SUBS = [
        "wallstreetbets",       # 19.9M — retail HQ, YOLO culture
        "Superstonk",           # 1.2M  — GME deep DD, DRS movement
        "options",              # 1.4M  — options flow, strategies
        "stocks",               # 9.2M  — general equity discussion
        "StockMarket",          # 4.0M  — market-wide sentiment
        "Daytrading",           # 5.1M  — intraday momentum
        "unusual_whales",       # 250K  — unusual options activity
        "GME",                  # 469K  — dedicated GME intel
        "Shortsqueeze",         # 378K  — squeeze play detection
        "pennystocks",          # 2.2M  — small cap momentum
    ]

    # TIER 2: Scanned every cycle (hot only) — strong supporting intel
    TIER2_SUBS = [
        "thetagang",            # 325K  — options sellers / premium
        "amcstock",             # 522K  — AMC / meme stock sentiment
        "DeepFuckingValue",     # 308K  — DFV / GME culture
        "investing",            # 3.3M  — longer-term sentiment
        "ValueInvesting",       # 714K  — value plays
        "swingtrading",         # 162K  — multi-day setups
        "smallstreetbets",      # 456K  — small account YOLOs
        "WallStreetbetsELITE",  # 700K  — WSB overflow
        "FluentInFinance",      # 571K  — financial news/analysis
        "TheRaceTo10Million",   # 561K  — aggressive growth plays
        "SatoshiStreetBets",    # 759K  — crypto YOLO culture
        "CryptoCurrency",      # 10.1M — crypto sentiment
        "Bitcoin",              # 8.1M  — BTC sentiment
        "RealDayTrading",       # 128K  — serious day trading DD
        "DDintoGME",            # 65K   — deep GME research
        "SqueezePlays",         # 47K   — active squeeze hunting
    ]

    # TIER 3: Rotated scan (5 per cycle) — broader context
    TIER3_SUBS = [
        "ethereum",             # 3.7M  — ETH ecosystem
        "CryptoMoonShots",      # 2.3M  — speculative crypto
        "economics",            # 5.7M  — macro context
        "economy",              # 1.1M  — economic indicators
        "finance",              # 2.1M  — general finance
        "wallstreet",           # 97K   — Wall Street culture
        "dividends",            # 859K  — income investing
        "Bogleheads",           # 829K  — index investing sentiment
        "financialindependence", # 2.4M — FIRE movement
        "algotrading",          # 1.9M  — quant / algo strategies
        "Forex",                # 525K  — FX markets
        "FuturesTrading",       # 181K  — futures flow
        "quant",                # 187K  — quantitative finance
        "SPACs",                # 177K  — SPAC deals
        "weedstocks",           # 267K  — cannabis sector
        "Biotechplays",         # 22K   — biotech catalysts
        "Semiconductors",       # 31K   — chip sector
        "Vitards",              # 48K   — steel/commodities DD
        "CanadianInvestor",     # 650K  — Canadian markets
        "AusFinance",           # 805K  — Australian markets
        "UKInvesting",          # 236K  — UK markets
        "Optionswheel",         # 48K   — wheel strategy
        "optionstrading",       # 31K   — options education
        "MillennialBets",       # 12K   — millennial traders
        "FinancialPlanning",    # 976K  — planning / macro
        "EducatedInvesting",    # 95K   — investment education
        "BBBY",                 # 67K   — meme stock archive
        "maxjustrisk",          # 7K    — risk analysis DD
        "personalfinance",      # 21.7M — consumer sentiment
    ]

    # All subreddits combined
    ALL_SUBREDDITS = TIER1_SUBS + TIER2_SUBS + TIER3_SUBS

    # Flair categories that carry high signal value
    HIGH_SIGNAL_FLAIRS = {
        # WSB
        "dd", "due diligence", "technical analysis", "yolo",
        "gain", "loss", "news", "discussion", "catalyst",
        # Superstonk
        "📚 due diligence", "📈 technical analysis", "☁ hype/ fluff",
        "📰 news", "💡 education", "📳social media", "🤔 speculation / opinion",
        # Options
        "strategy", "trade idea", "unusual activity",
        # General
        "research", "analysis", "breaking",
    }

    # Keywords that indicate actionable intelligence
    ALPHA_KEYWORDS = [
        "squeeze", "short interest", "dark pool", "ftd", "failure to deliver",
        "options chain", "gamma ramp", "max pain", "drs", "citadel",
        "market maker", "pfof", "payment for order flow", "sec filing",
        "13f", "insider", "whale", "unusual volume", "breakout",
        "earnings", "catalyst", "merger", "acquisition", "buyback",
        "dilution", "offering", "reverse split", "margin call",
        "unusual whales", "options flow", "call sweep", "put sweep",
        "block trade", "golden cross", "death cross", "support",
        "resistance", "fibonacci", "cup and handle", "head and shoulders",
        "short ladder", "naked short", "reg sho", "threshold list",
    ]

    # Tier 3 rotation tracker
    _tier3_offset: int = 0

    def __init__(self, subreddits: list[str] | None = None, tier: str = "all"):
        """
        Initialize Reddit collector.

        Args:
            subreddits: Override list (ignores tiers). None = use tiered system.
            tier: Which tiers to scan: "all", "t1", "t2", "t1t2", or "full" (all 55+)
        """
        if subreddits:
            self.subreddits = subreddits
            self._use_tiers = False
        else:
            self._use_tiers = True
            self._tier = tier
            self.subreddits = self._build_scan_list()
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "NCL-Brain-Intelligence/1.0 (by /u/ncl-intel-bot)",
            },
            follow_redirects=True,
        )
        self._limiter = _RateLimiter(calls_per_minute=25)

    def _build_scan_list(self) -> list[str]:
        """Build subreddit list based on tier config."""
        if self._tier == "t1":
            return list(self.TIER1_SUBS)
        elif self._tier == "t2":
            return list(self.TIER2_SUBS)
        elif self._tier == "t1t2":
            return list(self.TIER1_SUBS) + list(self.TIER2_SUBS)
        elif self._tier == "full":
            return list(self.ALL_SUBREDDITS)
        else:  # "all" — tiered: T1 full, T2 hot-only, T3 rotating 5
            subs = list(self.TIER1_SUBS) + list(self.TIER2_SUBS)
            # Rotate through tier 3: pick 5 per scan cycle
            t3_len = len(self.TIER3_SUBS)
            if t3_len > 0:
                start = RedditCollector._tier3_offset % t3_len
                rotating = []
                for i in range(5):
                    rotating.append(self.TIER3_SUBS[(start + i) % t3_len])
                subs.extend(rotating)
                RedditCollector._tier3_offset += 5
            return subs

    async def collect_all(self) -> list[SocialSignal]:
        """
        Run tiered scan across financial subreddit network.

        Tier 1 (10 subs): hot + top daily + rising — full depth
        Tier 2 (16 subs): hot only — faster sweep
        Tier 3 (29 subs): 5 per cycle, rotating — broad context
        """
        all_signals: list[SocialSignal] = []
        scan_list = self.subreddits if not self._use_tiers else self._build_scan_list()

        # Batch subs into concurrent groups of 5 to manage rate limits
        batch_size = 5
        for batch_start in range(0, len(scan_list), batch_size):
            batch = scan_list[batch_start:batch_start + batch_size]
            tasks = []

            for sub in batch:
                is_tier1 = sub in self.TIER1_SUBS
                if is_tier1 or not self._use_tiers:
                    # Full scan for tier 1 or custom subreddit list
                    tasks.append(self._scan_sub_full(sub))
                else:
                    # Hot-only scan for tier 2/3
                    tasks.append(self._scan_sub_hot(sub))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_signals.extend(result)
                elif isinstance(result, Exception):
                    log.warning(f"Reddit batch scan error: {result}")



        # Deduplicate by post ID
        seen_ids: set[str] = set()
        deduped: list[SocialSignal] = []
        for sig in all_signals:
            post_id = sig.metadata.get("post_id", "")
            if post_id and post_id not in seen_ids:
                seen_ids.add(post_id)
                deduped.append(sig)
            elif not post_id:
                deduped.append(sig)

        log.info(
            f"Reddit scan: {len(deduped)} unique signals from {len(scan_list)} subs "
            f"(T1={len(self.TIER1_SUBS)}, T2={len(self.TIER2_SUBS)}, "
            f"T3 rotating={len(self.TIER3_SUBS)})"
        )
        return deduped

    async def _scan_sub_full(self, sub: str) -> list[SocialSignal]:
        """Full-depth scan: hot + top daily + rising."""
        signals: list[SocialSignal] = []
        try:
            hot, top, rising = await asyncio.gather(
                self._collect_listing(sub, "hot", limit=25),
                self._collect_listing(sub, "top", limit=15, params={"t": "day"}),
                self._collect_listing(sub, "rising", limit=10),
                return_exceptions=True,
            )
            for result in [hot, top, rising]:
                if isinstance(result, list):
                    signals.extend(result)
                elif isinstance(result, Exception):
                    log.warning(f"Reddit r/{sub} partial scan failed: {result}")
        except Exception as e:
            log.warning(f"Reddit r/{sub} full scan failed: {e}")
        return signals

    async def _scan_sub_hot(self, sub: str) -> list[SocialSignal]:
        """Quick scan: hot posts only."""
        try:
            return await self._collect_listing(sub, "hot", limit=15)
        except Exception as e:
            log.warning(f"Reddit r/{sub} hot scan failed: {e}")
            return []

    async def _collect_listing(
        self,
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
        params: dict | None = None,
    ) -> list[SocialSignal]:
        """Fetch a subreddit listing (hot/top/rising/new) and convert to signals."""
        signals: list[SocialSignal] = []

        url = f"{self.BASE_URL}/r/{subreddit}/{sort}.json"
        query = {"limit": limit, "raw_json": 1}
        if params:
            query.update(params)

        try:
            data = await _fetch_json(
                self._client, url, params=query, limiter=self._limiter
            )
        except Exception as e:
            log.warning(f"Reddit r/{subreddit}/{sort} fetch failed: {e}")
            return signals

        children = data.get("data", {}).get("children", [])

        for post in children:
            post_data = post.get("data", {})
            if not post_data:
                continue

            # Skip stickied/pinned mod posts (usually daily threads)
            if post_data.get("stickied", False):
                continue

            signal = self._post_to_signal(post_data, subreddit, sort)
            if signal:
                signals.append(signal)

        return signals

    def _post_to_signal(self, post: dict, subreddit: str, listing_type: str) -> SocialSignal | None:
        """Convert a Reddit post to a SocialSignal."""
        title = post.get("title", "")
        selftext = post.get("selftext", "")[:1000]  # Cap body text
        author = post.get("author", "[deleted]")
        score = int(post.get("score", 0))
        num_comments = int(post.get("num_comments", 0))
        upvote_ratio = float(post.get("upvote_ratio", 0.5))
        flair = (post.get("link_flair_text") or "").strip()
        created_utc = float(post.get("created_utc", post.get("created", 0)))
        post_id = post.get("name", "")  # e.g., "t3_abc123"
        permalink = post.get("permalink", "")
        is_self = post.get("is_self", False)

        # Engagement = score + comments (weighted — comments show deeper engagement)
        engagement = score + (num_comments * 3)

        # Calculate signal strength: high-score + high-engagement = strong signal
        # WSB posts with 1000+ score are significant; 5000+ are viral
        if score >= 5000:
            strength = "viral"
            confidence = 0.85
        elif score >= 1000:
            strength = "hot"
            confidence = 0.7
        elif score >= 200:
            strength = "warm"
            confidence = 0.5
        else:
            strength = "emerging"
            confidence = 0.35

        # Boost confidence for high-signal flairs (DD, YOLO, etc.)
        flair_lower = flair.lower()
        is_high_signal = any(hf in flair_lower for hf in self.HIGH_SIGNAL_FLAIRS)
        if is_high_signal:
            confidence = min(0.95, confidence + 0.15)

        # Extract ticker mentions ($GME, $AMC, etc.)
        import re
        tickers = list(set(re.findall(r'\$([A-Z]{1,5})\b', title + " " + selftext)))

        # Check for alpha keywords in title/body
        combined_text = (title + " " + selftext).lower()
        alpha_hits = [kw for kw in self.ALPHA_KEYWORDS if kw in combined_text]

        if alpha_hits:
            confidence = min(0.95, confidence + 0.1)

        # Sentiment from upvote ratio and flair
        sentiment = self._estimate_sentiment(title, selftext, flair, upvote_ratio)

        # Direction
        if sentiment > 0.3:
            direction = SignalDirection.BULLISH
        elif sentiment < -0.3:
            direction = SignalDirection.BEARISH
        elif listing_type == "rising":
            direction = SignalDirection.EMERGING
        else:
            direction = SignalDirection.NEUTRAL

        # Build content summary
        content_parts = [f"r/{subreddit} [{flair}]" if flair else f"r/{subreddit}"]
        content_parts.append(f"Score: {score:,} | Comments: {num_comments:,} | Ratio: {upvote_ratio:.0%}")
        if tickers:
            content_parts.append(f"Tickers: {', '.join('$'+t for t in tickers[:5])}")
        if alpha_hits:
            content_parts.append(f"Keywords: {', '.join(alpha_hits[:3])}")
        if selftext and is_self:
            # Include first 200 chars of body for DD posts
            content_parts.append(f"Body: {selftext[:200].strip()}...")

        return SocialSignal(
            source=SourceType.REDDIT,
            category=self._categorize_post(subreddit, flair, title, tickers),
            title=title[:200],
            content=" | ".join(content_parts)[:500],
            platform="reddit",
            engagement=engagement,
            author_followers=0,  # Not available from public API
            sentiment=sentiment,
            value=float(score),
            volume=float(num_comments),
            change_pct=None,
            direction=direction,
            confidence=confidence,
            url=f"https://www.reddit.com{permalink}" if permalink else None,
            tags=self._build_tags(subreddit, flair, tickers, listing_type, strength),
            metadata={
                "post_id": post_id,
                "subreddit": subreddit,
                "author": author,
                "score": score,
                "num_comments": num_comments,
                "upvote_ratio": upvote_ratio,
                "flair": flair,
                "listing_type": listing_type,
                "strength": strength,
                "tickers": tickers,
                "alpha_keywords": alpha_hits,
                "is_dd": is_high_signal,
                "created_utc": created_utc,
            },
        )

    def _estimate_sentiment(self, title: str, body: str, flair: str, upvote_ratio: float) -> float:
        """Estimate post sentiment from text, flair, and engagement signals."""
        text = (title + " " + body).lower()
        flair_lower = flair.lower()

        # Flair-based sentiment
        if any(f in flair_lower for f in ["gain", "bullish", "yolo"]):
            base = 0.5
        elif any(f in flair_lower for f in ["loss", "bearish"]):
            base = -0.3
        elif any(f in flair_lower for f in ["dd", "due diligence", "education"]):
            base = 0.2  # DD is generally constructive/bullish
        else:
            base = 0.0

        # Keyword-based adjustment
        bullish_words = [
            "moon", "rocket", "squeeze", "tendies", "diamond hands",
            "bullish", "calls", "buy", "long", "undervalued", "breakout",
            "gamma", "ramp", "drs", "moass", "lfg", "to the moon",
            "all in", "yolo", "send it",
        ]
        bearish_words = [
            "puts", "short", "crash", "dump", "sell", "overvalued",
            "bearish", "rip", "bag hold", "loss porn", "margin call",
            "rug pull", "scam", "dilution", "offering",
        ]

        bull_count = sum(1 for w in bullish_words if w in text)
        bear_count = sum(1 for w in bearish_words if w in text)
        total = bull_count + bear_count

        if total > 0:
            keyword_sentiment = (bull_count - bear_count) / total * 0.5
        else:
            keyword_sentiment = 0.0

        # Upvote ratio adjustment: high ratio = community agrees with sentiment
        ratio_boost = (upvote_ratio - 0.5) * 0.3

        sentiment = base + keyword_sentiment + ratio_boost
        return max(-1.0, min(1.0, sentiment))

    def _categorize_post(self, subreddit: str, flair: str, title: str, tickers: list[str]) -> str:
        """Categorize post for NCL intelligence bucketing."""
        flair_lower = flair.lower()
        title_lower = title.lower()

        if any(f in flair_lower for f in ["dd", "due diligence"]):
            return "retail_dd"
        if any(f in flair_lower for f in ["yolo"]):
            return "retail_yolo"
        if any(f in flair_lower for f in ["gain"]):
            return "retail_gain"
        if any(f in flair_lower for f in ["loss"]):
            return "retail_loss"
        if any(f in flair_lower for f in ["technical analysis"]):
            return "retail_ta"
        if any(f in flair_lower for f in ["news", "social media"]):
            return "retail_news"
        if any(f in flair_lower for f in ["meme", "shitpost", "hype"]):
            return "retail_meme"
        if "gme" in title_lower or "$gme" in title_lower or "gamestop" in title_lower:
            return "gme_intel"
        if tickers:
            return "retail_ticker"
        return "retail_general"

    def _build_tags(
        self, subreddit: str, flair: str, tickers: list[str],
        listing_type: str, strength: str,
    ) -> list[str]:
        """Build tag list for signal."""
        tags = ["reddit", subreddit.lower(), listing_type, strength]
        if flair:
            # Normalize flair to tag-safe string
            flair_tag = flair.lower().replace(" ", "_").replace("/", "_")
            # Strip emoji
            import re
            flair_tag = re.sub(r'[^\w_]', '', flair_tag).strip("_")
            if flair_tag:
                tags.append(f"flair:{flair_tag}")
        for ticker in tickers[:3]:
            tags.append(f"ticker:{ticker.lower()}")
        return tags

    async def collect_ticker_mentions(self, subreddit: str = "wallstreetbets", limit: int = 100) -> dict[str, int]:
        """
        Scan a subreddit and count ticker mentions.
        Returns dict of ticker -> mention count, sorted by frequency.
        Useful for detecting emerging retail favorites.
        """
        import re
        ticker_counts: dict[str, int] = {}

        url = f"{self.BASE_URL}/r/{subreddit}/hot.json"
        try:
            data = await _fetch_json(
                self._client, url, params={"limit": limit, "raw_json": 1},
                limiter=self._limiter,
            )
        except Exception as e:
            log.warning(f"Reddit ticker scan failed: {e}")
            return ticker_counts

        # Common false positives to filter out
        noise_tickers = {
            "DD", "TA", "USA", "CEO", "CFO", "CTO", "IPO", "SEC", "FDA",
            "ETF", "OTC", "IMO", "FYI", "ATH", "ATL", "OG", "USD", "EUR",
            "API", "AI", "EPS", "PE", "IV", "DTE", "ITM", "OTM", "WSB",
            "GME", "DRS", "MOASS", "PFOF", "FTD", "SI", "YOLO", "LOL",
            "RIP", "HODL", "BRO", "LMAO", "PDF", "ALL", "NEW", "TOP",
        }
        # GME is special — keep it for Superstonk context
        if subreddit.lower() == "superstonk":
            noise_tickers.discard("GME")

        for post in data.get("data", {}).get("children", []):
            pd = post.get("data", {})
            text = pd.get("title", "") + " " + (pd.get("selftext", "") or "")
            found = re.findall(r'\$([A-Z]{1,5})\b', text)
            for ticker in found:
                if ticker not in noise_tickers:
                    ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

        # Sort by count descending
        return dict(sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True))

    async def close(self):
        await self._client.aclose()
