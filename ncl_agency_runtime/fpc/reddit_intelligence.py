"""Reddit Intelligence Engine — Public Subreddit Feed Ingestion.

Monitors high-signal subreddits via their public RSS feeds
(``https://www.reddit.com/r/<sub>/top.rss?t=day``) and classifies
posts for trend prediction and strategic routing.

No API key required — Reddit exposes public RSS for every subreddit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_FPC_ROOT = Path(__file__).resolve().parent

ATOM_NS = "http://www.w3.org/2005/Atom"


# ── Enums ───────────────────────────────────────────────────────


class RedditDomain(StrEnum):
    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"
    MACHINE_LEARNING = "machine_learning"
    TECHNOLOGY = "technology"
    PROGRAMMING = "programming"
    CRYPTO = "crypto"
    FINANCE = "finance"
    SCIENCE = "science"
    FUTURISM = "futurism"
    GEOPOLITICS = "geopolitics"
    ENERGY = "energy"
    GENERAL = "general"


class PostHeat(StrEnum):
    """How much engagement traction a post has."""
    COLD = "cold"
    WARM = "warm"
    HOT = "hot"
    VIRAL = "viral"


class RedditSignalType(StrEnum):
    TRENDING_POST = "trending_post"
    BREAKTHROUGH_DISCUSSION = "breakthrough_discussion"
    SENTIMENT_SHIFT = "sentiment_shift"
    NEW_TOOL_ANNOUNCEMENT = "new_tool_announcement"
    COMMUNITY_DEBATE = "community_debate"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class RedditPost:
    """A single Reddit post signal."""

    post_id: str
    subreddit: str
    title: str
    summary: str
    domain: RedditDomain
    signal_type: RedditSignalType
    heat: PostHeat
    url: str = ""
    author: str = ""
    published_at: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.subreddit}:{self.title[:80]}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.published_at:
            self.published_at = datetime.now(UTC).isoformat()


@dataclass
class RedditDigest:
    """Aggregated Reddit intelligence digest."""

    timestamp: str
    posts: list[RedditPost] = field(default_factory=list)
    domain_counts: dict[str, int] = field(default_factory=dict)
    subreddit_counts: dict[str, int] = field(default_factory=dict)
    hot_topics: list[str] = field(default_factory=list)
    trend_summary: str = ""


# ── Classifier ──────────────────────────────────────────────────


class RedditClassifier:
    """Classify Reddit posts by domain and signal type."""

    DOMAIN_KEYWORDS: ClassVar[dict[str, list[str]]] = {
        "artificial_intelligence": ["ai", "artificial intelligence", "chatgpt",
                                    "gpt", "llm", "openai", "anthropic",
                                    "claude", "gemini", "copilot"],
        "machine_learning": ["machine learning", "neural network", "training",
                             "fine-tuning", "dataset", "pytorch", "tensorflow",
                             "huggingface", "model weights"],
        "technology": ["tech", "software", "hardware", "startup", "saas",
                       "app", "platform", "api", "cloud"],
        "programming": ["python", "rust", "javascript", "golang", "code",
                        "developer", "programming", "framework", "library"],
        "crypto": ["bitcoin", "ethereum", "crypto", "blockchain", "defi",
                   "nft", "web3", "token", "mining"],
        "finance": ["market", "stock", "invest", "fed", "inflation",
                    "economy", "gdp", "earnings", "portfolio"],
        "science": ["research", "paper", "study", "experiment", "physics",
                    "biology", "chemistry", "peer-review"],
        "futurism": ["future", "singularity", "agi", "transhumanism",
                     "automation", "robotics", "space", "mars"],
        "geopolitics": ["china", "war", "policy", "sanctions", "nato",
                        "diplomacy", "election", "government"],
        "energy": ["energy", "solar", "nuclear", "oil", "renewable",
                   "battery", "grid", "hydrogen", "fusion"],
    }

    SIGNAL_KEYWORDS: ClassVar[dict[str, list[str]]] = {
        "breakthrough_discussion": ["breakthrough", "first ever", "unprecedented",
                                    "revolutionary", "game changer"],
        "new_tool_announcement": ["released", "launched", "announcing", "v1",
                                  "v2", "open source", "just dropped"],
        "sentiment_shift": ["actually", "unpopular opinion", "changed my mind",
                            "overrated", "underrated"],
        "community_debate": ["debate", "vs", "compared to", "which is better",
                             "hot take"],
    }

    @classmethod
    def classify_domain(cls, title: str, summary: str) -> RedditDomain:
        text = f"{title} {summary}".lower()
        scores: dict[str, int] = {}
        for dom, keywords in cls.DOMAIN_KEYWORDS.items():
            scores[dom] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda d: scores[d])
        if scores[best] > 0:
            return RedditDomain(best)
        return RedditDomain.GENERAL

    @classmethod
    def classify_signal(cls, title: str, summary: str) -> RedditSignalType:
        text = f"{title} {summary}".lower()
        for sig_type, keywords in cls.SIGNAL_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return RedditSignalType(sig_type)
        return RedditSignalType.TRENDING_POST


# ── Scraper ─────────────────────────────────────────────────────


class RedditIntelligence:
    """Monitor high-signal subreddits via public RSS feeds."""

    DEFAULT_SUBREDDITS: ClassVar[list[str]] = []  # loaded from registry

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls.DEFAULT_SUBREDDITS:
            from .topics_registry import get_subreddits
            cls.DEFAULT_SUBREDDITS = get_subreddits()

    def __init__(self, subreddits: list[str] | None = None,
                 cache_dir: Path | None = None):
        self._ensure_loaded()
        self._subs = subreddits or self.DEFAULT_SUBREDDITS
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "reddit_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: float = 0.0
        self._rate_limit_s: float = 3.0

    def collect(self) -> RedditDigest:
        """Collect top posts from all monitored subreddits."""
        posts: list[RedditPost] = []

        for sub in self._subs:
            url = f"https://www.reddit.com/r/{sub}/top.rss?t=day"
            posts.extend(self._parse_feed(url, sub))

        # Deduplicate
        seen: set[str] = set()
        unique: list[RedditPost] = []
        for post in posts:
            if post.fingerprint not in seen:
                seen.add(post.fingerprint)
                unique.append(post)

        domain_counts: dict[str, int] = {}
        sub_counts: dict[str, int] = {}
        for post in unique:
            domain_counts[post.domain] = domain_counts.get(post.domain, 0) + 1
            sub_counts[post.subreddit] = sub_counts.get(post.subreddit, 0) + 1

        hot_topics = [p.title for p in unique if p.heat in (PostHeat.HOT, PostHeat.VIRAL)]

        digest = RedditDigest(
            timestamp=datetime.now(UTC).isoformat(),
            posts=unique,
            domain_counts=domain_counts,
            subreddit_counts=sub_counts,
            hot_topics=hot_topics[:10],
            trend_summary=f"{len(unique)} posts from {len(sub_counts)} subreddits",
        )

        self._cache_digest(digest)
        return digest

    def _parse_feed(self, url: str, subreddit: str) -> list[RedditPost]:
        """Parse Reddit RSS (Atom) feed for a subreddit."""
        posts: list[RedditPost] = []
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={"User-Agent": "NCL-FPC/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()
                root = ElementTree.fromstring(xml_data)

                for entry in root.findall(f"{{{ATOM_NS}}}entry"):
                    title_el = entry.find(f"{{{ATOM_NS}}}title")
                    link_el = entry.find(f"{{{ATOM_NS}}}link")
                    content_el = entry.find(f"{{{ATOM_NS}}}content")
                    updated_el = entry.find(f"{{{ATOM_NS}}}updated")
                    author_el = entry.find(f"{{{ATOM_NS}}}author")

                    title = title_el.text if title_el is not None and title_el.text else ""
                    href = link_el.get("href", "") if link_el is not None else ""
                    summary = content_el.text[:500] if content_el is not None and content_el.text else ""

                    author_name = ""
                    if author_el is not None:
                        name_el = author_el.find(f"{{{ATOM_NS}}}name")
                        if name_el is not None and name_el.text:
                            author_name = name_el.text

                    posts.append(RedditPost(
                        post_id=hashlib.sha256(href.encode()).hexdigest()[:16],
                        subreddit=subreddit,
                        title=title,
                        summary=summary,
                        domain=RedditClassifier.classify_domain(title, summary),
                        signal_type=RedditClassifier.classify_signal(title, summary),
                        heat=PostHeat.WARM,  # Default; upgrade later with upvotes
                        url=href,
                        author=author_name,
                        published_at=updated_el.text if updated_el is not None and updated_el.text else "",
                    ))
        except Exception as exc:
            logger.debug("Reddit feed r/%s failed: %s", subreddit, exc)

        return posts[:10]  # Latest 10 per subreddit

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: RedditDigest) -> None:
        cache_file = self._cache_dir / f"reddit_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            cache_file.write_text(
                json.dumps({"posts": [asdict(p) for p in digest.posts],
                            "hot_topics": digest.hot_topics,
                            "summary": digest.trend_summary,
                            "timestamp": digest.timestamp},
                           indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to cache Reddit digest: %s", exc)
