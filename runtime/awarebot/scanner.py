"""Awarebot scanner agent - collects intelligence from multiple sources."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..ncl_brain.models import InsightSignal

logger = logging.getLogger(__name__)


class Scanner:
    """
    Multi-source intelligence scanner.

    Scans X, YouTube, and Reddit for signals.
    Scores importance using multi-factor formula.
    """

    def __init__(
        self,
        x_bearer_token: Optional[str] = None,
        youtube_api_key: Optional[str] = None,
        reddit_client_id: Optional[str] = None,
        reddit_client_secret: Optional[str] = None,
        reddit_user_agent: str = "NCL-Awarebot/1.0",
    ) -> None:
        """
        Initialize scanner with API credentials.

        Args:
            x_bearer_token: X API bearer token
            youtube_api_key: YouTube Data API key
            reddit_client_id: Reddit OAuth client ID
            reddit_client_secret: Reddit OAuth client secret
            reddit_user_agent: Reddit user agent string
        """
        self.x_bearer_token = x_bearer_token
        self.youtube_api_key = youtube_api_key
        self.reddit_client_id = reddit_client_id
        self.reddit_client_secret = reddit_client_secret
        self.reddit_user_agent = reddit_user_agent
        self.http_client = httpx.AsyncClient(timeout=30.0)

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
            response = await self.http_client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": min(max_results, 100),
                    "tweet.fields": "created_at,public_metrics",
                    "expansions": "author_id",
                    "user.fields": "verified,public_metrics",
                },
                headers={"Authorization": f"Bearer {self.x_bearer_token}"},
            )
            response.raise_for_status()
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
            response = await self.http_client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "q": query,
                    "key": self.youtube_api_key,
                    "maxResults": min(max_results, 50),
                    "part": "snippet",
                    "type": "video",
                    "order": "relevance",
                },
            )
            response.raise_for_status()
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
            # Get Reddit auth token
            auth = (self.reddit_client_id, self.reddit_client_secret)
            token_response = await self.http_client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.reddit_user_agent},
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]

            # Fetch subreddit posts
            posts_response = await self.http_client.get(
                f"https://oauth.reddit.com/r/{subreddit}/hot",
                params={"limit": min(max_results, 100)},
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": self.reddit_user_agent,
                },
            )
            posts_response.raise_for_status()
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

    def _compute_importance(self, signal: InsightSignal) -> float:
        """
        Compute importance score using multi-factor formula.

        Formula: importance = (relevance * 0.3) + (novelty * 0.25) +
                 (actionability * 0.25) + (source_authority * 0.1) +
                 (time_sensitivity * 0.1)

        Args:
            signal: InsightSignal to score

        Returns:
            Importance score 0-100
        """
        importance = (
            (signal.relevance * 0.3)
            + (signal.novelty * 0.25)
            + (signal.actionability * 0.25)
            + (signal.source_authority * 0.1)
            + (signal.time_sensitivity * 0.1)
        )
        return max(0.0, min(100.0, importance * 100.0))

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()
