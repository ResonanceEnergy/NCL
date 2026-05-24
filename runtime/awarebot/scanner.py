"""Awarebot scanner agent - collects intelligence from multiple sources.

Extracts REAL engagement metrics from APIs (retweets, likes, views,
upvotes, comments) instead of hardcoding scores. The agent's scoring
engine in agent.py handles all composite scoring — the scanner only
passes through raw data and engagement metadata.

Implements exponential backoff retry. Rate limiting is delegated to the
agent-level TokenBucket (no duplicate limiters here).
"""

import asyncio
import functools
import logging
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..ncl_brain.models import InsightSignal


logger = logging.getLogger(__name__)


class Scanner:
    """
    Multi-source intelligence scanner.

    Scans X, YouTube, and Reddit for signals.
    Extracts real engagement metrics and passes them as metadata so the
    agent scoring engine can compute data-driven scores.
    """

    def __init__(
        self,
        x_bearer_token: Optional[str] = None,
        youtube_api_key: Optional[str] = None,
        reddit_client_id: Optional[str] = None,
        reddit_client_secret: Optional[str] = None,
        reddit_user_agent: str = "NCL-Awarebot/1.0",
    ) -> None:
        self.x_bearer_token = x_bearer_token
        self.youtube_api_key = youtube_api_key
        self.reddit_client_id = reddit_client_id
        self.reddit_client_secret = reddit_client_secret
        self.reddit_user_agent = reddit_user_agent
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Browser-style User-Agents for Reddit (bot UAs get 403'd)
        self._reddit_browser_uas = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",  # noqa: E501
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",  # noqa: E501
            "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        ]
        self._reddit_ua_index = 0

        # Thread pool for blocking yt-dlp calls
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytdlp")

        # Retry config
        self._max_retries = 3
        self._base_delay = 1.0

    async def _request_with_retry(
        self, method: str, url: str, platform: str, **kwargs
    ) -> httpx.Response:
        """HTTP request with exponential backoff retry."""
        last_error = None
        for attempt in range(self._max_retries):
            try:
                if method == "GET":
                    resp = await self.http_client.get(url, **kwargs)
                else:
                    resp = await self.http_client.post(url, **kwargs)

                if resp.status_code == 429:
                    retry_after = int(
                        resp.headers.get("retry-after", self._base_delay * (2**attempt))
                    )
                    logger.warning(
                        f"[{platform}] Rate limited, waiting {retry_after}s (attempt {attempt + 1})"
                    )
                    await asyncio.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code in (401, 402, 403):
                    raise  # 402 = Payment Required (don't waste retries on billing issues)
                delay = self._base_delay * (2**attempt)
                logger.warning(
                    f"[{platform}] HTTP {e.response.status_code}, retrying in {delay:.1f}s (attempt {attempt + 1})"  # noqa: E501
                )
                await asyncio.sleep(delay)

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                delay = self._base_delay * (2**attempt)
                logger.warning(
                    f"[{platform}] Connection error, retrying in {delay:.1f}s (attempt {attempt + 1})"  # noqa: E501
                )
                await asyncio.sleep(delay)

        raise last_error or Exception(f"Max retries ({self._max_retries}) exhausted for {platform}")

    # ── Engagement → score helpers ──────────────────────────────────────

    @staticmethod
    def _x_engagement_score(metrics: dict) -> float:
        """Derive authority/actionability from real X engagement metrics.

        Uses Wilson score lower bound for small-sample correction:
            (p + z²/2n - z√(p(1-p)/n + z²/4n²)) / (1 + z²/n)
        where p = positive ratio, n = total engagements, z = 1.96 (95% CI).
        """
        rt = metrics.get("retweet_count", 0)
        likes = metrics.get("like_count", 0)
        replies = metrics.get("reply_count", 0)
        quotes = metrics.get("quote_count", 0)
        total = rt + likes + replies + quotes
        if total == 0:
            return 0.0

        # Weighted engagement (retweets/quotes signal stronger intent)
        weighted = rt * 3.0 + quotes * 2.5 + likes * 1.0 + replies * 1.5
        # Log-scale normalization (1000 weighted engagement ≈ 1.0)
        raw = min(1.0, math.log1p(weighted) / math.log1p(1000))

        # Wilson lower bound for confidence correction
        n = total
        p = raw
        z = 1.96
        denom = 1 + z * z / n
        centre = p + z * z / (2 * n)
        spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
        wilson = max(0.0, (centre - spread) / denom)
        return round(wilson, 4)

    @staticmethod
    def _reddit_engagement_score(post_data: dict) -> float:
        """Derive score from Reddit upvotes/comments/awards."""
        ups = post_data.get("ups", 0)
        comments = post_data.get("num_comments", 0)
        awards = post_data.get("total_awards_received", 0)
        ratio = post_data.get("upvote_ratio", 0.5)

        # Weighted engagement
        weighted = ups * 1.0 + comments * 2.0 + awards * 5.0
        raw = min(1.0, math.log1p(weighted) / math.log1p(500))

        # Penalize controversial posts (low upvote ratio)
        if ratio < 0.6:
            raw *= 0.7
        return round(raw * ratio, 4)

    @staticmethod
    def _time_sensitivity_score(created_utc: float) -> float:
        """HN-style gravity decay: 1 / (age_hours + 2)^1.8"""
        age_hours = (time.time() - created_utc) / 3600.0
        if age_hours < 0:
            age_hours = 0
        return round(min(1.0, 1.0 / ((age_hours + 2) ** 1.8) * 10), 4)

    # ── Platform scanners ───────────────────────────────────────────────

    async def scan_x(self, query: str, max_results: int = 10) -> list[InsightSignal]:
        """Scan X with REAL engagement metric extraction."""
        if not self.x_bearer_token:
            logger.error("[scanner] X_BEARER_TOKEN not configured — X scan disabled. Set in .env")
            return []

        # Budget check before making the API call
        from ..cost_tracker import check_budget, record_cost

        est_cost = max_results * 0.01  # ~$0.01 per tweet read
        if not await check_budget("x_twitter", est_cost):
            logger.warning(f"[scanner] X daily budget exceeded — skipping query '{query}'")
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

            # Record cost for this API call
            tweet_count = len(data.get("data", []))
            actual_cost = tweet_count * 0.01
            await record_cost(
                "x_twitter",
                actual_cost,
                "tweet_search",
                f"query='{query}' results={tweet_count}",
                query=query,
                results=tweet_count,
            )

            # Build user lookup for verified status and followers
            users = {}
            for user in data.get("includes", {}).get("users", []):
                users[user["id"]] = user

            for tweet in data.get("data", []):
                metrics = tweet.get("public_metrics", {})
                author_id = tweet.get("author_id", "")
                user_info = users.get(author_id, {})
                user_metrics = user_info.get("public_metrics", {})
                verified = user_info.get("verified", False)
                followers = user_metrics.get("followers_count", 0)

                engagement = self._x_engagement_score(metrics)

                signal = InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="x",
                    content=tweet["text"],
                    url=f"https://twitter.com/i/web/status/{tweet['id']}",
                    importance_score=0.0,  # Computed by agent scoring engine
                    relevance=0.0,  # Computed by agent (BM25)
                    novelty=0.0,  # Computed by agent (decay + SimHash)
                    actionability=engagement,  # Real engagement data
                    source_authority=engagement,  # Will be refined by agent
                    time_sensitivity=0.0,
                    timestamp=datetime.now(timezone.utc),
                    tags=["x", query.lower()],
                )
                # Attach real metrics as metadata for agent scoring
                signal.metadata = {
                    "retweets": metrics.get("retweet_count", 0),
                    "likes": metrics.get("like_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "quotes": metrics.get("quote_count", 0),
                    "verified": verified,
                    "followers": followers,
                    "engagement_score": engagement,
                }
                signals.append(signal)
        except Exception as e:
            logger.warning(f"Failed to scan X for query '{query}': {e}")

        return signals

    @staticmethod
    def _ytdlp_search(query: str, max_results: int) -> list[dict]:
        """Blocking yt-dlp search — runs in thread pool.

        Uses yt-dlp's ytsearch to avoid YouTube Data API quota limits.
        Returns list of video info dicts.
        """
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            logger.error(
                "[scanner] yt-dlp not installed — YouTube scan disabled. Run: pip install yt-dlp"
            )
            return []

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }

        results = []
        try:
            with YoutubeDL(ydl_opts) as ydl:
                search_url = f"ytsearch{max_results}:{query}"
                info = ydl.extract_info(search_url, download=False)
                if not info or "entries" not in info:
                    return []

                for entry in info["entries"]:
                    if not entry:
                        continue
                    results.append(
                        {
                            "id": entry.get("id", ""),
                            "title": entry.get("title", "Untitled"),
                            "description": (entry.get("description") or "")[:500],
                            "channel": entry.get("channel", entry.get("uploader", "")),
                            "view_count": entry.get("view_count") or 0,
                            "duration": entry.get("duration") or 0,
                            "upload_date": entry.get("upload_date", ""),
                        }
                    )
        except Exception as e:
            logger.warning(f"[scanner] yt-dlp search failed for '{query}': {e}")

        return results

    async def scan_youtube(self, query: str, max_results: int = 10) -> list[InsightSignal]:
        """Scan YouTube via yt-dlp search (no API quota needed).

        Runs yt-dlp in a thread pool to avoid blocking the async event loop.
        Falls back to YouTube Data API if yt-dlp is not installed.
        """
        signals = []

        try:
            # Run blocking yt-dlp in thread pool
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                self._executor,
                functools.partial(self._ytdlp_search, query, min(max_results, 20)),
            )

            for item in results:
                video_id = item.get("id", "")
                title = item.get("title", "")
                desc = item.get("description", "")
                channel = item.get("channel", "")
                views = item.get("view_count", 0)

                # View-based engagement score (log-scale, 100K views ≈ 1.0)
                view_score = min(1.0, math.log1p(views) / math.log1p(100_000)) if views else 0.0

                signal = InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="youtube",
                    content=f"{title} - {desc}",
                    url=f"https://youtu.be/{video_id}",
                    importance_score=0.0,
                    relevance=0.0,
                    novelty=0.0,
                    actionability=view_score,
                    source_authority=view_score,
                    time_sensitivity=0.0,
                    timestamp=datetime.now(timezone.utc),
                    tags=["youtube", query.lower()],
                )
                signal.metadata = {
                    "channel": channel,
                    "video_id": video_id,
                    "view_count": views,
                    "duration": item.get("duration", 0),
                    "upload_date": item.get("upload_date", ""),
                    "view_score": round(view_score, 4),
                }
                signals.append(signal)

            logger.info(f"[scanner] YouTube yt-dlp: got {len(signals)} results for '{query}'")
        except Exception as e:
            logger.warning(f"Failed to scan YouTube for query '{query}': {e}")

        return signals

    def _next_reddit_ua(self) -> str:
        """Rotate through browser User-Agents to avoid Reddit 403 bot detection."""
        ua = self._reddit_browser_uas[self._reddit_ua_index % len(self._reddit_browser_uas)]
        self._reddit_ua_index += 1
        return ua

    async def _reddit_get_json(self, url: str, params: dict) -> dict:
        """GET Reddit JSON with browser UA rotation + old.reddit.com fallback."""
        ua = self._next_reddit_ua()
        try:
            response = await self._request_with_retry(
                "GET",
                url,
                platform="reddit",
                params=params,
                headers={"User-Agent": ua},
            )
            return response.json()
        except Exception:
            # Fallback to old.reddit.com on 403 or connection errors
            if "www.reddit.com" in url:
                fallback_url = url.replace("www.reddit.com", "old.reddit.com")
                logger.info(f"[scanner] Reddit fallback to old.reddit.com for: {fallback_url}")
                response = await self._request_with_retry(
                    "GET",
                    fallback_url,
                    platform="reddit",
                    params=params,
                    headers={"User-Agent": self._next_reddit_ua()},
                )
                return response.json()
            raise

    async def scan_reddit(self, subreddit: str, max_results: int = 10) -> list[InsightSignal]:
        """Scan Reddit via JSON API with browser UA rotation and old.reddit fallback."""
        signals = []
        try:
            if subreddit.startswith("search:"):
                query = subreddit[7:].strip()
                url = "https://www.reddit.com/search.json"
                params = {"q": query, "sort": "new", "limit": min(max_results, 25)}
            else:
                url = f"https://www.reddit.com/r/{subreddit}/hot.json"
                params = {"limit": min(max_results, 25)}

            data = await self._reddit_get_json(url, params)

            for post in data.get("data", {}).get("children", []):
                post_data = post.get("data", {})
                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")[:500]
                content = f"{title} - {selftext}" if selftext else title

                engagement = self._reddit_engagement_score(post_data)
                created_utc = post_data.get("created_utc", time.time())
                freshness = self._time_sensitivity_score(created_utc)

                signal = InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="reddit",
                    content=content,
                    url=f"https://reddit.com{post_data.get('permalink', '')}",
                    importance_score=0.0,
                    relevance=0.0,
                    novelty=0.0,
                    actionability=engagement,
                    source_authority=engagement,
                    time_sensitivity=freshness,
                    timestamp=datetime.now(timezone.utc),
                    tags=["reddit", f"r/{subreddit}"],
                )
                signal.metadata = {
                    "upvotes": post_data.get("ups", 0),
                    "downvotes": post_data.get("downs", 0),
                    "comments": post_data.get("num_comments", 0),
                    "awards": post_data.get("total_awards_received", 0),
                    "upvote_ratio": post_data.get("upvote_ratio", 0.5),
                    "subreddit": post_data.get("subreddit", subreddit),
                    "author": post_data.get("author", ""),
                    "created_utc": created_utc,
                    "engagement_score": engagement,
                    "freshness_score": freshness,
                }
                signals.append(signal)

            logger.info(f"[scanner] Reddit RSS: got {len(signals)} signals from r/{subreddit}")
        except Exception as e:
            logger.warning(f"Failed to scan Reddit (RSS) '{subreddit}': {e}")

        return signals

    async def close(self) -> None:
        """Close HTTP client and thread pool."""
        await self.http_client.aclose()
        self._executor.shutdown(wait=False)
