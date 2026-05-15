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
    """Sliding-window rate limiter supporting arbitrary windows."""

    def __init__(self, calls: int = 10, window_seconds: int = 60):
        """
        Args:
            calls: Maximum calls allowed in the window.
            window_seconds: Window length in seconds (default 60 = per-minute).
        """
        self.calls = calls
        self.window = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            wait_time = 0.0
            async with self._lock:
                now = time.monotonic()
                self._timestamps = [t for t in self._timestamps if now - t < self.window]
                if len(self._timestamps) >= self.calls:
                    wait_time = self.window - (now - self._timestamps[0])
                else:
                    self._timestamps.append(time.monotonic())
                    return
            # Sleep outside the lock so other requests aren't blocked
            if wait_time > 0:
                await asyncio.sleep(wait_time)


class SafeAPIError(Exception):
    """
    Sanitized HTTP error — status + URL only, never the response body.

    Upstream APIs may include attacker-controlled text in error bodies
    (e.g. UW 401 contains a prompt-injection payload aimed at AI agents).
    Raising this instead of httpx.HTTPStatusError prevents that payload
    from reaching log files, stack traces, or downstream LLM context.
    """

    def __init__(self, status_code: int, url: str):
        self.status_code = status_code
        # Strip query string — may also be sensitive (api keys in some APIs)
        clean_url = url.split("?", 1)[0]
        self.url = clean_url
        super().__init__(f"HTTP {status_code} from {clean_url}")


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    limiter: Optional[_RateLimiter] = None,
    retries: int = 3,
) -> Any:
    """GET JSON with retry and rate limiting.

    Auth/forbidden errors raise SafeAPIError (sanitized). Other transport
    errors propagate, but their str() should not be logged verbatim by
    callers if the upstream is untrusted.
    """
    if limiter:
        await limiter.acquire()
    last_err = None
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 404:
                # Resource does not exist — no point retrying
                log.debug(f"404 Not Found for {url.split('?', 1)[0]} — skipping retries")
                return None
            if resp.status_code == 429:
                wait = int(resp.headers.get("retry-after", 2 ** attempt))
                log.warning(f"Rate limited on {url.split('?', 1)[0]}, waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (401, 403):
                # Do NOT log resp.text — may contain prompt-injection content
                raise SafeAPIError(resp.status_code, url)
            resp.raise_for_status()
            return resp.json()
        except SafeAPIError:
            raise
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)
    # Wrap final failure in SafeAPIError so callers can't accidentally
    # log an httpx error containing response.text from the upstream.
    if isinstance(last_err, httpx.HTTPStatusError):
        raise SafeAPIError(last_err.response.status_code, url)
    raise SafeAPIError(0, url) from last_err


