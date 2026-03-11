"""Data ingestion — RSS feeds, generic API fetcher, and CSV loader."""

import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """A single ingested data signal."""
    source: str
    title: str
    content: str
    url: str
    timestamp: datetime
    meta: Dict = field(default_factory=dict)


class RSSIngester:
    """Fetch and parse RSS/Atom feeds into Signal objects."""

    def fetch(self, feed_url: str, max_items: int = 20) -> List[Signal]:
        signals: List[Signal] = []
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "FPC/0.3"})
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — trusted feed URLs only
                tree = ET.parse(resp)
        except Exception:
            logger.warning("Failed to fetch RSS feed: %s", feed_url)
            return signals

        root = tree.getroot()
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            signals.append(
                Signal(
                    source=feed_url,
                    title=item.findtext("title", ""),
                    content=item.findtext("description", ""),
                    url=item.findtext("link", ""),
                    timestamp=datetime.now(),
                )
            )

        # Atom
        for entry in root.findall(".//atom:entry", ns)[:max_items]:
            link_el = entry.find("atom:link", ns)
            signals.append(
                Signal(
                    source=feed_url,
                    title=entry.findtext("atom:title", "", ns),
                    content=entry.findtext("atom:summary", "", ns),
                    url=link_el.get("href", "") if link_el is not None else "",
                    timestamp=datetime.now(),
                )
            )

        logger.info("Ingested %d signals from %s", len(signals), feed_url)
        return signals


class APIIngester:
    """Fetch JSON from a generic REST endpoint."""

    def fetch(self, url: str, headers: Optional[Dict[str, str]] = None) -> List[Signal]:
        hdrs = {"User-Agent": "FPC/0.3", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
        except Exception:
            logger.warning("Failed to fetch API: %s", url)
            return []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            return []

        return [
            Signal(
                source=url,
                title=str(item.get("title", item.get("name", "")))[:200],
                content=json.dumps(item)[:2000],
                url=url,
                timestamp=datetime.now(),
                meta={"raw_keys": list(item.keys()) if isinstance(item, dict) else []},
            )
            for item in items[:50]
        ]


class CSVIngester:
    """Load a local CSV into Signal objects (one row = one signal)."""

    def fetch(self, path: str, title_col: str = "title", content_col: str = "content") -> List[Signal]:
        import csv

        signals: List[Signal] = []
        csv_path = Path(path)
        if not csv_path.exists():
            logger.warning("CSV not found: %s", path)
            return signals

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                signals.append(
                    Signal(
                        source=str(csv_path),
                        title=row.get(title_col, "")[:200],
                        content=row.get(content_col, json.dumps(row))[:2000],
                        url="",
                        timestamp=datetime.now(),
                    )
                )
        logger.info("Ingested %d rows from %s", len(signals), path)
        return signals


class IngestionPipeline:
    """Orchestrate multiple ingesters against configured sources."""

    def __init__(self, config_path: str = "config/council_config.json"):
        self.rss = RSSIngester()
        self.api = APIIngester()
        self.csv = CSVIngester()
        self._load_sources(config_path)

    def _load_sources(self, config_path: str):
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            cfg = {}
        self.rss_feeds: List[str] = cfg.get("rss_feeds", [])
        self.api_endpoints: List[Dict] = cfg.get("api_endpoints", [])

    def run(self) -> List[Signal]:
        """Run all configured ingesters and return combined signals."""
        signals: List[Signal] = []
        for feed in self.rss_feeds:
            signals.extend(self.rss.fetch(feed))
        for ep in self.api_endpoints:
            signals.extend(self.api.fetch(ep["url"], ep.get("headers")))
        logger.info("Total signals ingested: %d", len(signals))
        return signals
