"""Substack Intelligence Engine — Newsletter RSS Ingestion Pipeline.

Ingests Substack newsletter feeds via their public RSS endpoints,
classifies content by domain, and routes intelligence signals for
trend prediction and strategic analysis.

No API key required — all Substack newsletters expose RSS at
``https://<publication>.substack.com/feed``.
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

_FPC_ROOT = Path(__file__).resolve().parent.parent


# ── Enums ───────────────────────────────────────────────────────


class SubstackDomain(StrEnum):
    AI_TECHNOLOGY = "ai_technology"
    FINANCE = "finance"
    GEOPOLITICS = "geopolitics"
    SCIENCE = "science"
    ENTREPRENEURSHIP = "entrepreneurship"
    CULTURE = "culture"
    HEALTH = "health"
    ENERGY = "energy"
    SECURITY = "security"
    GENERAL = "general"


class ContentType(StrEnum):
    NEWSLETTER = "newsletter"
    PODCAST_TRANSCRIPT = "podcast_transcript"
    THREAD = "thread"
    PAID = "paid"
    FREE = "free"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class SubstackArticle:
    """A single Substack newsletter article."""

    article_id: str
    publication: str
    title: str
    summary: str
    domain: SubstackDomain
    url: str = ""
    author: str = ""
    published_at: str = ""
    content_type: ContentType = ContentType.FREE
    tags: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.publication}:{self.title[:80]}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.published_at:
            self.published_at = datetime.now(UTC).isoformat()


@dataclass
class SubstackDigest:
    """Aggregated Substack intelligence digest."""

    timestamp: str
    articles: list[SubstackArticle] = field(default_factory=list)
    domain_counts: dict[str, int] = field(default_factory=dict)
    publication_counts: dict[str, int] = field(default_factory=dict)
    trend_summary: str = ""


# ── Classifier ──────────────────────────────────────────────────


class SubstackClassifier:
    """Classify newsletter content by domain.

    Keywords loaded from canonical registry: ``_config/topics_registry.json``
    """

    _REGISTRY_MAP: ClassVar[dict[str, list[str]]] = {
        "ai_technology": ["ai_technology"],
        "finance": ["finance_markets", "blockchain_web3"],
        "geopolitics": ["geopolitics"],
        "science": ["science_research"],
        "entrepreneurship": ["entrepreneurship"],
        "energy": ["energy_climate"],
        "health": ["health_longevity"],
        "security": ["security_intelligence"],
    }

    DOMAIN_KEYWORDS: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls.DOMAIN_KEYWORDS:
            from .topics_registry import get_keywords_mapped
            cls.DOMAIN_KEYWORDS = get_keywords_mapped(cls._REGISTRY_MAP)

    @classmethod
    def classify(cls, title: str, summary: str) -> SubstackDomain:
        cls._ensure_loaded()
        text = f"{title} {summary}".lower()
        scores: dict[str, int] = {}
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda d: scores[d])
        if scores[best] > 0:
            return SubstackDomain(best)
        return SubstackDomain.GENERAL


# ── Scraper ─────────────────────────────────────────────────────


class SubstackIntelligence:
    """Ingest Substack newsletters via public RSS feeds."""

    # Curated list of high-signal newsletters
    DEFAULT_PUBLICATIONS: ClassVar[dict[str, str]] = {
        "natesnewsletter": "Nate B Jones",
        "platformer": "Platformer (Casey Newton)",
        "thealgorithmicbridge": "The Algorithmic Bridge",
        "importai": "Import AI (Jack Clark)",
        "chinai": "ChinAI Newsletter",
        "astralcodexten": "Astral Codex Ten",
        "thegeneralist": "The Generalist",
        "stratechery": "Stratechery",
        "notboring": "Not Boring (Packy McCormick)",
        "exponentialview": "Exponential View",
    }

    def __init__(self, publications: dict[str, str] | None = None,
                 cache_dir: Path | None = None):
        self._publications = publications or self.DEFAULT_PUBLICATIONS
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "substack_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: float = 0.0
        self._rate_limit_s: float = 5.0

    def collect(self) -> SubstackDigest:
        """Collect intelligence from all configured Substack publications."""
        articles: list[SubstackArticle] = []

        for slug, pub_name in self._publications.items():
            feed_url = f"https://{slug}.substack.com/feed"
            articles.extend(self._parse_feed(feed_url, pub_name, slug))

        # Deduplicate
        seen: set[str] = set()
        unique: list[SubstackArticle] = []
        for art in articles:
            if art.fingerprint not in seen:
                seen.add(art.fingerprint)
                unique.append(art)

        domain_counts: dict[str, int] = {}
        pub_counts: dict[str, int] = {}
        for art in unique:
            domain_counts[art.domain] = domain_counts.get(art.domain, 0) + 1
            pub_counts[art.publication] = pub_counts.get(art.publication, 0) + 1

        digest = SubstackDigest(
            timestamp=datetime.now(UTC).isoformat(),
            articles=unique,
            domain_counts=domain_counts,
            publication_counts=pub_counts,
            trend_summary=f"{len(unique)} articles from {len(pub_counts)} publications",
        )

        self._cache_digest(digest)
        return digest

    def _parse_feed(self, url: str, pub_name: str, slug: str) -> list[SubstackArticle]:
        """Parse a single Substack RSS feed."""
        articles: list[SubstackArticle] = []
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={"User-Agent": "NCL-FPC/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()
                root = ElementTree.fromstring(xml_data)

                for item in root.iter("item"):
                    title_el = item.find("title")
                    link_el = item.find("link")
                    desc_el = item.find("description")
                    pub_date_el = item.find("pubDate")
                    creator_el = item.find("{http://purl.org/dc/elements/1.1/}creator")

                    title = title_el.text if title_el is not None and title_el.text else ""
                    summary = desc_el.text[:500] if desc_el is not None and desc_el.text else ""
                    link = link_el.text if link_el is not None and link_el.text else ""

                    articles.append(SubstackArticle(
                        article_id=hashlib.sha256(link.encode()).hexdigest()[:16],
                        publication=pub_name,
                        title=title,
                        summary=summary,
                        domain=SubstackClassifier.classify(title, summary),
                        url=link,
                        author=creator_el.text if creator_el is not None and creator_el.text else pub_name,
                        published_at=pub_date_el.text if pub_date_el is not None and pub_date_el.text else "",
                    ))
        except Exception as exc:
            logger.debug("Substack feed %s failed: %s", slug, exc)

        return articles[:10]  # Latest 10 per publication

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: SubstackDigest) -> None:
        cache_file = self._cache_dir / f"substack_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            cache_file.write_text(
                json.dumps({"articles": [asdict(a) for a in digest.articles],
                            "summary": digest.trend_summary,
                            "timestamp": digest.timestamp},
                           indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to cache Substack digest: %s", exc)
