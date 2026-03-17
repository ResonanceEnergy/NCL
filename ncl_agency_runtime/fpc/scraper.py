"""Scheduled scraper engine — tiered data collection from MASTER_TOPICS.json.

Runs ingesters by priority tier (daily/weekly/monthly/quarterly),
caches signals to ``data/signal_cache/``, and tracks last-scrape
timestamps to avoid redundant fetches.

Master topics live in the shared NCL-TOPICS folder (C:/dev/NCL-TOPICS/).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .topic_mapper import _DEFAULT_TOPICS_PATH, TopicMapper

logger = logging.getLogger(__name__)

TIER_INTERVAL_DAYS = {
    "tier_1_daily": 1,
    "tier_2_weekly": 7,
    "tier_3_monthly": 30,
    "tier_4_quarterly": 90,
}


class TopicScraper:
    """Tiered scraper that uses MASTER_TOPICS.json to drive data collection."""

    def __init__(
        self,
        topics_path: str = _DEFAULT_TOPICS_PATH,
        config_path: str = "config/council_config.json",
        cache_dir: str = "data/signal_cache",
    ):
        self.mapper = TopicMapper(topics_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = config_path

    def scrape_tier(self, tier: str, free_only: bool = True) -> list[Any]:
        """Run all ingesters for a specific priority tier.

        Returns list of Signal objects and caches results to disk.
        """
        from .data_sources.registry import IngesterRegistry

        sources = self.mapper.sources_for_tier(tier)
        if not sources:
            logger.warning("No sources mapped for tier %s", tier)
            return []

        logger.info("Scraping tier %s — %d sources: %s", tier, len(sources), sources)
        registry = IngesterRegistry(self.config_path)
        signals = registry.run_sources(sources=sources, free_only=free_only)

        # Cache results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cache_file = self.cache_dir / f"{tier}_{timestamp}.json"

        signal_dicts = [self._signal_to_dict(s) for s in signals]
        cache_file.write_text(
            json.dumps(
                {
                    "tier": tier,
                    "sources_run": sources,
                    "signal_count": len(signals),
                    "timestamp": timestamp,
                    "signals": signal_dicts,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        logger.info("Tier %s complete — %d signals cached to %s", tier, len(signals), cache_file)
        return signals

    def scrape_due(self, free_only: bool = True) -> dict[str, Any]:
        """Check last-scrape timestamps and run tiers that are due.

        Returns a dict of tier → signal count (if scraped) or status string.
        """
        results: dict[str, Any] = {}

        for tier, interval_days in TIER_INTERVAL_DAYS.items():
            last = self._last_scrape_time(tier)
            if last is None or (datetime.now() - last).days >= interval_days:
                signals = self.scrape_tier(tier, free_only=free_only)
                results[tier] = {"scraped": True, "signal_count": len(signals)}
            else:
                days_until = interval_days - (datetime.now() - last).days
                results[tier] = {"scraped": False, "days_remaining": days_until}

        return results

    def scrape_all(self, free_only: bool = True) -> dict[str, int]:
        """Force-scrape every tier regardless of schedule.

        Returns tier → signal count.
        """
        results: dict[str, int] = {}
        for tier in TIER_INTERVAL_DAYS:
            signals = self.scrape_tier(tier, free_only=free_only)
            results[tier] = len(signals)
        return results

    def latest_signals(self, tier: str | None = None) -> list[dict]:
        """Get the most recent cached signals, optionally for a specific tier."""
        pattern = f"{tier}_*.json" if tier else "tier_*_*.json"
        files = sorted(self.cache_dir.glob(pattern))

        if not files:
            return []

        data = json.loads(files[-1].read_text(encoding="utf-8"))
        return data.get("signals", [])

    def cache_status(self) -> dict[str, Any]:
        """Show cache state: last scrape time and signal count per tier."""
        status: dict[str, Any] = {}
        for tier in TIER_INTERVAL_DAYS:
            last = self._last_scrape_time(tier)
            latest = self.latest_signals(tier)
            status[tier] = {
                "last_scraped": last.isoformat() if last else None,
                "cached_signals": len(latest),
                "interval_days": TIER_INTERVAL_DAYS[tier],
            }
        return status

    def _last_scrape_time(self, tier: str) -> datetime | None:
        """Find the most recent cache file timestamp for a tier."""
        files = sorted(self.cache_dir.glob(f"{tier}_*.json"))
        if not files:
            return None
        ts_str = files[-1].stem.replace(f"{tier}_", "")
        try:
            return datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
        except ValueError:
            return None

    @staticmethod
    def _signal_to_dict(signal: Any) -> dict:
        """Convert a Signal dataclass to JSON-serializable dict."""
        if hasattr(signal, "__dict__"):
            d = dict(signal.__dict__)
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
            return d
        return {"raw": str(signal)}
