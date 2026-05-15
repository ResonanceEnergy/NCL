"""Awarebot scanner agent - collects intelligence from multiple sources.

Integrates with Paperclip cost tracking and MWP intelligence-scan workspace.
Implements exponential backoff retry and per-platform rate limiting.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..ncl_brain.models import InsightSignal

logger = logging.getLogger(__name__)


class _RateLimiter:
    """Simple token-bucket rate limiter per platform (thread-safe with asyncio.Lock)."""

    def __init__(self, calls_per_minute: int = 10):
        self.calls_per_minute = calls_per_minute
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.monotonic()
            # Purge timestamps older than 60 seconds
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) >= self.calls_per_minute:
                wait = 60 - (now - self._timestamps[0])
                if wait > 0:
                    logger.debug(f"Rate limit reached, waiting {wait:.1f}s")
                    await asyncio.sleep(wait)
            self._timestamps.append(time.monotonic())


class Scanner:
    """
    Multi-source intelligence scanner.

    Scans X, YouTube, and Reddit for signals.
    Scores importance using configurable multi-factor formula.
    Includes exponential backoff retry and per-platform rate limiting.
    """

    def __init__(
        self,
        x_bearer_token: Optional[str] = None,
        youtube_api_key: Optional[str] = None,
        reddit_client_id: Optional[str] = None,
        reddit_client_secret: Optional[str] = None,
        reddit_user_agent: str = "NCL-Awarebot/1.0",
        importance_weights: Optional[dict[str, float]] = None,
    ) -> None:
        """
        Initialize scanner with API credentials.

        Args:
            x_bearer_token: X API bearer token
            youtube_api_key: YouTube Data API key
            reddit_client_id: Reddit OAuth client ID
            reddit_client_secret: Reddit OAuth client secret
            reddit_user_agent: Reddit user agent string
            importance_weights: Override default importance factor weights
        """
        self.x_bearer_token = x_bearer_token
        self.youtube_api_key = youtube_api_key
        self.reddit_client_id = reddit_client_id
        self.reddit_client_secret = reddit_client_secret
        self.reddit_user_agent = reddit_user_agent
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Configurable importance weights (Gap 11 fix)
        self.importance_weights = importance_weights or {
            "relevance": 0.3,
            "novelty": 0.25,
            "actionability": 0.25,
            "source_authority": 0.1,
            "time_sensitivity": 0.1,
        }

        # Per-platform rate limiters
        self._rate_limiters = {
            "x": _RateLimiter(calls_per_minute=15),  # X API basic tier
            "youtube": _RateLimiter(calls_per_minute=30),
            "reddit": _RateLimiter(calls_per_minute=10),
        }

        # Reddit OAuth token cache
        self._reddit_token: Optional[str] = None
        self._reddit_token_expires: float = 0.0  # monotonic time

        # Retry config
        self._max_retries = 3
        self._base_delay = 1.0  # seconds

    async def _request_with_retry(
        self, method: str, url: str, platform: str, **kwargs
    ) -> httpx.Response:
        """
        Make an HTTP request with exponential backoff retry and rate limiting.

        Follows Paperclip cost tracking patterns — each retry is logged.
        """
        limiter = self._rate_limiters.get(platform)
        if limiter:
            await limiter.acquire()

        last_error = None
        for attempt in range(self._max_retries):
            try:
                if method == "GET":
                    resp = await self.http_client.get(url, **kwargs)
                else:
                    resp = await self.http_client.post(url, **kwargs)

                # Handle rate limit responses
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", self._base_delay * (2 ** attempt)))
                    logger.warning(f"[{platform}] Rate limited, waiting {retry_after}s (attempt {attempt + 1})")
                    await asyncio.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code in (401, 403):
                    raise  # Auth errors don't retry
                delay = self._base_delay * (2 ** attempt)
                logger.warning(f"[{platform}] HTTP {e.response.status_code}, retrying in {delay:.1f}s (attempt {attempt + 1})")
                await asyncio.sleep(delay)

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                delay = self._base_delay * (2 ** attempt)
                logger.warning(f"[{platform}] Connection error, retrying in {delay:.1f}s (attempt {attempt + 1})")
                await asyncio.sleep(delay)

        raise last_error or Exception(f"Max retries ({self._max_retries}) exhausted for {platform}")

    async def scan_x(self, query: str, max_results: int = 10) -> list[InsightSignal]:
        """
        Scan X (Twitter) for signals matching query.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of InsightSignals from X
        """
        if not self.x_bearer_token:
            return []

        signals = []
        try:
            response = await self._request_with_retry(
                "GET",
                "https://api.twitter.com/2/tweets/search/recent",
                platform="x",
                params={
                    "query": query,
                    "max_results": min(max_results, 100),
                    "tweet.fields": "created_at,public_metrics",
                    "expansions": "author_id",
                    "user.fields": "verified,public_metrics",
                },
                headers={"Authorization": f"Bearer {self.x_bearer_token}"},
            )
            data = response.json()

            for tweet in data.get("data", []):
                signal = InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="x",
                    content=tweet["text"],
                    url=f"https://twitter.com/i/web/status/{tweet['id']}",
                    importance_score=0.0,  # Will be computed
                    relevance=0.7,
                    novelty=0.6,
                    actionability=0.5,
                    source_authority=0.6,
                    time_sensitivity=0.7,
                    timestamp=datetime.now(timezone.utc),
                    tags=["x", query.lower()],
                )
                signal.importance_score = self._compute_importance(signal)
                signals.append(signal)
        except Exception as e:
            logger.warning(f"Failed to scan X for query '{query}': {e}")

        return signals

    async def scan_youtube(
        self, query: str, max_results: int = 10
    ) -> list[InsightSignal]:
        """
        Scan YouTube for signals matching query.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of InsightSignals from YouTube
        """
        if not self.youtube_api_key:
            return []

        signals = []
        try:
            response = await self._request_with_retry(
                "GET",
                "https://www.googleapis.com/youtube/v3/search",
                platform="youtube",
                params={
                    "q": query,
                    "maxResults": min(max_results, 50),
                    "part": "snippet",
                    "type": "video",
                    "order": "relevance",
                },
                # API key in header — keeps it out of URLs, server logs, and
                # browser history (Google also accepts X-Goog-Api-Key).
                headers={"X-Goog-Api-Key": self.youtube_api_key},
            )
            data = response.json()

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                signal = InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="youtube",
                    content=f"{snippet.get('title', '')} - {snippet.get('description', '')}",
                    url=f"https://youtu.be/{item['id']['videoId']}",
                    importance_score=0.0,
                    relevance=0.6,
                    novelty=0.5,
                    actionability=0.4,
                    source_authority=0.7,
                    time_sensitivity=0.3,
                    timestamp=datetime.now(timezone.utc),
                    tags=["youtube", query.lower()],
                )
                signal.importance_score = self._compute_importance(signal)
                signals.append(signal)
        except Exception as e:
            logger.warning(f"Failed to scan YouTube for query '{query}': {e}")

        return signals

    async def scan_reddit(self, subreddit: str, max_results: int = 10) -> list[InsightSignal]:
        """
        Scan Reddit for signals from subreddit.

        Args:
            subreddit: Subreddit name (without r/)
            max_results: Maximum results to return

        Returns:
            List of InsightSignals from Reddit
        """
        if not self.reddit_client_id or not self.reddit_client_secret:
            return []

        signals = []
        try:
            # Get Reddit auth token (cached with expiry)
            token = await self._get_reddit_token()

            # Fetch subreddit posts (with retry)
            posts_response = await self._request_with_retry(
                "GET",
                f"https://oauth.reddit.com/r/{subreddit}/hot",
                platform="reddit",
                params={"limit": min(max_results, 100)},
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": self.reddit_user_agent,
                },
            )
            data = posts_response.json()

            for post in data.get("data", {}).get("children", []):
                post_data = post.get("data", {})
                signal = InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="reddit",
                    content=f"{post_data.get('title', '')} - {post_data.get('selftext', '')}",
                    url=f"https://reddit.com{post_data.get('permalink', '')}",
                    importance_score=0.0,
                    relevance=0.5,
                    novelty=0.6,
                    actionability=0.6,
                    source_authority=0.4,
                    time_sensitivity=0.4,
                    timestamp=datetime.now(timezone.utc),
                    tags=["reddit", f"r/{subreddit}"],
                )
                signal.importance_score = self._compute_importance(signal)
                signals.append(signal)
        except Exception as e:
            logger.warning(f"Failed to scan Reddit subreddit '{subreddit}': {e}")

        return signals

    async def _get_reddit_token(self) -> str:
        """Get a Reddit OAuth token, returning cached token if still valid."""
        now = time.monotonic()
        if self._reddit_token and now < self._reddit_token_expires:
            return self._reddit_token

        auth = (self.reddit_client_id, self.reddit_client_secret)
        token_response = await self._request_with_retry(
            "POST",
            "https://www.reddit.com/api/v1/access_token",
            platform="reddit",
            auth=auth,
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self.reddit_user_agent},
        )
        data = token_response.json()
        self._reddit_token = data["access_token"]
        # Reddit tokens last 3600s; expire 60s early to avoid edge cases
        expires_in = data.get("expires_in", 3600)
        self._reddit_token_expires = time.monotonic() + max(0, expires_in - 60)
        return self._reddit_token

    def _compute_importance(self, signal: InsightSignal) -> float:
        """
        Compute importance score using configurable multi-factor formula.

        Default weights (configurable via importance_weights):
        - relevance: 0.3
        - novelty: 0.25
        - actionability: 0.25
        - source_authority: 0.1
        - time_sensitivity: 0.1

        Follows MWP intelligence-scan scoring conventions.

        Args:
            signal: InsightSignal to score

        Returns:
            Importance score 0-100
        """
        w = self.importance_weights
        importance = (
            (signal.relevance * w.get("relevance", 0.3))
            + (signal.novelty * w.get("novelty", 0.25))
            + (signal.actionability * w.get("actionability", 0.25))
            + (signal.source_authority * w.get("source_authority", 0.1))
            + (signal.time_sensitivity * w.get("time_sensitivity", 0.1))
        )
        return max(0.0, min(100.0, importance * 100.0))

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()
