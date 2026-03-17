"""Google Trends Intelligence Engine — Public Trends RSS Ingestion.

Monitors Google Trends for trending topics, daily search trends,
and real-time searches via their public RSS feed and sitemap.

No API key required — Google Trends exposes RSS at
``https://trends.google.com/trends/trendingsearches/daily/rss?geo=US``
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

HT_NS = "https://trends.google.com/trends/trendingsearches/daily"


# ── Enums ───────────────────────────────────────────────────────


class TrendCategory(StrEnum):
    TECHNOLOGY = "technology"
    BUSINESS = "business"
    ENTERTAINMENT = "entertainment"
    SPORTS = "sports"
    POLITICS = "politics"
    SCIENCE = "science"
    HEALTH = "health"
    WORLD = "world"
    GENERAL = "general"


class TrendMomentum(StrEnum):
    EMERGING = "emerging"
    RISING = "rising"
    PEAKING = "peaking"
    DECLINING = "declining"


class SearchVolume(StrEnum):
    LOW = "low"           # < 50K
    MODERATE = "moderate"  # 50K-200K
    HIGH = "high"          # 200K-500K
    MASSIVE = "massive"    # 500K+


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class TrendSignal:
    """A single Google Trends trending topic signal."""

    trend_id: str
    query: str
    category: TrendCategory
    momentum: TrendMomentum
    volume: SearchVolume
    traffic_estimate: str = ""
    news_headline: str = ""
    news_url: str = ""
    geo: str = "US"
    published_at: str = ""
    related_queries: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"gtrends:{self.query}:{self.geo}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.published_at:
            self.published_at = datetime.now(UTC).isoformat()


@dataclass
class TrendsDigest:
    """Aggregated Google Trends intelligence digest."""

    timestamp: str
    signals: list[TrendSignal] = field(default_factory=list)
    category_counts: dict[str, int] = field(default_factory=dict)
    top_queries: list[str] = field(default_factory=list)
    geo_coverage: list[str] = field(default_factory=list)
    trend_summary: str = ""


# ── Classifier ──────────────────────────────────────────────────


class TrendClassifier:
    """Classify Google Trends queries into categories.

    Keywords loaded from canonical registry: ``_config/topics_registry.json``
    """

    # Map Google Trends categories → registry domains
    _REGISTRY_MAP: ClassVar[dict[str, list[str]]] = {
        "technology": ["ai_technology"],
        "business": ["finance_markets", "entrepreneurship"],
        "entertainment": ["entertainment_culture"],
        "sports": ["sports"],
        "politics": ["politics", "geopolitics"],
        "science": ["science_research"],
        "health": ["health_longevity"],
    }

    CATEGORY_KEYWORDS: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls.CATEGORY_KEYWORDS:
            from .topics_registry import get_keywords_mapped
            cls.CATEGORY_KEYWORDS = get_keywords_mapped(cls._REGISTRY_MAP)

    @classmethod
    def classify(cls, query: str, headline: str = "") -> TrendCategory:
        cls._ensure_loaded()
        text = f"{query} {headline}".lower()
        scores: dict[str, int] = {}
        for cat, keywords in cls.CATEGORY_KEYWORDS.items():
            scores[cat] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda c: scores[c])
        if scores[best] > 0:
            return TrendCategory(best)
        return TrendCategory.GENERAL

    @classmethod
    def estimate_volume(cls, traffic: str) -> SearchVolume:
        """Parse traffic string like '200,000+' into a volume tier."""
        normalized = traffic.replace(",", "").replace("+", "").strip()
        try:
            num = int(normalized)
        except (ValueError, TypeError):
            return SearchVolume.LOW
        if num >= 500_000:
            return SearchVolume.MASSIVE
        if num >= 200_000:
            return SearchVolume.HIGH
        if num >= 50_000:
            return SearchVolume.MODERATE
        return SearchVolume.LOW


# ── Scraper ─────────────────────────────────────────────────────


class GoogleTrendsIntelligence:
    """Monitor Google Trends via public RSS feeds."""

    DEFAULT_GEOS: ClassVar[list[str]] = ["US", "GB", "AU", "CA", "IN"]

    def __init__(self, geos: list[str] | None = None,
                 cache_dir: Path | None = None):
        self._geos = geos or self.DEFAULT_GEOS
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "gtrends_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: float = 0.0
        self._rate_limit_s: float = 5.0

    def collect(self) -> TrendsDigest:
        """Collect trending searches from all configured geos."""
        signals: list[TrendSignal] = []

        for geo in self._geos:
            url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
            signals.extend(self._parse_feed(url, geo))

        # Deduplicate
        seen: set[str] = set()
        unique: list[TrendSignal] = []
        for sig in signals:
            if sig.fingerprint not in seen:
                seen.add(sig.fingerprint)
                unique.append(sig)

        category_counts: dict[str, int] = {}
        for sig in unique:
            category_counts[sig.category] = category_counts.get(sig.category, 0) + 1

        top_queries = [s.query for s in unique[:20]]

        digest = TrendsDigest(
            timestamp=datetime.now(UTC).isoformat(),
            signals=unique,
            category_counts=category_counts,
            top_queries=top_queries,
            geo_coverage=self._geos,
            trend_summary=f"{len(unique)} trends across {len(self._geos)} regions",
        )

        self._cache_digest(digest)
        return digest

    def _parse_feed(self, url: str, geo: str) -> list[TrendSignal]:
        """Parse Google Trends daily RSS feed."""
        signals: list[TrendSignal] = []
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={"User-Agent": "NCL-FPC/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()
                root = ElementTree.fromstring(xml_data)

                for item in root.iter("item"):
                    title_el = item.find("title")
                    traffic_el = item.find(f"{{{HT_NS}}}approx_traffic")
                    pub_date_el = item.find("pubDate")

                    query = title_el.text if title_el is not None and title_el.text else ""
                    traffic = traffic_el.text if traffic_el is not None and traffic_el.text else ""

                    # Look for associated news
                    news_title = ""
                    news_url = ""
                    news_item = item.find(f"{{{HT_NS}}}news_item")
                    if news_item is not None:
                        nt_el = news_item.find(f"{{{HT_NS}}}news_item_title")
                        nu_el = news_item.find(f"{{{HT_NS}}}news_item_url")
                        if nt_el is not None and nt_el.text:
                            news_title = nt_el.text
                        if nu_el is not None and nu_el.text:
                            news_url = nu_el.text

                    signals.append(TrendSignal(
                        trend_id=hashlib.sha256(f"{query}:{geo}".encode()).hexdigest()[:16],
                        query=query,
                        category=TrendClassifier.classify(query, news_title),
                        momentum=TrendMomentum.RISING,  # All daily trends are rising
                        volume=TrendClassifier.estimate_volume(traffic),
                        traffic_estimate=traffic,
                        news_headline=news_title,
                        news_url=news_url,
                        geo=geo,
                        published_at=pub_date_el.text if pub_date_el is not None and pub_date_el.text else "",
                    ))
        except Exception as exc:
            logger.debug("Google Trends feed %s failed: %s", geo, exc)

        return signals[:15]  # Top 15 per geo

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: TrendsDigest) -> None:
        cache_file = self._cache_dir / f"gtrends_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            cache_file.write_text(
                json.dumps({"signals": [asdict(s) for s in digest.signals],
                            "top_queries": digest.top_queries,
                            "summary": digest.trend_summary,
                            "timestamp": digest.timestamp},
                           indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to cache Google Trends digest: %s", exc)
