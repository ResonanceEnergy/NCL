"""Technology, innovation & digital adoption ingesters.

APIs: USPTO Patents, arXiv, ITU Telecom, Ookla Open Data.
"""

import contextlib
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import ClassVar

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class USPTOPatentIngester(BaseIngester):
    """USPTO Patent Data — patent applications and grants. No key."""

    source_name = "uspto"
    BASE_URL = "https://developer.uspto.gov/ibd-api/v1/application/publications"

    def fetch(
        self,
        search_text: str = "artificial intelligence",
        rows: int = 50,
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            import urllib.parse
            url = (
                f"{self.BASE_URL}"
                f"?searchText={urllib.parse.quote(search_text)}"
                f"&rows={rows}&start=0"
            )
            data = self._get_json(url)
            results = data.get("results", [])
            for rec in results:
                signals.append(self._make_signal(
                    source=f"USPTO:{search_text[:15]}",
                    title=f"Patent: {rec.get('inventionTitle', '')[:100]}",
                    content=json.dumps({
                        "title": rec.get("inventionTitle"),
                        "assignee": rec.get("assigneeEntityName"),
                        "filing_date": rec.get("filingDate"),
                        "patent_number": rec.get("patentNumber"),
                        "ipc_code": rec.get("mainCPCSymbolText"),
                    }),
                    url=f"https://patents.google.com/patent/US{rec.get('patentNumber', '')}",
                    meta={
                        "title": rec.get("inventionTitle", "")[:100],
                        "assignee": rec.get("assigneeEntityName"),
                        "filing_date": rec.get("filingDate"),
                    },
                ))
        except Exception:
            logger.warning("USPTO fetch failed for '%s'", search_text)
        logger.info("USPTO: ingested %d signals", len(signals))
        return signals


class ArxivIngester(BaseIngester):
    """arXiv — 2.4M+ scientific preprints. No key."""

    source_name = "arxiv"
    BASE_URL = "https://export.arxiv.org/api/query"

    DEFAULT_QUERIES: ClassVar[list[str]] = [
        "all:artificial+intelligence+forecasting",
        "all:climate+prediction+model",
        "all:pandemic+epidemiological+model",
        "all:quantum+computing",
        "all:energy+transition+renewable",
    ]

    def fetch(
        self,
        queries: list[str] | None = None,
        max_results: int = 10,
    ) -> list[Signal]:
        queries = queries or self.DEFAULT_QUERIES
        signals: list[Signal] = []
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for query in queries:
            try:
                url = f"{self.BASE_URL}?search_query={query}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
                text = self._get_text(url)
                root = ET.fromstring(text)
                for entry in root.findall("atom:entry", ns):
                    title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
                    summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
                    link_el = entry.find("atom:link[@type='text/html']", ns)
                    if link_el is None:
                        link_el = entry.find("atom:link", ns)
                    pub_date = entry.findtext("atom:published", "", ns)
                    ts = datetime.now()
                    if pub_date:
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(pub_date[:19])

                    # Extract categories
                    categories = [c.get("term", "") for c in entry.findall("atom:category", ns)]

                    signals.append(self._make_signal(
                        source="arXiv",
                        title=f"arXiv: {title}",
                        content=summary[:2000],
                        url=link_el.get("href", "") if link_el is not None else "",
                        timestamp=ts,
                        meta={
                            "query": query,
                            "categories": categories,
                            "published": pub_date,
                        },
                    ))
            except Exception:
                logger.warning("arXiv fetch failed for query: %s", query)
        logger.info("arXiv: ingested %d signals", len(signals))
        return signals


class WikipediaPageviewsIngester(BaseIngester):
    """Wikipedia Pageviews API — attention proxy. No key."""

    source_name = "wikipedia_pageviews"
    BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

    DEFAULT_PAGES: ClassVar[list[str]] = [
        "Recession", "Inflation", "Pandemic",
        "Artificial_intelligence", "Climate_change",
        "Bitcoin", "Stock_market_crash", "World_War_III",
        "Nuclear_war", "Famine",
    ]

    def fetch(
        self,
        pages: list[str] | None = None,
        project: str = "en.wikipedia",
        granularity: str = "daily",
        days: int = 30,
    ) -> list[Signal]:
        pages = pages or self.DEFAULT_PAGES
        signals: list[Signal] = []
        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(days=days)
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        for page in pages:
            try:
                url = (
                    f"{self.BASE_URL}/{project}/all-access/all-agents"
                    f"/{page}/{granularity}/{start_str}00/{end_str}00"
                )
                data = self._get_json(url)
                for item in data.get("items", []):
                    dt_str = item.get("timestamp", "")
                    ts = datetime.now()
                    if len(dt_str) >= 8:
                        with contextlib.suppress(ValueError):
                            ts = datetime(int(dt_str[:4]), int(dt_str[4:6]), int(dt_str[6:8]))
                    signals.append(self._make_signal(
                        source=f"Wikipedia:{page}",
                        title=f"Wiki '{page}' — {ts.date()} — {item.get('views', 0)} views",
                        content=json.dumps(item),
                        timestamp=ts,
                        meta={
                            "page": page,
                            "views": item.get("views"),
                            "project": project,
                        },
                    ))
            except Exception:
                logger.warning("Wikipedia pageviews failed for %s", page)
        logger.info("Wikipedia: ingested %d signals", len(signals))
        return signals
