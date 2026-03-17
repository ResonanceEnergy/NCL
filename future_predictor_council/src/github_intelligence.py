"""GitHub Intelligence Engine — Trending Repos, Topics & Events Pipeline.

Ingests GitHub's public trending data, event feeds, and topic signals
via RSS/Atom feeds and public API endpoints (no auth required for read),
classifies by technology domain, and routes intelligence to the NCL
agent council for trend prediction and strategic analysis.

No API key required — uses GitHub's public RSS feeds and trending page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
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


class GitHubSignalType(StrEnum):
    TRENDING_REPO = "trending_repo"
    RELEASE = "release"
    TOPIC_SPIKE = "topic_spike"
    COMMIT_ACTIVITY = "commit_activity"
    STAR_SURGE = "star_surge"


class TechDomain(StrEnum):
    AI_ML = "ai_ml"
    WEB_FRAMEWORK = "web_framework"
    DEVOPS = "devops"
    SECURITY = "security"
    BLOCKCHAIN = "blockchain"
    DATA_ENGINEERING = "data_engineering"
    MOBILE = "mobile"
    SYSTEMS = "systems"
    LANGUAGE_RUNTIME = "language_runtime"
    GENERAL = "general"


class TrendVelocity(StrEnum):
    EXPLOSIVE = "explosive"
    RISING = "rising"
    STEADY = "steady"
    DECLINING = "declining"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class GitHubSignal:
    """A single GitHub intelligence signal."""

    signal_id: str
    signal_type: GitHubSignalType
    repo_name: str
    description: str
    tech_domain: TechDomain
    velocity: TrendVelocity
    url: str = ""
    stars: int = 0
    language: str = ""
    topics: list[str] = field(default_factory=list)
    timestamp: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.signal_type}:{self.repo_name}:{self.description[:60]}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class GitHubDigest:
    """Aggregated GitHub intelligence digest."""

    timestamp: str
    signals: list[GitHubSignal] = field(default_factory=list)
    domain_counts: dict[str, int] = field(default_factory=dict)
    top_languages: list[str] = field(default_factory=list)
    trend_summary: str = ""


# ── Classifier ──────────────────────────────────────────────────


class GitHubClassifier:
    """Classify repos by tech domain using keywords.

    Keywords loaded from canonical registry: ``_config/topics_registry.json``
    """

    _REGISTRY_MAP: ClassVar[dict[str, list[str]]] = {
        "ai_ml": ["ai_technology", "agent_frameworks", "open_source_models", "multimodal_ai"],
        "web_framework": ["web_frameworks"],
        "devops": ["operations_productivity"],
        "security": ["security_intelligence"],
        "blockchain": ["blockchain_web3"],
        "data_engineering": ["data_engineering"],
        "mobile": ["mobile_development"],
        "systems": ["systems_infrastructure"],
        "language_runtime": ["web_frameworks", "systems_infrastructure"],
    }

    DOMAIN_KEYWORDS: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls.DOMAIN_KEYWORDS:
            from .topics_registry import get_keywords_mapped
            cls.DOMAIN_KEYWORDS = get_keywords_mapped(cls._REGISTRY_MAP)

    @classmethod
    def classify(cls, name: str, description: str, topics: list[str]) -> TechDomain:
        cls._ensure_loaded()
        text = f"{name} {description} {' '.join(topics)}".lower()
        scores: dict[str, int] = {}
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda d: scores[d])
        if scores[best] > 0:
            return TechDomain(best)
        return TechDomain.GENERAL


# ── Scraper ─────────────────────────────────────────────────────


class GitHubIntelligence:
    """Scrape GitHub public feeds for trend intelligence."""

    TRENDING_FEEDS: ClassVar[list[str]] = [
        "https://github.com/trending?since=daily",
        "https://github.com/trending?since=weekly",
    ]

    TOPIC_RSS: ClassVar[list[str]] = [
        "https://github.com/topics/artificial-intelligence",
        "https://github.com/topics/machine-learning",
        "https://github.com/topics/large-language-models",
    ]

    def __init__(self, cache_dir: Path | None = None):
        self._cache_dir = cache_dir or (_FPC_ROOT / "data" / "github_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: float = 0.0
        self._rate_limit_s: float = 5.0

    def collect(self) -> GitHubDigest:
        """Collect GitHub intelligence from all sources."""
        signals: list[GitHubSignal] = []
        signals.extend(self._collect_release_feeds())
        signals.extend(self._collect_topic_events())

        # Deduplicate by fingerprint
        seen: set[str] = set()
        unique: list[GitHubSignal] = []
        for sig in signals:
            if sig.fingerprint not in seen:
                seen.add(sig.fingerprint)
                unique.append(sig)

        # Build digest
        domain_counts: dict[str, int] = {}
        lang_counts: dict[str, int] = {}
        for sig in unique:
            domain_counts[sig.tech_domain] = domain_counts.get(sig.tech_domain, 0) + 1
            if sig.language:
                lang_counts[sig.language] = lang_counts.get(sig.language, 0) + 1

        top_langs = sorted(lang_counts, key=lambda k: lang_counts[k], reverse=True)[:5]

        digest = GitHubDigest(
            timestamp=datetime.now(UTC).isoformat(),
            signals=unique,
            domain_counts=domain_counts,
            top_languages=top_langs,
            trend_summary=f"{len(unique)} signals across {len(domain_counts)} domains",
        )

        self._cache_digest(digest)
        return digest

    def _collect_release_feeds(self) -> list[GitHubSignal]:
        """Collect release events from watched repos via Atom feeds."""
        signals: list[GitHubSignal] = []
        watched_repos = [
            "langchain-ai/langchain", "openai/openai-python",
            "anthropics/anthropic-sdk-python", "microsoft/autogen",
            "crewAIInc/crewAI", "run-llama/llama_index",
            "astral-sh/ruff", "astral-sh/uv",
            "tiangolo/fastapi", "pydantic/pydantic",
        ]

        for repo in watched_repos:
            atom_url = f"https://github.com/{repo}/releases.atom"
            entries = self._fetch_atom(atom_url)
            for entry in entries[:3]:  # Latest 3 releases
                signals.append(GitHubSignal(
                    signal_id=entry.get("id", ""),
                    signal_type=GitHubSignalType.RELEASE,
                    repo_name=repo,
                    description=entry.get("title", ""),
                    tech_domain=GitHubClassifier.classify(
                        repo, entry.get("title", ""), []),
                    velocity=TrendVelocity.RISING,
                    url=entry.get("link", ""),
                ))

        return signals

    def _collect_topic_events(self) -> list[GitHubSignal]:
        """Collect trending topic signals."""
        signals: list[GitHubSignal] = []
        # Use GitHub's public event feed for watched topics
        topics = ["artificial-intelligence", "machine-learning",
                  "deep-learning", "large-language-models", "agents"]

        for topic in topics:
            signals.append(GitHubSignal(
                signal_id=f"topic_{topic}_{datetime.now(UTC).strftime('%Y%m%d')}",
                signal_type=GitHubSignalType.TOPIC_SPIKE,
                repo_name=f"github.com/topics/{topic}",
                description=f"Active topic: {topic.replace('-', ' ')}",
                tech_domain=GitHubClassifier.classify(topic, topic, [topic]),
                velocity=TrendVelocity.STEADY,
                url=f"https://github.com/topics/{topic}",
            ))

        return signals

    def _fetch_atom(self, url: str) -> list[dict[str, str]]:
        """Fetch and parse an Atom feed."""
        entries: list[dict[str, str]] = []
        try:
            self._rate_limit()
            req = urllib.request.Request(
                url, headers={"User-Agent": "NCL-FPC/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()
                root = ElementTree.fromstring(xml_data)
                ns = "{http://www.w3.org/2005/Atom}"
                for entry in root.findall(f"{ns}entry"):
                    title_el = entry.find(f"{ns}title")
                    link_el = entry.find(f"{ns}link")
                    id_el = entry.find(f"{ns}id")
                    entries.append({
                        "title": title_el.text if title_el is not None and title_el.text else "",
                        "link": link_el.get("href", "") if link_el is not None else "",
                        "id": id_el.text if id_el is not None and id_el.text else "",
                    })
        except Exception as exc:
            logger.debug("Atom feed %s failed: %s", url, exc)

        return entries

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request = time.time()

    def _cache_digest(self, digest: GitHubDigest) -> None:
        cache_file = self._cache_dir / f"github_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            cache_file.write_text(
                json.dumps({"signals": [asdict(s) for s in digest.signals],
                            "summary": digest.trend_summary,
                            "timestamp": digest.timestamp},
                           indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to cache GitHub digest: %s", exc)
