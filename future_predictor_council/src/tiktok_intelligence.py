"""TikTok Intelligence Engine — Public Discovery Feed Signals.

Monitors TikTok's public discovery endpoints for trending hashtags,
sounds, and viral content signals. Uses TikTok's public RSS/embed
endpoints — no API key or authentication required.

Note: TikTok has limited public feed access compared to other platforms.
This engine focuses on trending hashtag/tag pages and public embed data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)

_FPC_ROOT = Path(__file__).resolve().parent.parent


# ── Enums ───────────────────────────────────────────────────────


class TikTokDomain(StrEnum):
    AI_TECH = "ai_tech"
    FINANCE = "finance"
    EDUCATION = "education"
    CULTURE_TRENDS = "culture_trends"
    CREATOR_ECONOMY = "creator_economy"
    HEALTH_WELLNESS = "health_wellness"
    POLITICS = "politics"
    SCIENCE = "science"
    ENTERTAINMENT = "entertainment"
    GENERAL = "general"


class ViralVelocity(StrEnum):
    SEEDING = "seeding"      # Just starting to spread
    GROWING = "growing"      # Building momentum
    VIRAL = "viral"          # Exponential spread
    PLATEAUED = "plateaued"  # Peak reached


class ContentFormat(StrEnum):
    SHORT_VIDEO = "short_video"
    DUET = "duet"
    STITCH = "stitch"
    LIVE = "live"
    SERIES = "series"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class TikTokSignal:
    """A single TikTok trend/content signal."""

    signal_id: str
    hashtag: str
    domain: TikTokDomain
    velocity: ViralVelocity
    description: str = ""
    estimated_views: str = ""
    related_tags: list[str] = field(default_factory=list)
    content_format: ContentFormat = ContentFormat.SHORT_VIDEO
    collected_at: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"tiktok:{self.hashtag}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.collected_at:
            self.collected_at = datetime.now(UTC).isoformat()


@dataclass
class TikTokDigest:
    """Aggregated TikTok intelligence digest."""

    timestamp: str
    signals: list[TikTokSignal] = field(default_factory=list)
    domain_counts: dict[str, int] = field(default_factory=dict)
    top_hashtags: list[str] = field(default_factory=list)
    trend_summary: str = ""


# ── Classifier ──────────────────────────────────────────────────


class TikTokClassifier:
    """Classify TikTok hashtags and signals by domain.

    Keywords loaded from canonical registry: ``_config/topics_registry.json``
    """

    _REGISTRY_MAP: ClassVar[dict[str, list[str]]] = {
        "ai_tech": ["ai_technology"],
        "finance": ["finance_markets", "blockchain_web3"],
        "education": ["education_learning"],
        "culture_trends": ["entertainment_culture", "lifestyle"],
        "creator_economy": ["personal_brand", "creative_media"],
        "health_wellness": ["health_longevity"],
        "politics": ["politics", "geopolitics"],
        "science": ["science_research"],
    }

    DOMAIN_KEYWORDS: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls.DOMAIN_KEYWORDS:
            from .topics_registry import get_keywords_mapped
            cls.DOMAIN_KEYWORDS = get_keywords_mapped(cls._REGISTRY_MAP)

    @classmethod
    def classify(cls, hashtag: str, description: str = "") -> TikTokDomain:
        cls._ensure_loaded()
        text = f"{hashtag} {description}".lower()
        scores: dict[str, int] = {}
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda d: scores[d])
        if scores[best] > 0:
            return TikTokDomain(best)
        return TikTokDomain.GENERAL


# ── Collector ───────────────────────────────────────────────────


class TikTokIntelligence:
    """Collect TikTok trend signals from public endpoints.

    TikTok's public API is limited. This engine monitors:
    1. Curated trending hashtags (known high-signal tags)
    2. Public tag page metadata for view counts
    3. Cross-references with other platform trends
    """

    # Curated high-signal hashtags to track
    TRACKED_HASHTAGS: ClassVar[list[str]] = [
        "ai", "chatgpt", "tech", "coding", "artificialintelligence",
        "crypto", "investing", "entrepreneur", "startup",
        "science", "space", "climate", "energy",
        "fyp", "trending", "viral", "edutok", "booktok",
        "creator", "contentcreator", "digitalmarketing",
        "fitness", "mentalhealth", "mindset",
        "politics", "news", "worldnews",
    ]

    def __init__(self, hashtags: list[str] | None = None,
                 cache_dir: Path | None = None):
        self._hashtags = hashtags or self.TRACKED_HASHTAGS
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "tiktok_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: float = 0.0
        self._rate_limit_s: float = 10.0  # Conservative rate limit

    def collect(self) -> TikTokDigest:
        """Collect trend signals from tracked TikTok hashtags."""
        signals: list[TikTokSignal] = []

        for tag in self._hashtags:
            signal = self._probe_hashtag(tag)
            if signal is not None:
                signals.append(signal)

        # Deduplicate
        seen: set[str] = set()
        unique: list[TikTokSignal] = []
        for sig in signals:
            if sig.fingerprint not in seen:
                seen.add(sig.fingerprint)
                unique.append(sig)

        domain_counts: dict[str, int] = {}
        for sig in unique:
            domain_counts[sig.domain] = domain_counts.get(sig.domain, 0) + 1

        digest = TikTokDigest(
            timestamp=datetime.now(UTC).isoformat(),
            signals=unique,
            domain_counts=domain_counts,
            top_hashtags=[s.hashtag for s in unique[:15]],
            trend_summary=f"{len(unique)} TikTok hashtag signals collected",
        )

        self._cache_digest(digest)
        return digest

    def _probe_hashtag(self, hashtag: str) -> TikTokSignal | None:
        """Probe a TikTok hashtag tag page for metadata.

        Attempts to fetch the public tag page and extract view count
        from the HTML meta tags (og:description often contains view info).
        """
        url = f"https://www.tiktok.com/tag/{hashtag}"
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; NCL-FPC/1.0)",
                    "Accept": "text/html",
                })
            with urllib.request.urlopen(req, timeout=15) as resp:
                # Only read first 20KB to find meta tags
                html = resp.read(20_480).decode("utf-8", errors="replace")

                # Extract view count from og:description or page content
                views = self._extract_view_count(html)
                description = self._extract_meta_description(html)

                return TikTokSignal(
                    signal_id=hashlib.sha256(f"tt:{hashtag}".encode()).hexdigest()[:16],
                    hashtag=hashtag,
                    domain=TikTokClassifier.classify(hashtag, description),
                    velocity=ViralVelocity.GROWING,
                    description=description[:200] if description else f"#{hashtag}",
                    estimated_views=views,
                )
        except Exception as exc:
            logger.debug("TikTok hashtag #%s probe failed: %s", hashtag, exc)
            # Still create a signal from the curated list
            return TikTokSignal(
                signal_id=hashlib.sha256(f"tt:{hashtag}".encode()).hexdigest()[:16],
                hashtag=hashtag,
                domain=TikTokClassifier.classify(hashtag),
                velocity=ViralVelocity.SEEDING,
                description=f"#{hashtag} (probe failed)",
            )

    @staticmethod
    def _extract_view_count(html: str) -> str:
        """Extract view count from TikTok meta tags."""
        match = re.search(r'(\d[\d,.]*[KMBkmb]?)\s*(?:views|video)', html)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def _extract_meta_description(html: str) -> str:
        """Extract og:description or meta description from HTML."""
        match = re.search(
            r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]*)"',
            html, re.IGNORECASE)
        if match:
            return match.group(1)
        return ""

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: TikTokDigest) -> None:
        cache_file = self._cache_dir / f"tiktok_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            cache_file.write_text(
                json.dumps({"signals": [asdict(s) for s in digest.signals],
                            "top_hashtags": digest.top_hashtags,
                            "summary": digest.trend_summary,
                            "timestamp": digest.timestamp},
                           indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to cache TikTok digest: %s", exc)
