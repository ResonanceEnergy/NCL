"""Instagram Intelligence Engine — Public Profile & Hashtag Signals.

Monitors Instagram's public endpoints for trending hashtags, creator
activity, and content signals. Uses Instagram's public web interface
and embed endpoints — no API key required.

Note: Instagram's public access is more restricted than other platforms.
This engine focuses on publicly accessible profile pages and hashtag
explore metadata.
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


class InstagramDomain(StrEnum):
    AI_TECH = "ai_tech"
    BUSINESS = "business"
    CREATOR_ECONOMY = "creator_economy"
    LIFESTYLE = "lifestyle"
    EDUCATION = "education"
    FINANCE = "finance"
    HEALTH_FITNESS = "health_fitness"
    ART_DESIGN = "art_design"
    NEWS_POLITICS = "news_politics"
    GENERAL = "general"


class ContentSignalType(StrEnum):
    HASHTAG_TREND = "hashtag_trend"
    CREATOR_ACTIVITY = "creator_activity"
    REEL_TREND = "reel_trend"
    CAROUSEL_TREND = "carousel_trend"
    STORY_MENTION = "story_mention"


class EngagementTier(StrEnum):
    MICRO = "micro"        # < 10K followers/engagement
    RISING = "rising"      # 10K-100K
    ESTABLISHED = "established"  # 100K-1M
    MEGA = "mega"          # 1M+


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class InstagramSignal:
    """A single Instagram content/hashtag signal."""

    signal_id: str
    source: str  # hashtag or profile handle
    signal_type: ContentSignalType
    domain: InstagramDomain
    engagement_tier: EngagementTier
    description: str = ""
    post_count: str = ""
    related_tags: list[str] = field(default_factory=list)
    collected_at: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"ig:{self.source}:{self.signal_type}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.collected_at:
            self.collected_at = datetime.now(UTC).isoformat()


@dataclass
class InstagramDigest:
    """Aggregated Instagram intelligence digest."""

    timestamp: str
    signals: list[InstagramSignal] = field(default_factory=list)
    domain_counts: dict[str, int] = field(default_factory=dict)
    top_hashtags: list[str] = field(default_factory=list)
    trend_summary: str = ""


# ── Classifier ──────────────────────────────────────────────────


class InstagramClassifier:
    """Classify Instagram hashtags and signals by domain.

    Keywords loaded from canonical registry: ``_config/topics_registry.json``
    """

    _REGISTRY_MAP: ClassVar[dict[str, list[str]]] = {
        "ai_tech": ["ai_technology"],
        "business": ["finance_markets", "entrepreneurship"],
        "creator_economy": ["personal_brand", "creative_media"],
        "lifestyle": ["lifestyle"],
        "education": ["education_learning"],
        "finance": ["finance_markets", "blockchain_web3"],
        "health_fitness": ["health_longevity"],
        "art_design": ["creative_media"],
        "news_politics": ["politics", "geopolitics"],
    }

    DOMAIN_KEYWORDS: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls.DOMAIN_KEYWORDS:
            from .topics_registry import get_keywords_mapped
            cls.DOMAIN_KEYWORDS = get_keywords_mapped(cls._REGISTRY_MAP)

    @classmethod
    def classify(cls, source: str, description: str = "") -> InstagramDomain:
        cls._ensure_loaded()
        text = f"{source} {description}".lower()
        scores: dict[str, int] = {}
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda d: scores[d])
        if scores[best] > 0:
            return InstagramDomain(best)
        return InstagramDomain.GENERAL


# ── Collector ───────────────────────────────────────────────────


class InstagramIntelligence:
    """Collect Instagram trend signals from public endpoints.

    Instagram's public API is restricted. This engine monitors:
    1. Curated high-signal hashtags via explore page metadata
    2. Public creator profile activity
    3. Cross-references with other platform trends
    """

    TRACKED_HASHTAGS: ClassVar[list[str]] = [
        "artificialintelligence", "machinelearning", "tech", "coding",
        "startup", "entrepreneur", "business", "marketing",
        "creator", "contentcreator", "reels", "viral",
        "finance", "investing", "crypto",
        "science", "space", "climate",
        "fitness", "wellness", "mindset",
        "art", "design", "photography",
        "news", "worldnews",
    ]

    TRACKED_PROFILES: ClassVar[list[str]] = [
        "openai", "google", "meta", "nvidia",
        "techcrunch", "waboronline", "elonmusk_",
    ]

    def __init__(self, hashtags: list[str] | None = None,
                 profiles: list[str] | None = None,
                 cache_dir: Path | None = None):
        self._hashtags = hashtags or self.TRACKED_HASHTAGS
        self._profiles = profiles or self.TRACKED_PROFILES
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "instagram_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: float = 0.0
        self._rate_limit_s: float = 12.0  # Extra conservative

    def collect(self) -> InstagramDigest:
        """Collect trend signals from tracked Instagram hashtags and profiles."""
        signals: list[InstagramSignal] = []

        # Hashtag signals
        for tag in self._hashtags:
            signal = self._probe_hashtag(tag)
            if signal is not None:
                signals.append(signal)

        # Profile signals
        for profile in self._profiles:
            signal = self._probe_profile(profile)
            if signal is not None:
                signals.append(signal)

        # Deduplicate
        seen: set[str] = set()
        unique: list[InstagramSignal] = []
        for sig in signals:
            if sig.fingerprint not in seen:
                seen.add(sig.fingerprint)
                unique.append(sig)

        domain_counts: dict[str, int] = {}
        for sig in unique:
            domain_counts[sig.domain] = domain_counts.get(sig.domain, 0) + 1

        digest = InstagramDigest(
            timestamp=datetime.now(UTC).isoformat(),
            signals=unique,
            domain_counts=domain_counts,
            top_hashtags=[s.source for s in unique
                          if s.signal_type == ContentSignalType.HASHTAG_TREND][:15],
            trend_summary=f"{len(unique)} Instagram signals collected",
        )

        self._cache_digest(digest)
        return digest

    def _probe_hashtag(self, hashtag: str) -> InstagramSignal | None:
        """Probe Instagram hashtag explore page for metadata."""
        url = f"https://www.instagram.com/explore/tags/{hashtag}/"
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; NCL-FPC/1.0)",
                    "Accept": "text/html",
                })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read(20_480).decode("utf-8", errors="replace")

                post_count = self._extract_post_count(html)
                description = self._extract_meta_description(html)

                return InstagramSignal(
                    signal_id=hashlib.sha256(f"ig:tag:{hashtag}".encode()).hexdigest()[:16],
                    source=f"#{hashtag}",
                    signal_type=ContentSignalType.HASHTAG_TREND,
                    domain=InstagramClassifier.classify(hashtag, description),
                    engagement_tier=EngagementTier.RISING,
                    description=description[:200] if description else f"#{hashtag}",
                    post_count=post_count,
                )
        except Exception as exc:
            logger.debug("Instagram hashtag #%s probe failed: %s", hashtag, exc)
            return InstagramSignal(
                signal_id=hashlib.sha256(f"ig:tag:{hashtag}".encode()).hexdigest()[:16],
                source=f"#{hashtag}",
                signal_type=ContentSignalType.HASHTAG_TREND,
                domain=InstagramClassifier.classify(hashtag),
                engagement_tier=EngagementTier.MICRO,
                description=f"#{hashtag} (probe failed)",
            )

    def _probe_profile(self, profile: str) -> InstagramSignal | None:
        """Probe a public Instagram profile for activity signals."""
        url = f"https://www.instagram.com/{profile}/"
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; NCL-FPC/1.0)",
                    "Accept": "text/html",
                })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read(20_480).decode("utf-8", errors="replace")

                description = self._extract_meta_description(html)
                follower_count = self._extract_follower_count(html)

                return InstagramSignal(
                    signal_id=hashlib.sha256(f"ig:prof:{profile}".encode()).hexdigest()[:16],
                    source=f"@{profile}",
                    signal_type=ContentSignalType.CREATOR_ACTIVITY,
                    domain=InstagramClassifier.classify(profile, description),
                    engagement_tier=self._tier_from_followers(follower_count),
                    description=description[:200] if description else f"@{profile}",
                )
        except Exception as exc:
            logger.debug("Instagram profile @%s probe failed: %s", profile, exc)
            return None

    @staticmethod
    def _extract_post_count(html: str) -> str:
        match = re.search(r'(\d[\d,.]*[KMBkmb]?)\s*(?:posts|Posts)', html)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_follower_count(html: str) -> str:
        match = re.search(r'(\d[\d,.]*[KMBkmb]?)\s*(?:followers|Followers)', html)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_meta_description(html: str) -> str:
        match = re.search(
            r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]*)"',
            html, re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _tier_from_followers(count_str: str) -> EngagementTier:
        """Map follower count string to engagement tier."""
        if not count_str:
            return EngagementTier.MICRO
        normalized = count_str.replace(",", "").strip().upper()
        try:
            if normalized.endswith("M") or normalized.endswith("B"):
                return EngagementTier.MEGA
            if normalized.endswith("K"):
                num = float(normalized[:-1])
                if num >= 100:
                    return EngagementTier.ESTABLISHED
                if num >= 10:
                    return EngagementTier.RISING
                return EngagementTier.MICRO
            num = float(normalized)
            if num >= 1_000_000:
                return EngagementTier.MEGA
            if num >= 100_000:
                return EngagementTier.ESTABLISHED
            if num >= 10_000:
                return EngagementTier.RISING
        except ValueError:
            pass
        return EngagementTier.MICRO

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: InstagramDigest) -> None:
        cache_file = self._cache_dir / f"instagram_{datetime.now(UTC).strftime('%Y%m%d')}.json"
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
            logger.warning("Failed to cache Instagram digest: %s", exc)