async def retry_api_call(
    func,
    *args,
    max_retries: int = 3,
    backoff: float = 1.0,
    **kwargs,
) -> Any:
    """
    Call an async function with exponential backoff retry.

    Designed for external API calls (YouTube, Reddit, X/Twitter, etc.).
    Delays: 1s → 2s → 4s (with default backoff=1.0).

    Args:
        func: Async callable.
        *args: Positional args forwarded to func.
        max_retries: Total attempts before re-raising.
        backoff: Base delay in seconds; doubled each attempt.
        **kwargs: Keyword args forwarded to func.

    Returns:
        The return value of func on success.

    Raises:
        The last exception if all attempts are exhausted.
    """
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                delay = backoff * (2 ** attempt)
                log.warning(
                    "retry_api_call: attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1,
                    max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                log.warning(
                    "retry_api_call: all %d attempts exhausted: %s",
                    max_retries,
                    e,
                )
    raise last_err  # type: ignore[misc]


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
        self._limiter = _RateLimiter(calls=5, window_seconds=60)

    async def collect_daily_trends(self, geo: str = "US") -> list[TrendSignal]:
        """
        Fetch today's trending searches from Google Trends.

        Primary: RSS feed (reliable, always works).
        Fallback: dailytrends JSON API (sometimes returns 404).
        """
        signals = []

        # ── Primary: RSS feed ─────────────────────────────────────
        try:
            await self._limiter.acquire()
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
            await self._limiter.acquire()
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
        pytrends makes synchronous HTTP requests, so the blocking call is
        offloaded to a thread pool via asyncio.to_thread.
        """
        signals = []
        try:
            def _fetch_pytrends() -> list[TrendSignal]:
                from pytrends.request import TrendReq
                pt = TrendReq(hl="en-US", tz=240)
                pt.build_payload(keywords[:5], cat=0, timeframe=timeframe, geo=geo)
                iot = pt.interest_over_time()

                result: list[TrendSignal] = []
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

                                result.append(TrendSignal(
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
                return result

            signals = await asyncio.to_thread(_fetch_pytrends)
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
        self._limiter = _RateLimiter(calls=15, window_seconds=60)

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
                raw_prices = best_mkt.get("outcomePrices")
                yes_price = self._parse_yes_price(raw_prices)
                if yes_price is None:
                    continue  # Skip markets with missing price data
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
                        yes_price = self._parse_yes_price(mkt.get("outcomePrices"))
                        if yes_price is None:
                            continue  # Skip markets with missing price data
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

    def _parse_yes_price(self, raw: Any) -> Optional[float]:
        """Parse outcomePrices field (JSON array string, CSV, or list).

        Returns None when price data is missing or unparseable, so callers
        can handle missing data explicitly rather than assuming 50%.
        """
        if isinstance(raw, list) and raw:
            try:
                return float(raw[0])
            except (ValueError, TypeError):
                return None
        if isinstance(raw, str):
            cleaned = raw.strip().strip("[]")
            parts = [p.strip().strip('"\'') for p in cleaned.split(",")]
            if parts:
                try:
                    return float(parts[0])
                except ValueError:
                    pass
        return None

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

    # RSS fallbacks — used when no API keys are configured
    RSS_HEADLINES = {
        "general": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
        "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    }

    def __init__(self, gnews_api_key: Optional[str] = None, newsapi_key: Optional[str] = None):
        self._gnews_key = gnews_api_key
        self._newsapi_key = newsapi_key
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._limiter = _RateLimiter(calls=10, window_seconds=60)

    async def collect_top_headlines(self, category: str = "general", lang: str = "en") -> list[NewsSignal]:
        """Fetch top headlines (GNews → NewsAPI → RSS fallback)."""
        signals = []

        # Try GNews first
        if self._gnews_key:
            signals = await self._collect_gnews(category, lang)

        # Try NewsAPI as fallback
        if not signals and self._newsapi_key:
            signals = await self._collect_newsapi(category, lang)

        # RSS fallback (no API keys required)
        if not signals:
            signals = await self._collect_rss_headlines(category)

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

        # RSS fallback for topic search
        if not signals:
            signals = await self._collect_rss_topic(query)

        return signals

    async def _collect_rss_headlines(self, category: str) -> list[NewsSignal]:
        """Parse Google News RSS — works without API keys."""
        url = self.RSS_HEADLINES.get(category, self.RSS_HEADLINES["general"])
        return await self._fetch_rss(url, category)

    async def _collect_rss_topic(self, query: str) -> list[NewsSignal]:
        """Search Google News RSS for a topic."""
        from urllib.parse import quote_plus
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        return await self._fetch_rss(url, query)

    async def _fetch_rss(self, url: str, topic: str) -> list[NewsSignal]:
        """Minimal RSS parser — extracts <item> entries with title/link/source."""
        try:
            await self._limiter.acquire()
            resp = await self._client.get(url)
            resp.raise_for_status()
            xml_text = resp.text
        except Exception as e:
            log.warning(f"RSS fetch failed ({url}): {e}")
            return []

        signals: list[NewsSignal] = []
        # Lightweight regex-based extraction (no external dep)
        import re
        # Match <item>...</item> blocks
        for item_match in list(re.finditer(r"<item>(.*?)</item>", xml_text, re.DOTALL))[:15]:
            block = item_match.group(1)
            title_match = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL)
            link_match = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
            source_match = re.search(r'<source[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</source>', block, re.DOTALL)
            desc_match = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.DOTALL)
            if not title_match:
                continue
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
            link = link_match.group(1).strip() if link_match else ""
            source_name = source_match.group(1).strip() if source_match else "Google News"
            description = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip() if desc_match else ""

            article = {
                "title": title,
                "description": description[:500],
                "source": {"name": source_name},
                "url": link,
            }
            signals.append(self._article_to_signal(article, topic))
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
        self._limiter = _RateLimiter(calls=10, window_seconds=60)  # CoinGecko free = ~10-30/min

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
    """Relative Strength Index using Wilder's exponential smoothing. Returns 0-100 or None."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Seed with SMA of first `period` deltas
    first_gains = [max(d, 0.0) for d in deltas[:period]]
    first_losses = [max(-d, 0.0) for d in deltas[:period]]
    avg_gain = sum(first_gains) / period
    avg_loss = sum(first_losses) / period

    # Wilder's smoothing (EMA with alpha = 1/period) for remaining deltas
    for d in deltas[period:]:
        gain = max(d, 0.0)
        loss = max(-d, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

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
    """
    MACD line, signal line, histogram.

    Uses an incremental EMA pass (O(N)) instead of recalculating EMA from
    scratch for every bar (O(N²)).  Each EMA is seeded with the SMA of its
    first *period* bars and then updated as:
        ema = price * k + ema_prev * (1 - k)   where k = 2 / (period + 1)

    Both fast (12) and slow (26) EMAs are seeded at their respective SMA points,
    then the fast EMA is updated from bar 12 to bar 25 (while slow is still in its
    seed window).  MACD values are only produced from bar 26 onward once both EMAs
    are running.
    """
    if len(prices) < 35:
        return None

    k_fast = 2.0 / (12 + 1)
    k_slow = 2.0 / (26 + 1)

    # Seed fast EMA with SMA of first 12 bars
    fast_ema = sum(prices[:12]) / 12
    # Seed slow EMA with SMA of first 26 bars
    slow_ema = sum(prices[:26]) / 26

    # Advance fast EMA through bars 12-25 (slow is still seeding during this window)
    for price in prices[12:26]:
        fast_ema = price * k_fast + fast_ema * (1 - k_fast)

    # Walk from bar 26 onward, updating both EMAs incrementally
    macd_vals: list[float] = []
    for price in prices[26:]:
        fast_ema = price * k_fast + fast_ema * (1 - k_fast)
        slow_ema = price * k_slow + slow_ema * (1 - k_slow)
        macd_vals.append(fast_ema - slow_ema)

    if len(macd_vals) < 9:
        return None

    macd_line = macd_vals[-1]

    # Signal line: 9-period EMA of MACD values, seeded with SMA of first 9
    k_sig = 2.0 / (9 + 1)
    signal_line = sum(macd_vals[:9]) / 9
    for mv in macd_vals[9:]:
        signal_line = mv * k_sig + signal_line * (1 - k_sig)

    return macd_line, signal_line, macd_line - signal_line


# ═══════════════════════════════════════════════════════════════════════════
# 4b. UNUSUAL WHALES COLLECTOR (options flow + market tide)
# ═══════════════════════════════════════════════════════════════════════════


class UnusualWhalesCollector:
    """
    Fetch options flow + index/market data from Unusual Whales.

    Endpoints used:
      - /api/market/market-tide          → SPY/index sentiment (call vs put premium)
      - /api/option-trades/flow-alerts   → unusual options activity
    """

    BASE_URL = "https://api.unusualwhales.com/api"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or ""
        self._client = httpx.AsyncClient(timeout=30.0)
        # UW publishes a 120 req/min plan-dependent limit; stay well under.
        self._limiter = _RateLimiter(calls=60, window_seconds=60)
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    async def collect_market_tide(self) -> list[MarketSignal]:
        """
        Latest market-tide point: net call premium vs net put premium for the
        broad index. Strong negative net = bearish flow; strong positive = bullish.
        """
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/market/market-tide",
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            latest = rows[-1]
            net_call = float(latest.get("net_call_premium", 0) or 0)
            net_put = float(latest.get("net_put_premium", 0) or 0)
            net_volume = float(latest.get("net_volume", 0) or 0)
            net_premium = net_call - net_put

            if net_premium > 50_000_000:
                direction = SignalDirection.BULLISH
            elif net_premium < -50_000_000:
                direction = SignalDirection.BEARISH
            elif net_premium > 10_000_000:
                direction = SignalDirection.EXPANDING
            elif net_premium < -10_000_000:
                direction = SignalDirection.CONTRACTING
            else:
                direction = SignalDirection.NEUTRAL

            signals.append(MarketSignal(
                source=SourceType.OPTIONS_FLOW,
                category="index_flow",
                title=f"Market Tide: net premium ${net_premium:+,.0f}",
                content=(
                    f"Net call premium: ${net_call:+,.0f} | "
                    f"Net put premium: ${net_put:+,.0f} | "
                    f"Net volume: {net_volume:+,.0f}"
                ),
                symbol="SPY",
                value=net_premium,
                volume=abs(net_volume),
                direction=direction,
                confidence=0.80,
                tags=["options_flow", "market_tide", "spy", "index"],
                metadata={
                    "net_call_premium": net_call,
                    "net_put_premium": net_put,
                    "net_volume": net_volume,
                    "timestamp_uw": latest.get("timestamp"),
                },
            ))
        except Exception as e:
            log.warning(f"UW market-tide failed: {e}")
        return signals

    async def collect_flow_alerts(self, limit: int = 50) -> list[MarketSignal]:
        """
        Recent unusual options flow alerts (single-leg + multi-leg).
        """
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/option-trades/flow-alerts",
                params={"limit": limit},
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            for alert in rows[:limit]:
                ticker = alert.get("ticker", "")
                if not ticker:
                    continue
                ask_prem = float(alert.get("total_ask_side_prem", 0) or 0)
                bid_prem = float(alert.get("total_bid_side_prem", 0) or 0)
                size = float(alert.get("total_size", 0) or 0)
                oi = float(alert.get("open_interest", 0) or 0)
                iv_end = alert.get("iv_end")
                sector = alert.get("sector") or ""
                has_multileg = bool(alert.get("has_multileg", False))

                # Side bias: more ask-side premium = aggressive buying (bullish on calls,
                # bearish on puts depending on contract type — flow-alerts mixes both,
                # so use raw premium ratio as signal magnitude).
                total_prem = ask_prem + bid_prem
                if total_prem == 0:
                    continue
                ask_ratio = ask_prem / total_prem if total_prem > 0 else 0.5
                if ask_ratio > 0.7:
                    direction = SignalDirection.BULLISH
                elif ask_ratio < 0.3:
                    direction = SignalDirection.BEARISH
                else:
                    direction = SignalDirection.NEUTRAL

                # Confidence scales with premium size + OI penetration.
                conf = min(0.95, 0.5 + (total_prem / 1_000_000) * 0.1)

                signals.append(MarketSignal(
                    source=SourceType.OPTIONS_FLOW,
                    category="options_flow",
                    title=f"{ticker} flow alert: ${total_prem:,.0f} ({size:.0f} contracts)",
                    content=(
                        f"{ticker} — ask ${ask_prem:,.0f} / bid ${bid_prem:,.0f} | "
                        f"size {size:.0f} | OI {oi:.0f} | sector {sector}"
                        + (" | multileg" if has_multileg else "")
                    ),
                    symbol=ticker,
                    value=total_prem,
                    volume=size,
                    direction=direction,
                    confidence=conf,
                    tags=["options_flow", ticker.lower(), sector.lower().replace(" ", "_") or "unknown"],
                    metadata={
                        "ask_premium": ask_prem,
                        "bid_premium": bid_prem,
                        "open_interest": oi,
                        "iv_end": iv_end,
                        "has_multileg": has_multileg,
                        "rule_id": alert.get("rule_id"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW flow-alerts failed: {e}")
        return signals

    async def collect_dark_pool(self, min_premium: float = 1_000_000) -> list[MarketSignal]:
        """
        Recent dark-pool prints, filtered by premium threshold.

        Large off-exchange prints often indicate institutional accumulation
        or distribution invisible on lit markets.
        """
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/darkpool/recent",
                params={"limit": 200},
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            # Aggregate by ticker for cleaner signal
            by_ticker: dict[str, dict] = {}
            for trade in rows:
                if trade.get("canceled"):
                    continue
                ticker = trade.get("ticker", "")
                premium = float(trade.get("premium", 0) or 0)
                if not ticker or premium < min_premium:
                    continue
                size = float(trade.get("size", 0) or 0)
                price = float(trade.get("price", 0) or 0)
                ask = float(trade.get("nbbo_ask", price) or price)
                bid = float(trade.get("nbbo_bid", price) or price)
                # Above-ask = aggressive buy; below-bid = aggressive sell
                if ask > 0 and price >= ask:
                    side_bias = 1
                elif bid > 0 and price <= bid:
                    side_bias = -1
                else:
                    side_bias = 0
                slot = by_ticker.setdefault(ticker, {
                    "total_prem": 0.0, "total_size": 0.0,
                    "max_print": 0.0, "side_score": 0, "n_prints": 0,
                })
                slot["total_prem"] += premium
                slot["total_size"] += size
                slot["max_print"] = max(slot["max_print"], premium)
                slot["side_score"] += side_bias
                slot["n_prints"] += 1

            for ticker, agg in by_ticker.items():
                if agg["side_score"] > 0:
                    direction = SignalDirection.BULLISH
                elif agg["side_score"] < 0:
                    direction = SignalDirection.BEARISH
                else:
                    direction = SignalDirection.NEUTRAL
                conf = min(0.95, 0.5 + (agg["total_prem"] / 50_000_000) * 0.4)
                signals.append(MarketSignal(
                    source=SourceType.OPTIONS_FLOW,
                    category="dark_pool",
                    title=f"{ticker} dark pool: ${agg['total_prem']:,.0f} across {agg['n_prints']} prints",
                    content=(
                        f"{ticker} — total ${agg['total_prem']:,.0f} | "
                        f"max single ${agg['max_print']:,.0f} | "
                        f"size {agg['total_size']:,.0f} | side_score {agg['side_score']}"
                    ),
                    symbol=ticker,
                    value=agg["total_prem"],
                    volume=agg["total_size"],
                    direction=direction,
                    confidence=conf,
                    tags=["dark_pool", ticker.lower(), "institutional"],
                    metadata={
                        "max_print": agg["max_print"],
                        "n_prints": agg["n_prints"],
                        "side_score": agg["side_score"],
                    },
                ))
        except Exception as e:
            log.warning(f"UW dark-pool failed: {e}")
        return signals

    async def collect_greek_exposure(self, tickers: list[str]) -> list[MarketSignal]:
        """
        Net dealer greek exposure (delta/gamma/charm/vanna) per ticker.

        Gamma flip signal: when sum(call_gamma, put_gamma) crosses zero,
        dealer hedging behavior inverts → vol regime shift.
        """
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        for ticker in tickers:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.BASE_URL}/stock/{ticker}/greek-exposure",
                    headers=self._headers,
                    limiter=self._limiter,
                )
                rows = (data or {}).get("data") if isinstance(data, dict) else None
                if not rows:
                    continue
                latest = rows[-1] if isinstance(rows, list) else rows
                call_delta = float(latest.get("call_delta", 0) or 0)
                put_delta = float(latest.get("put_delta", 0) or 0)
                call_gamma = float(latest.get("call_gamma", 0) or 0)
                put_gamma = float(latest.get("put_gamma", 0) or 0)
                net_delta = call_delta + put_delta
                net_gamma = call_gamma + put_gamma

                if net_gamma > 0:
                    # Long gamma → dealers stabilize, low realized vol
                    direction = SignalDirection.NEUTRAL
                    regime = "long_gamma_stable"
                else:
                    # Short gamma → dealers amplify, high realized vol
                    direction = SignalDirection.EXPANDING
                    regime = "short_gamma_volatile"

                signals.append(MarketSignal(
                    source=SourceType.OPTIONS_FLOW,
                    category="greek_exposure",
                    title=f"{ticker} net gamma {net_gamma:+,.0f} ({regime})",
                    content=(
                        f"{ticker} — net delta {net_delta:+,.0f} | "
                        f"net gamma {net_gamma:+,.0f} | regime {regime}"
                    ),
                    symbol=ticker,
                    value=net_gamma,
                    direction=direction,
                    confidence=0.75,
                    tags=["greek_exposure", ticker.lower(), regime],
                    metadata={
                        "call_delta": call_delta,
                        "put_delta": put_delta,
                        "call_gamma": call_gamma,
                        "put_gamma": put_gamma,
                        "net_delta": net_delta,
                        "net_gamma": net_gamma,
                        "regime": regime,
                        "date": latest.get("date"),
                    },
                ))
            except Exception as e:
                log.warning(f"UW greek-exposure {ticker} failed: {e}")
        return signals

    async def collect_max_pain(self, tickers: list[str]) -> list[MarketSignal]:
        """Max pain strikes per ticker — magnetism into expiry."""
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        for ticker in tickers:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.BASE_URL}/stock/{ticker}/max-pain",
                    headers=self._headers,
                    limiter=self._limiter,
                )
                rows = (data or {}).get("data") if isinstance(data, dict) else None
                if not rows:
                    continue
                latest = rows[-1] if isinstance(rows, list) else rows
                close = float(latest.get("close", 0) or 0)
                max_pain = float(latest.get("max_pain", 0) or 0)
                if close == 0 or max_pain == 0:
                    continue
                pin_distance_pct = (max_pain - close) / close * 100
                # Direction = where price would need to go to hit max pain
                if pin_distance_pct > 1:
                    direction = SignalDirection.BEARISH  # pin lower
                elif pin_distance_pct < -1:
                    direction = SignalDirection.BULLISH  # pin higher
                else:
                    direction = SignalDirection.NEUTRAL
                signals.append(MarketSignal(
                    source=SourceType.OPTIONS_FLOW,
                    category="max_pain",
                    title=f"{ticker} max pain ${max_pain:,.2f} ({pin_distance_pct:+.2f}% from spot)",
                    content=(
                        f"{ticker} — spot ${close:,.2f} | max pain ${max_pain:,.2f} | "
                        f"expiry {latest.get('expiry','?')}"
                    ),
                    symbol=ticker,
                    current_price=close,
                    value=max_pain,
                    change_pct=pin_distance_pct,
                    direction=direction,
                    confidence=0.65,
                    tags=["max_pain", ticker.lower()],
                    metadata={
                        "expiry": latest.get("expiry"),
                        "next_upper_strike": latest.get("next_upper_strike"),
                        "next_lower_strike": latest.get("next_lower_strike"),
                    },
                ))
            except Exception as e:
                log.warning(f"UW max-pain {ticker} failed: {e}")
        return signals

    async def collect_sector_etfs(self) -> list[MarketSignal]:
        """Sector ETF flow snapshot (XLK, XLF, XLE, etc + SPY)."""
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/market/sector-etfs",
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            for row in rows:
                ticker = row.get("ticker", "")
                if not ticker:
                    continue
                last = float(row.get("last", 0) or 0)
                open_ = float(row.get("open", 0) or 0)
                call_prem = float(row.get("call_premium", 0) or 0)
                put_prem = float(row.get("put_premium", 0) or 0)
                call_vol = float(row.get("call_volume", 0) or 0)
                put_vol = float(row.get("put_volume", 0) or 0)
                day_change_pct = ((last - open_) / open_ * 100) if open_ > 0 else 0
                pcr = (put_vol / call_vol) if call_vol > 0 else 0
                net_prem = call_prem - put_prem

                if day_change_pct > 0.5 and net_prem > 0:
                    direction = SignalDirection.BULLISH
                elif day_change_pct < -0.5 and net_prem < 0:
                    direction = SignalDirection.BEARISH
                elif net_prem > 0:
                    direction = SignalDirection.EXPANDING
                elif net_prem < 0:
                    direction = SignalDirection.CONTRACTING
                else:
                    direction = SignalDirection.NEUTRAL

                signals.append(MarketSignal(
                    source=SourceType.OPTIONS_FLOW,
                    category="sector_rotation",
                    title=f"{ticker} {day_change_pct:+.2f}% | net opt prem ${net_prem:+,.0f}",
                    content=(
                        f"{ticker} ({row.get('full_name','')}) — last ${last:,.2f} | "
                        f"P/C ratio {pcr:.2f} | call prem ${call_prem:,.0f} | put prem ${put_prem:,.0f}"
                    ),
                    symbol=ticker,
                    current_price=last,
                    value=net_prem,
                    change_pct=day_change_pct,
                    volume=call_vol + put_vol,
                    direction=direction,
                    confidence=0.85,
                    tags=["sector_etf", ticker.lower(), "rotation"],
                    metadata={
                        "call_premium": call_prem,
                        "put_premium": put_prem,
                        "call_volume": call_vol,
                        "put_volume": put_vol,
                        "put_call_ratio": pcr,
                        "in_out_flow": row.get("in_out_flow"),
                        "marketcap": row.get("marketcap"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW sector-etfs failed: {e}")
        return signals

    async def collect_total_options_volume(self) -> list[MarketSignal]:
        """Market-wide call/put volume + premium → fear/greed regime gauge."""
        signals: list[MarketSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/market/total-options-volume",
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            latest = rows[-1] if isinstance(rows, list) else rows
            call_vol = float(latest.get("call_volume", 0) or 0)
            put_vol = float(latest.get("put_volume", 0) or 0)
            call_prem = float(latest.get("call_premium", 0) or 0)
            put_prem = float(latest.get("put_premium", 0) or 0)
            if call_vol + put_vol == 0:
                return signals
            pcr_volume = put_vol / call_vol if call_vol > 0 else 0
            put_prem_pct = put_prem / (call_prem + put_prem) if (call_prem + put_prem) > 0 else 0
            # Classic put/call > 1.0 = fear; < 0.7 = complacency
            if pcr_volume > 1.0 or put_prem_pct > 0.45:
                direction = SignalDirection.BEARISH
                regime = "fear"
            elif pcr_volume < 0.7 and put_prem_pct < 0.30:
                direction = SignalDirection.BULLISH
                regime = "greed"
            else:
                direction = SignalDirection.NEUTRAL
                regime = "balanced"
            signals.append(MarketSignal(
                source=SourceType.OPTIONS_FLOW,
                category="market_regime",
                title=f"Market regime: {regime} (P/C vol {pcr_volume:.2f}, put prem {put_prem_pct:.0%})",
                content=(
                    f"Total call vol {call_vol:,.0f} | put vol {put_vol:,.0f} | "
                    f"call prem ${call_prem:,.0f} | put prem ${put_prem:,.0f}"
                ),
                symbol="MARKET",
                value=pcr_volume,
                direction=direction,
                confidence=0.85,
                tags=["market_regime", regime, "options_flow"],
                metadata={
                    "call_volume": call_vol,
                    "put_volume": put_vol,
                    "call_premium": call_prem,
                    "put_premium": put_prem,
                    "put_call_ratio_volume": pcr_volume,
                    "put_premium_pct": put_prem_pct,
                    "regime": regime,
                    "date": latest.get("date"),
                },
            ))
        except Exception as e:
            log.warning(f"UW total-options-volume failed: {e}")
        return signals

    async def collect_congress_trades(self, limit: int = 50) -> list[IntelSignal]:
        """Recent US Congress member trades — political insider signal."""
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/congress/recent-trades",
                params={"limit": limit},
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            for trade in rows[:limit]:
                ticker = trade.get("ticker", "")
                if not ticker:
                    continue
                txn = (trade.get("txn_type") or "").lower()
                amounts = trade.get("amounts") or ""
                # Parse upper bound from "$100,001 - $250,000"
                try:
                    amt_high = float(amounts.split("-")[-1].replace("$", "").replace(",", "").strip())
                except Exception:
                    amt_high = 0
                if "buy" in txn or "purchase" in txn:
                    direction = SignalDirection.BULLISH
                elif "sell" in txn:
                    direction = SignalDirection.BEARISH
                else:
                    direction = SignalDirection.NEUTRAL
                conf = min(0.85, 0.4 + (amt_high / 1_000_000) * 0.3)
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="congress_trade",
                    title=f"{trade.get('name','?')} {txn} {ticker} ({amounts})",
                    content=(
                        f"{trade.get('name','?')} ({trade.get('member_type','?')}) "
                        f"{txn} {ticker} on {trade.get('transaction_date','?')} | "
                        f"issuer={trade.get('issuer','?')} | filed {trade.get('filed_at_date','?')}"
                    ),
                    value=amt_high,
                    direction=direction,
                    confidence=conf,
                    tags=["congress_trade", ticker.lower(), txn, trade.get('member_type', 'unknown')],
                    metadata={
                        "ticker": ticker,
                        "politician": trade.get("name"),
                        "politician_id": trade.get("politician_id"),
                        "issuer": trade.get("issuer"),
                        "txn_type": trade.get("txn_type"),
                        "amounts": amounts,
                        "transaction_date": trade.get("transaction_date"),
                        "filed_at_date": trade.get("filed_at_date"),
                        "member_type": trade.get("member_type"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW congress-trades failed: {e}")
        return signals

    async def collect_insider_clusters(self, limit: int = 100, min_cluster: int = 3) -> list[IntelSignal]:
        """
        Form-4 insider transactions; emit cluster signals when ≥ min_cluster
        distinct insiders transact same ticker recently (very strong signal).
        """
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/insider/transactions",
                params={"limit": limit},
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            # Cluster by ticker, count distinct owners, sum value
            clusters: dict[str, dict] = {}
            for txn in rows:
                ticker = txn.get("ticker", "")
                code = (txn.get("transaction_code") or "").upper()
                # P = open-market purchase (strongest), S = sale, A/M = grant/option (noise)
                if not ticker or code not in {"P", "S"}:
                    continue
                slot = clusters.setdefault(ticker, {
                    "owners": set(), "buys": 0, "sells": 0,
                    "value": 0.0, "officers": 0, "directors": 0,
                    "sample": txn,
                })
                slot["owners"].add(txn.get("owner_name", ""))
                amount = float(txn.get("amount", 0) or 0)
                price = float(txn.get("price", 0) or 0) or float(txn.get("stock_price", 0) or 0)
                slot["value"] += amount * price
                if code == "P":
                    slot["buys"] += 1
                else:
                    slot["sells"] += 1
                if txn.get("is_officer"):
                    slot["officers"] += 1
                if txn.get("is_director"):
                    slot["directors"] += 1

            for ticker, agg in clusters.items():
                n_owners = len(agg["owners"])
                if n_owners < min_cluster:
                    continue
                net = agg["buys"] - agg["sells"]
                if net > 0:
                    direction = SignalDirection.BULLISH
                elif net < 0:
                    direction = SignalDirection.BEARISH
                else:
                    direction = SignalDirection.NEUTRAL
                conf = min(0.95, 0.55 + n_owners * 0.05 + (agg["officers"] + agg["directors"]) * 0.02)
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="insider_cluster",
                    title=f"{ticker} insider cluster: {n_owners} insiders, net {net:+d} (${agg['value']:,.0f})",
                    content=(
                        f"{ticker} — {n_owners} distinct insiders | "
                        f"buys {agg['buys']} / sells {agg['sells']} | "
                        f"officers {agg['officers']} | directors {agg['directors']} | "
                        f"value ${agg['value']:,.0f}"
                    ),
                    value=agg["value"],
                    direction=direction,
                    confidence=conf,
                    tags=["insider_cluster", ticker.lower(), "form4"],
                    metadata={
                        "ticker": ticker,
                        "n_owners": n_owners,
                        "buys": agg["buys"],
                        "sells": agg["sells"],
                        "officers": agg["officers"],
                        "directors": agg["directors"],
                        "value": agg["value"],
                        "sector": agg["sample"].get("sector"),
                        "marketcap": agg["sample"].get("marketcap"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW insider-clusters failed: {e}")
        return signals

    # ──────────────────────────────────────────────────────────────────
    # TIER 3 — Calendars, screeners, seasonality, news, earnings
    # All use SafeAPIError-protected _fetch_json. Per-method exceptions
    # are caught and logged so a single failing endpoint can't sink a
    # whole collection cycle.
    # ──────────────────────────────────────────────────────────────────

    async def collect_economic_calendar(self) -> list[IntelSignal]:
        """Upcoming Fed/CPI/NFP/macro releases — context for macro positioning."""
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/market/economic-calendar",
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            now = datetime.now(timezone.utc)
            for ev in rows:
                event = ev.get("event") or ""
                t_iso = ev.get("time") or ""
                forecast = ev.get("forecast")
                prev = ev.get("prev")
                # Tier importance from event keywords
                ev_lower = event.lower()
                high_impact = any(k in ev_lower for k in (
                    "cpi", "ppi", "fomc", "non-farm", "nonfarm", "payroll",
                    "unemployment", "gdp", "fed funds", "interest rate",
                    "powell", "jobless", "retail sales",
                ))
                conf = 0.85 if high_impact else 0.55
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="economic_calendar",
                    title=f"{event} ({ev.get('reported_period','')}) @ {t_iso}",
                    content=f"{event} | period={ev.get('reported_period')} | forecast={forecast} | prev={prev}",
                    direction=SignalDirection.NEUTRAL,
                    confidence=conf,
                    tags=["macro", "calendar", "high_impact" if high_impact else "low_impact"],
                    metadata={
                        "event": event,
                        "time": t_iso,
                        "forecast": forecast,
                        "prev": prev,
                        "period": ev.get("reported_period"),
                        "type": ev.get("type"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW economic-calendar failed: {e}")
        return signals

    async def collect_fda_calendar(self, days_ahead: int = 30) -> list[IntelSignal]:
        """Upcoming PDUFA dates, AdCom, Phase trial readouts — biotech catalysts."""
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/market/fda-calendar",
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            cutoff = datetime.now(timezone.utc) + timedelta(days=days_ahead)
            now = datetime.now(timezone.utc)
            for ev in rows:
                ticker = ev.get("ticker") or ""
                target = ev.get("target_date") or ev.get("end_date") or ev.get("start_date")
                if not ticker or not target:
                    continue
                # Try to filter to forward-looking; accept non-parseable dates
                # (UW returns soft strings like "2025-MID") so we don't drop them.
                is_forward = True
                try:
                    tdate = datetime.fromisoformat(str(target).replace("Z", "+00:00"))
                    if tdate.tzinfo is None:
                        tdate = tdate.replace(tzinfo=timezone.utc)
                    is_forward = (now - timedelta(days=1)) <= tdate <= cutoff
                except Exception:
                    pass  # keep ambiguous-dated catalyst, downgrade confidence below
                etype = ev.get("event_type") or ev.get("status") or ""
                has_options = bool(ev.get("has_options"))
                base = 0.55 if has_options else 0.40
                conf = base + (0.20 if is_forward else 0.0)
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="fda_catalyst",
                    title=f"{ticker} FDA: {etype} on {target}",
                    content=(ev.get("description") or "")[:400],
                    direction=SignalDirection.NEUTRAL,
                    confidence=conf,
                    tags=["biotech", "fda", ticker.lower(), "options" if has_options else "no_options"],
                    metadata={
                        "ticker": ticker,
                        "target_date": target,
                        "event_type": etype,
                        "drug": ev.get("drug"),
                        "indication": ev.get("indication"),
                        "outcome": ev.get("outcome"),
                        "has_options": has_options,
                        "marketcap": ev.get("marketcap"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW fda-calendar failed: {e}")
        return signals

    async def collect_oi_change(
        self, tickers: list[str], top_n: int = 10
    ) -> list[IntelSignal]:
        """Largest day-over-day OI deltas per ticker (positioning shifts)."""
        signals: list[IntelSignal] = []
        if not self.enabled or not tickers:
            return signals
        for t in tickers:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.BASE_URL}/stock/{t}/oi-change",
                    headers=self._headers,
                    limiter=self._limiter,
                )
                rows = (data or {}).get("data") if isinstance(data, dict) else None
                if not rows:
                    continue
                # Sort by absolute oi_change descending
                ranked = sorted(
                    rows,
                    key=lambda r: abs(float(r.get("oi_change") or 0)),
                    reverse=True,
                )[:top_n]
                for row in ranked:
                    sym = row.get("option_symbol") or ""
                    delta = float(row.get("oi_change") or 0)
                    if abs(delta) < 1000:
                        continue
                    is_call = "C" in sym[-9:-8] if len(sym) >= 9 else False
                    direction = (
                        SignalDirection.BULLISH if (is_call and delta > 0) or (not is_call and delta < 0)
                        else SignalDirection.BEARISH if (is_call and delta < 0) or (not is_call and delta > 0)
                        else SignalDirection.NEUTRAL
                    )
                    signals.append(IntelSignal(
                        source=SourceType.MARKET_DATA,
                        category="oi_change",
                        title=f"{t} {sym} OI Δ {delta:+,.0f}",
                        content=(
                            f"{t} {sym} | oi_change={delta:+,.0f} | "
                            f"curr_oi={row.get('curr_oi')} | volume={row.get('volume')} | "
                            f"prev_premium=${row.get('prev_total_premium')}"
                        ),
                        value=abs(delta),
                        direction=direction,
                        confidence=min(0.85, 0.5 + abs(delta) / 100000),
                        tags=["oi_change", t.lower(), "calls" if is_call else "puts"],
                        metadata={
                            "ticker": t,
                            "option_symbol": sym,
                            "oi_change": delta,
                            "curr_oi": row.get("curr_oi"),
                            "volume": row.get("volume"),
                            "prev_total_premium": row.get("prev_total_premium"),
                            "days_of_oi_increases": row.get("days_of_oi_increases"),
                        },
                    ))
            except Exception as e:
                log.warning(f"UW oi-change failed for {t}: {e}")
        return signals

    async def collect_expiry_breakdown(self, tickers: list[str]) -> list[IntelSignal]:
        """OI/volume distribution across expiries — gamma cliff / pin detection."""
        signals: list[IntelSignal] = []
        if not self.enabled or not tickers:
            return signals
        for t in tickers:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.BASE_URL}/stock/{t}/expiry-breakdown",
                    headers=self._headers,
                    limiter=self._limiter,
                )
                rows = (data or {}).get("data") if isinstance(data, dict) else None
                if not rows:
                    continue
                total_oi = sum(int(r.get("open_interest") or 0) for r in rows)
                total_vol = sum(int(r.get("volume") or 0) for r in rows)
                if total_oi == 0:
                    continue
                # Find dominant expiry (largest concentration = gamma cliff)
                top = max(rows, key=lambda r: int(r.get("open_interest") or 0))
                top_pct = int(top.get("open_interest") or 0) / total_oi
                conf = 0.55 + min(0.35, top_pct)
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="expiry_breakdown",
                    title=f"{t} top expiry {top.get('expires')} = {top_pct:.0%} OI",
                    content=(
                        f"{t} | total_oi={total_oi:,} | total_vol={total_vol:,} | "
                        f"top_expiry={top.get('expires')} ({top_pct:.0%} OI, {top.get('chains')} chains)"
                    ),
                    value=float(top_pct),
                    direction=SignalDirection.NEUTRAL,
                    confidence=conf,
                    tags=["expiry", "gamma", t.lower()],
                    metadata={
                        "ticker": t,
                        "total_oi": total_oi,
                        "total_volume": total_vol,
                        "top_expiry": top.get("expires"),
                        "top_concentration_pct": round(top_pct, 4),
                        "expiry_count": len(rows),
                    },
                ))
            except Exception as e:
                log.warning(f"UW expiry-breakdown failed for {t}: {e}")
        return signals

    async def collect_screener_stocks(self, limit: int = 25) -> list[IntelSignal]:
        """Top tickers by unusual options activity / flow imbalance."""
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/screener/stocks",
                params={"limit": limit, "order": "net_call_premium", "order_direction": "desc"},
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            for row in rows:
                ticker = row.get("ticker") or ""
                if not ticker:
                    continue
                bull = float(row.get("bullish_premium") or 0)
                bear = float(row.get("bearish_premium") or 0)
                net = bull - bear
                if abs(net) < 1_000_000:  # $1M floor
                    continue
                direction = (
                    SignalDirection.BULLISH if net > 0
                    else SignalDirection.BEARISH if net < 0
                    else SignalDirection.NEUTRAL
                )
                conf = min(0.85, 0.5 + abs(net) / 50_000_000)
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="screener_unusual",
                    title=f"{ticker} flow imbalance ${net:+,.0f}",
                    content=(
                        f"{ticker} ({row.get('full_name')}) | "
                        f"bullish ${bull:,.0f} / bearish ${bear:,.0f} | net ${net:+,.0f} | "
                        f"iv30d={row.get('iv30d')} | iv_rank={row.get('iv_rank')} | "
                        f"sector={row.get('sector')}"
                    ),
                    value=abs(net),
                    direction=direction,
                    confidence=conf,
                    tags=["screener", "unusual_flow", ticker.lower()],
                    metadata={
                        "ticker": ticker,
                        "bullish_premium": bull,
                        "bearish_premium": bear,
                        "net_premium": net,
                        "iv30d": row.get("iv30d"),
                        "iv_rank": row.get("iv_rank"),
                        "sector": row.get("sector"),
                        "marketcap": row.get("marketcap"),
                        "next_earnings_date": row.get("next_earnings_date"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW screener-stocks failed: {e}")
        return signals

    async def collect_seasonality(self, tickers: list[str]) -> list[IntelSignal]:
        """Monthly seasonality edge — historical month-of-year performance."""
        signals: list[IntelSignal] = []
        if not self.enabled or not tickers:
            return signals
        current_month = datetime.now(timezone.utc).month
        next_month = (current_month % 12) + 1
        for t in tickers:
            try:
                data = await _fetch_json(
                    self._client,
                    f"{self.BASE_URL}/seasonality/{t}/monthly",
                    headers=self._headers,
                    limiter=self._limiter,
                )
                rows = (data or {}).get("data") if isinstance(data, dict) else None
                if not rows:
                    continue
                for row in rows:
                    m = int(row.get("month") or 0)
                    if m not in (current_month, next_month):
                        continue
                    avg = float(row.get("avg_change") or 0)
                    pos_perc = float(row.get("positive_months_perc") or 0)
                    years = int(row.get("years") or 0)
                    if years < 5:
                        continue
                    direction = (
                        SignalDirection.BULLISH if avg > 0.005 and pos_perc > 0.6
                        else SignalDirection.BEARISH if avg < -0.005 and pos_perc < 0.4
                        else SignalDirection.NEUTRAL
                    )
                    horizon = "current" if m == current_month else "next"
                    signals.append(IntelSignal(
                        source=SourceType.MARKET_DATA,
                        category="seasonality",
                        title=f"{t} M{m} ({horizon}): avg {avg:+.2%}, {pos_perc:.0%} positive ({years}y)",
                        content=(
                            f"{t} month {m} | avg_change={avg:+.2%} | "
                            f"median={row.get('median_change')} | "
                            f"positive_months={pos_perc:.0%} ({row.get('positive_closes')}/{years}) | "
                            f"max={row.get('max_change')} | min={row.get('min_change')}"
                        ),
                        value=avg,
                        direction=direction,
                        confidence=min(0.75, 0.4 + abs(pos_perc - 0.5) + years * 0.005),
                        tags=["seasonality", t.lower(), horizon],
                        metadata={
                            "ticker": t,
                            "month": m,
                            "horizon": horizon,
                            "avg_change": avg,
                            "median_change": row.get("median_change"),
                            "positive_months_perc": pos_perc,
                            "years": years,
                        },
                    ))
            except Exception as e:
                log.warning(f"UW seasonality failed for {t}: {e}")
        return signals

    async def collect_earnings_afterhours(self) -> list[IntelSignal]:
        """Today's after-hours earnings reports — catalyst plays."""
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/earnings/afterhours",
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            for row in rows:
                ticker = row.get("symbol") or ""
                if not ticker:
                    continue
                expected_move = row.get("expected_move_perc")
                has_options = bool(row.get("has_options"))
                is_sp500 = bool(row.get("is_s_p_500"))
                conf = 0.55 + (0.15 if is_sp500 else 0) + (0.1 if has_options else 0)
                signals.append(IntelSignal(
                    source=SourceType.MARKET_DATA,
                    category="earnings_afterhours",
                    title=f"{ticker} earnings AH — expected move {expected_move or 'n/a'}",
                    content=(
                        f"{ticker} ({row.get('full_name')}) | "
                        f"sector={row.get('sector')} | report_time={row.get('report_time')} | "
                        f"street_est={row.get('street_mean_est')} | "
                        f"expected_move={expected_move} | sp500={is_sp500}"
                    ),
                    direction=SignalDirection.NEUTRAL,
                    confidence=min(0.85, conf),
                    tags=["earnings", "afterhours", ticker.lower()] + (["sp500"] if is_sp500 else []),
                    metadata={
                        "ticker": ticker,
                        "report_time": row.get("report_time"),
                        "expected_move_perc": expected_move,
                        "street_mean_est": row.get("street_mean_est"),
                        "sector": row.get("sector"),
                        "is_sp500": is_sp500,
                        "has_options": has_options,
                        "marketcap": row.get("marketcap"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW earnings-afterhours failed: {e}")
        return signals

    async def collect_news_headlines(self, limit: int = 50) -> list[IntelSignal]:
        """Real-time market news headlines (Benzinga feed via UW)."""
        signals: list[IntelSignal] = []
        if not self.enabled:
            return signals
        try:
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/news/headlines",
                params={"limit": limit},
                headers=self._headers,
                limiter=self._limiter,
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not rows:
                return signals
            for row in rows:
                headline = row.get("headline") or ""
                if not headline:
                    continue
                tickers = row.get("tickers") or []
                sentiment = (row.get("sentiment") or "neutral").lower()
                is_major = bool(row.get("is_major"))
                direction = (
                    SignalDirection.BULLISH if sentiment in ("positive", "bullish")
                    else SignalDirection.BEARISH if sentiment in ("negative", "bearish")
                    else SignalDirection.NEUTRAL
                )
                conf = 0.55 + (0.25 if is_major else 0) + (0.1 if tickers else 0)
                signals.append(IntelSignal(
                    source=SourceType.NEWS,
                    category="news_headline",
                    title=headline[:200],
                    content=f"{headline} | tickers={tickers} | sentiment={sentiment} | source={row.get('source')}",
                    direction=direction,
                    confidence=min(0.9, conf),
                    tags=["news", row.get("source", "").lower()] + (
                        ["major"] if is_major else []
                    ) + [t.lower() for t in tickers[:3]],
                    metadata={
                        "headline": headline,
                        "tickers": tickers,
                        "sentiment": sentiment,
                        "is_major": is_major,
                        "source": row.get("source"),
                        "created_at": row.get("created_at"),
                        "tags": row.get("tags"),
                    },
                ))
        except Exception as e:
            log.warning(f"UW news-headlines failed: {e}")
        return signals

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()


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
    OAUTH_URL = "https://oauth.reddit.com"

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

    def __init__(
        self,
        subreddits: list[str] | None = None,
        tier: str = "all",
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
    ):
        """
        Initialize Reddit collector.

        Args:
            subreddits: Override list (ignores tiers). None = use tiered system.
            tier: Which tiers to scan: "all", "t1", "t2", "t1t2", or "full" (all 55+)
            client_id/client_secret/user_agent: explicit OAuth creds (override env)
        """
        import os as _os
        if subreddits:
            self.subreddits = subreddits
            self._use_tiers = False
        else:
            self._use_tiers = True
            self._tier = tier
            self.subreddits = self._build_scan_list()

        # Reddit OAuth credentials (Phase 2 fix: unauthenticated JSON returns 403).
        # Check explicit args first, then NCL_-prefixed env, then plain REDDIT_ env
        # (matches what's in repo-level .env).
        self._client_id = (
            client_id
            or _os.environ.get("NCL_REDDIT_CLIENT_ID", "")
            or _os.environ.get("REDDIT_CLIENT_ID", "")
        ).strip()
        self._client_secret = (
            client_secret
            or _os.environ.get("NCL_REDDIT_CLIENT_SECRET", "")
            or _os.environ.get("REDDIT_CLIENT_SECRET", "")
        ).strip()
        self._user_agent = (
            user_agent
            or _os.environ.get("NCL_REDDIT_USER_AGENT")
            or _os.environ.get("REDDIT_USER_AGENT")
            or "NCL-Brain-Intelligence/1.0 (by /u/ncl-intel-bot)"
        )
        self._oauth_token: str | None = None
        self._oauth_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._authed = bool(self._client_id and self._client_secret)

        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": self._user_agent},
            follow_redirects=True,
        )
        # Reddit OAuth: 60 requests/min (authenticated); be conservative
        self._limiter = _RateLimiter(calls=60, window_seconds=60)

    async def _get_oauth_token(self) -> str | None:
        """Fetch (and cache) a Reddit OAuth bearer token via client_credentials."""
        if not self._authed:
            return None
        now = time.monotonic()
        async with self._token_lock:
            if self._oauth_token and now < self._oauth_expires_at - 30:
                return self._oauth_token
            try:
                resp = await self._client.post(
                    "https://www.reddit.com/api/v1/access_token",
                    auth=(self._client_id, self._client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"User-Agent": self._user_agent},
                )
                resp.raise_for_status()
                payload = resp.json()
                self._oauth_token = payload.get("access_token")
                ttl = float(payload.get("expires_in", 3600))
                self._oauth_expires_at = now + ttl
                return self._oauth_token
            except Exception as e:
                log.warning(f"Reddit OAuth token fetch failed: {e}")
                self._oauth_token = None
                return None

    async def _auth_headers(self) -> dict:
        """Headers to use for Reddit API requests, with OAuth bearer when available."""
        token = await self._get_oauth_token()
        if token:
            return {"Authorization": f"Bearer {token}", "User-Agent": self._user_agent}
        return {"User-Agent": self._user_agent}

    def _build_scan_list(self, advance_offset: bool = False) -> list[str]:
        """Build subreddit list based on tier config.

        Args:
            advance_offset: If True, advance the Tier-3 rotation counter after
                selecting this cycle's subreddits.  Should only be True when
                called from collect_all() so that the offset advances exactly
                once per real collection sweep (not at __init__ time).
        """
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
                if advance_offset:
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
        scan_list = self.subreddits if not self._use_tiers else self._build_scan_list(advance_offset=True)

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

        # Phase 2 fix: prefer authenticated oauth.reddit.com when creds available
        # (unauthenticated www.reddit.com JSON returns 403). OAuth host wants
        # the path WITHOUT a .json suffix; the legacy host wants it WITH.
        if self._authed:
            url = f"{self.OAUTH_URL}/r/{subreddit}/{sort}"
        else:
            url = f"{self.BASE_URL}/r/{subreddit}/{sort}.json"
        query = {"limit": limit, "raw_json": 1}
        if params:
            query.update(params)
        headers = await self._auth_headers()

        try:
            data = await _fetch_json(
                self._client, url, params=query, headers=headers, limiter=self._limiter
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

        # Log author handle only at DEBUG to avoid PII in INFO-level logs / persisted data
        log.debug("Reddit signal: post_id=%s author=%s subreddit=%s", post_id, author, subreddit)

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
                # author handle omitted from persisted metadata to avoid PII at rest
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

        if self._authed:
            url = f"{self.OAUTH_URL}/r/{subreddit}/hot"
        else:
            url = f"{self.BASE_URL}/r/{subreddit}/hot.json"
        headers = await self._auth_headers()
        try:
            data = await _fetch_json(
                self._client, url, params={"limit": limit, "raw_json": 1},
                headers=headers, limiter=self._limiter,
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
