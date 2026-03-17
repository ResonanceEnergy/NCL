"""Dynamic topic→ingester mapping powered by MASTER_TOPICS.json.

Replaces the hardcoded ``_TOPIC_SOURCE_MAP`` with a living mapping
derived from the 347-topic, 14-domain master list.

Master topics live in the shared NCL-TOPICS folder (C:/dev/NCL-TOPICS/)
used by both FPC and NCL.  Falls back to local config/ if the shared
folder is not present.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Shared topics folder used by both FPC and NCL.
# Override with NCL_TOPICS_DIR env var if needed.
_SHARED_TOPICS_DIR = Path(
    os.environ.get("NCL_TOPICS_DIR", r"C:\dev\NCL-TOPICS")
)
_DEFAULT_TOPICS_PATH = str(
    _SHARED_TOPICS_DIR / "MASTER_TOPICS.json"
    if _SHARED_TOPICS_DIR.exists()
    else Path("config/MASTER_TOPICS.json")
)

# Domain ID → ingester names from the 53-source registry.
# This is the single authoritative link between topic domains and data sources.
DOMAIN_SOURCES: dict[str, list[str]] = {
    "01_CRYPTO_DEFI": [
        "coingecko", "coincap", "blockchain_com", "fear_greed",
        "defi_llama", "messari",
    ],
    "02_FINANCIAL_MARKETS": [
        "alpha_vantage", "fmp", "polygon", "fred", "fear_greed",
    ],
    "03_MACROECONOMICS": [
        "fred", "bls", "treasury", "world_bank", "imf",
        "eurostat", "nasdaq_data_link", "census",
    ],
    "04_ENERGY_CLEANTECH": [
        "eia", "fred", "world_bank", "open_meteo", "nasa_power",
    ],
    "05_AI_ML_AGENTS": [
        "arxiv", "github_dev", "google_trends", "newsapi",
        "wikipedia_pageviews",
    ],
    "06_GEOPOLITICS_CONFLICT": [
        "gdelt", "acled", "un_comtrade", "unhcr", "iom_dtm",
    ],
    "07_CLIMATE_EARTH_SCIENCE": [
        "noaa_climate", "open_meteo", "openweathermap", "noaa_co2",
        "nasa_power", "global_forest_watch", "openaq",
    ],
    "08_HEALTH_BIOELECTRICITY": [
        "who_gho", "global_health", "cdc", "healthmap",
    ],
    "09_SOUND_MUSIC_PRODUCTION": [
        "google_trends", "wikipedia_pageviews", "newsapi",
    ],
    "10_ALTERNATIVE_HISTORY": [
        "arxiv", "google_trends", "wikipedia_pageviews",
    ],
    "11_GAMING_INTERACTIVE": [
        "google_trends", "wikipedia_pageviews", "newsapi", "reddit",
    ],
    "12_MEDIA_MARKETING_CONTENT": [
        "google_trends", "reddit", "newsapi", "wikipedia_pageviews",
    ],
    "13_ENGINEERING_HARDWARE": [
        "uspto", "arxiv", "google_trends",
    ],
    "14_GOVERNANCE_OPERATIONS": [
        "github_dev", "google_trends",
    ],
}


class TopicMapper:
    """Map free-text topics to relevant data ingesters using MASTER_TOPICS.json."""

    def __init__(self, topics_path: str = _DEFAULT_TOPICS_PATH):
        self.topics_data = self._load(topics_path)
        self._keyword_index: dict[str, set[str]] = self._build_keyword_index()

    @staticmethod
    def _load(path: str) -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("MASTER_TOPICS.json not found at %s — using empty map", path)
            return {}

    def _build_keyword_index(self) -> dict[str, set[str]]:
        """Build word → {domain_ids} index from all topics."""
        index: dict[str, set[str]] = {}
        for domain_id, domain in self.topics_data.get("domains", {}).items():
            words: set[str] = set()
            for topic in domain.get("primary_topics", []) + domain.get("related_topics", []):
                for word in topic.lower().split():
                    cleaned = word.strip(",.;:!?()[]\"'")
                    if len(cleaned) >= 3:
                        words.add(cleaned)
            for word in words:
                index.setdefault(word, set()).add(domain_id)
        return index

    def sources_for_topic(self, topic: str) -> list[str]:
        """Given free-text topic, return sorted list of relevant ingester names."""
        words = topic.lower().split()
        domain_scores: dict[str, int] = {}

        for word in words:
            cleaned = word.strip(",.;:!?()[]\"'")
            if len(cleaned) < 3:
                continue
            for keyword, domains in self._keyword_index.items():
                if keyword in cleaned or cleaned in keyword:
                    for domain_id in domains:
                        domain_scores[domain_id] = domain_scores.get(domain_id, 0) + 1

        if not domain_scores:
            return sorted({"fred", "world_bank", "fear_greed", "newsapi", "google_trends"})

        sources: set[str] = set()
        for domain_id in domain_scores:
            for src in DOMAIN_SOURCES.get(domain_id, []):
                sources.add(src)
        return sorted(sources)

    def sources_for_tier(self, tier: str) -> list[str]:
        """Get ingester names for a scraper priority tier."""
        tiers = self.topics_data.get("scraper_priority_tiers", {})
        tier_data = tiers.get(tier, {})
        domains = tier_data.get("topic_domains", [])

        sources: set[str] = set()
        for domain_id in domains:
            for src in DOMAIN_SOURCES.get(domain_id, []):
                sources.add(src)
        return sorted(sources)

    def tier_schedule(self) -> dict[str, dict]:
        """Return tier → {domains, sources, key_feeds} for all tiers."""
        tiers = self.topics_data.get("scraper_priority_tiers", {})
        result: dict[str, dict] = {}
        for tier_name, tier_data in tiers.items():
            if tier_name == "description":
                continue
            result[tier_name] = {
                "domains": tier_data.get("topic_domains", []),
                "sources": self.sources_for_tier(tier_name),
                "key_feeds": tier_data.get("key_feeds", []),
            }
        return result

    def all_domains(self) -> list[str]:
        """Return all domain IDs."""
        return sorted(self.topics_data.get("domains", {}).keys())
