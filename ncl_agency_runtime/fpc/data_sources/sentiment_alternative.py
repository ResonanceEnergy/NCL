"""Sentiment & alternative data ingesters.

APIs: Crypto Fear & Greed Index, NewsAPI, Google Trends (pytrends), Reddit (PRAW).
"""

import contextlib
import json
import logging
import os
from datetime import datetime

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class FearGreedIngester(BaseIngester):
    """Crypto Fear & Greed Index — daily 0-100 sentiment. No key required."""

    source_name = "fear_greed"
    BASE_URL = "https://api.alternative.me/fng/"

    def fetch(self, limit: int = 30) -> list[Signal]:
        signals: list[Signal] = []
        try:
            data = self._get_json(f"{self.BASE_URL}?limit={limit}&format=json")
            for entry in data.get("data", []):
                ts_int = int(entry.get("timestamp", 0))
                ts = datetime.fromtimestamp(ts_int) if ts_int else datetime.now()
                signals.append(self._make_signal(
                    source="FearGreed",
                    title=f"Fear & Greed — {entry.get('value', '')} ({entry.get('value_classification', '')})",
                    content=json.dumps(entry),
                    timestamp=ts,
                    meta={
                        "value": int(entry.get("value", 50)),
                        "classification": entry.get("value_classification", ""),
                    },
                ))
        except Exception:
            logger.warning("Fear & Greed Index fetch failed")
        logger.info("FearGreed: ingested %d signals", len(signals))
        return signals


class NewsAPIIngester(BaseIngester):
    """NewsAPI — search 150,000+ news sources."""

    source_name = "newsapi"
    BASE_URL = "https://newsapi.org/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("NEWSAPI_KEY", "")

    def fetch(
        self,
        queries: list[str] | None = None,
        page_size: int = 20,
    ) -> list[Signal]:
        if not self.api_key:
            logger.warning("NEWSAPI_KEY not set — skipping")
            return []

        queries = queries or [
            "climate change",
            "artificial intelligence",
            "global economy recession",
            "pandemic outbreak",
            "energy crisis",
        ]
        signals: list[Signal] = []
        for q in queries:
            try:
                import urllib.parse
                url = (
                    f"{self.BASE_URL}/everything"
                    f"?q={urllib.parse.quote(q)}"
                    f"&sortBy=publishedAt&pageSize={page_size}"
                    f"&apiKey={self.api_key}"
                )
                data = self._get_json(url)
                for art in data.get("articles", []):
                    ts = datetime.now()
                    if art.get("publishedAt"):
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
                    signals.append(self._make_signal(
                        source=f"NewsAPI:{q[:20]}",
                        title=art.get("title", ""),
                        content=art.get("description", "") or art.get("content", ""),
                        url=art.get("url", ""),
                        timestamp=ts,
                        meta={
                            "query": q,
                            "source_name": art.get("source", {}).get("name", ""),
                            "author": art.get("author", ""),
                        },
                    ))
            except Exception:
                logger.warning("NewsAPI fetch failed for query: %s", q)
        logger.info("NewsAPI: ingested %d signals", len(signals))
        return signals


class GoogleTrendsIngester(BaseIngester):
    """Google Trends via pytrends — search volume data. No key required."""

    source_name = "google_trends"

    def fetch(
        self,
        keywords: list[str] | None = None,
        timeframe: str = "today 3-m",
        geo: str = "",
    ) -> list[Signal]:
        keywords = keywords or [
            "recession", "inflation", "bitcoin", "AI",
            "climate change", "pandemic", "housing crash",
        ]
        signals: list[Signal] = []
        try:
            from pytrends.request import TrendReq
        except ImportError:
            logger.warning("pytrends not installed — skipping GoogleTrends")
            return signals

        try:
            pytrends = TrendReq(hl="en-US")
            # Process in batches of 5 (pytrends limit)
            for i in range(0, len(keywords), 5):
                batch = keywords[i:i + 5]
                pytrends.build_payload(batch, timeframe=timeframe, geo=geo)
                df = pytrends.interest_over_time()
                if df.empty:
                    continue
                for col in batch:
                    if col not in df.columns:
                        continue
                    for idx, val in df[col].items():
                        signals.append(self._make_signal(
                            source=f"GoogleTrends:{col}",
                            title=f"Trend '{col}' — {idx.date()} — {val}",
                            content=json.dumps({"keyword": col, "date": str(idx.date()), "interest": int(val)}),
                            timestamp=idx.to_pydatetime(),
                            meta={"keyword": col, "interest": int(val)},
                        ))
        except Exception:
            logger.warning("GoogleTrends fetch failed")
        logger.info("GoogleTrends: ingested %d signals", len(signals))
        return signals


class RedditSentimentIngester(BaseIngester):
    """Reddit via PRAW — subreddit sentiment from hot posts."""

    source_name = "reddit"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str = "FPC/0.4",
    ):
        self.client_id = client_id or os.environ.get("REDDIT_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("REDDIT_CLIENT_SECRET", "")
        self.user_agent = user_agent

    def fetch(
        self,
        subreddits: list[str] | None = None,
        limit: int = 25,
    ) -> list[Signal]:
        if not self.client_id or not self.client_secret:
            logger.warning("REDDIT_CLIENT_ID/SECRET not set — skipping Reddit")
            return []

        subreddits = subreddits or [
            "worldnews", "economics", "technology",
            "science", "energy", "collapse",
        ]
        signals: list[Signal] = []
        try:
            import praw
        except ImportError:
            logger.warning("praw not installed — skipping Reddit")
            return signals

        try:
            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            for sub_name in subreddits:
                try:
                    sub = reddit.subreddit(sub_name)
                    for post in sub.hot(limit=limit):
                        signals.append(self._make_signal(
                            source=f"Reddit:r/{sub_name}",
                            title=post.title,
                            content=(post.selftext or "")[:2000],
                            url=f"https://reddit.com{post.permalink}",
                            timestamp=datetime.fromtimestamp(post.created_utc),
                            meta={
                                "subreddit": sub_name,
                                "score": post.score,
                                "num_comments": post.num_comments,
                                "upvote_ratio": post.upvote_ratio,
                            },
                        ))
                except Exception:
                    logger.warning("Reddit fetch failed for r/%s", sub_name)
        except Exception:
            logger.warning("Reddit initialization failed")
        logger.info("Reddit: ingested %d signals", len(signals))
        return signals
