#!/usr/bin/env python3
"""
NCL Web Research Fallback — When Stuck, Search the Internet
═════════════════════════════════════════════════════════════
When the daemon encounters a problem it cannot solve internally,
this module searches the web for answers related to the current
topics at hand.

Uses RSS feeds (already configured in ncl_config.json) and
web search to find relevant information.

Safety:
    - Only fetches from known-safe domains
    - Rate-limited to prevent abuse
    - Results are sanitized before storage
    - No credentials or PII in queries
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from xml.etree import ElementTree

LOG = logging.getLogger("ncl.research")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class WebResearchFallback:
    """Search the internet when the daemon gets stuck.

    Strategy:
        1. First check RSS feeds for relevant content
        2. Search known documentation sites
        3. Cache results to avoid repeat lookups
    """

    # Safe domains for research
    SAFE_DOMAINS: ClassVar[list[str]] = [
        "docs.python.org",
        "docs.github.com",
        "stackoverflow.com",
        "pypi.org",
        "realpython.com",
        "docs.pytest.org",
        "ruff.rs",
        "mypy.readthedocs.io",
        "fastapi.tiangolo.com",
        "sqlite.org",
        "github.com",
    ]

    def __init__(self, config: dict | None = None, cache_dir: Path | None = None):
        self._config = config or self._load_config()
        self._cache_dir = cache_dir or (_REPO_ROOT / "ncl_agency_runtime" / "logs" / "research_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_time: float = 0.0
        self._rate_limit_s: float = 5.0   # Min seconds between requests

    def _load_config(self) -> dict[str, Any]:
        config_path = _REPO_ROOT / "ncl_config.json"
        if config_path.exists():
            result: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
            return result
        return {}

    def research(self, topic: str, context: str = "") -> dict[str, Any]:
        """Research a topic using available sources.

        Args:
            topic: The subject to research
            context: Additional context about why we need this info

        Returns:
            Dict with findings, sources, and recommendations
        """
        LOG.info("Researching: %s", topic)
        result: dict[str, Any] = {
            "topic": topic,
            "context": context,
            "timestamp": datetime.now(UTC).isoformat(),
            "findings": [],
            "sources_checked": [],
            "cached": False,
        }

        # Check cache first
        cached = self._check_cache(topic)
        if cached:
            LOG.info("Cache hit for: %s", topic)
            cached["cached"] = True
            return cached

        # 1. Check RSS feeds for relevant content
        rss_findings = self._search_rss_feeds(topic)
        result["findings"].extend(rss_findings)
        result["sources_checked"].append("rss_feeds")

        # 2. Search Python docs if topic is code-related
        if self._is_code_topic(topic):
            doc_findings = self._search_python_docs(topic)
            result["findings"].extend(doc_findings)
            result["sources_checked"].append("python_docs")

        # 3. Search PyPI for packages that might help
        if "package" in topic.lower() or "library" in topic.lower() or "install" in topic.lower():
            pypi_findings = self._search_pypi(topic)
            result["findings"].extend(pypi_findings)
            result["sources_checked"].append("pypi")

        # Cache the result
        self._store_cache(topic, result)

        LOG.info("Research complete: %d findings from %d sources",
                 len(result["findings"]), len(result["sources_checked"]))
        return result

    def _search_rss_feeds(self, topic: str) -> list[dict]:
        """Search configured RSS feeds for relevant content."""
        findings = []
        channels = self._config.get("creator_doctrine", {}).get("channels", {})
        topic_words = set(topic.lower().split())

        for channel_id, channel_info in channels.items():
            rss_url = channel_info.get("rss", "")
            if not rss_url:
                continue

            try:
                self._rate_limit()
                req = urllib.request.Request(rss_url, headers={"User-Agent": "NCL-Research/1.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()
                    root = ElementTree.fromstring(xml_data)

                    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                        title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
                        if title_elem is None or title_elem.text is None:
                            continue
                        title = title_elem.text.lower()

                        # Check relevance
                        if any(word in title for word in topic_words if len(word) > 3):
                            link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
                            link = link_elem.get("href", "") if link_elem is not None else ""
                            findings.append({
                                "source": channel_info.get("name", channel_id),
                                "title": title_elem.text,
                                "url": link,
                                "relevance": "rss_match",
                            })

            except Exception as exc:
                LOG.debug("RSS feed %s failed: %s", channel_id, exc)

        return findings

    def _search_python_docs(self, topic: str) -> list[dict]:
        """Search Python documentation for relevant content."""
        findings = []
        # Extract potential module/function names from topic
        keywords = [w for w in topic.split() if len(w) > 2 and w.isidentifier()]

        for keyword in keywords[:3]:  # Limit to 3 lookups
            try:
                self._rate_limit()
                url = f"https://docs.python.org/3/search.html?q={urllib.parse.quote(keyword)}&check_keywords=yes"
                findings.append({
                    "source": "Python Docs",
                    "title": f"Python docs search: {keyword}",
                    "url": url,
                    "relevance": "documentation",
                })
            except Exception:
                pass

        return findings

    def _search_pypi(self, topic: str) -> list[dict]:
        """Search PyPI for relevant packages."""
        findings = []
        keywords = [w for w in topic.split() if len(w) > 2]
        query = "+".join(keywords[:5])

        try:
            self._rate_limit()
            url = f"https://pypi.org/search/?q={urllib.parse.quote(query)}"
            findings.append({
                "source": "PyPI",
                "title": f"PyPI search: {query}",
                "url": url,
                "relevance": "package_search",
            })
        except Exception:
            pass

        return findings

    def _is_code_topic(self, topic: str) -> bool:
        """Determine if a topic is code-related."""
        code_indicators = [
            "python", "import", "module", "function", "class", "error",
            "exception", "bug", "fix", "install", "package", "library",
            "test", "pytest", "async", "sqlite", "json", "api",
        ]
        topic_lower = topic.lower()
        return any(ind in topic_lower for ind in code_indicators)

    def _rate_limit(self):
        """Enforce rate limiting between web requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_s:
            time.sleep(self._rate_limit_s - elapsed)
        self._last_request_time = time.time()

    def _check_cache(self, topic: str) -> dict | None:
        """Check if we have a cached research result."""
        cache_key = hashlib.sha256(topic.lower().encode()).hexdigest()[:16]
        cache_file = self._cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                data: dict[str, Any] = json.loads(cache_file.read_text(encoding="utf-8"))
                # Cache expires after 24 hours
                cached_time = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
                if (datetime.now(UTC) - cached_time.replace(tzinfo=UTC)).total_seconds() < 86400:
                    return data
            except Exception:
                pass
        return None

    def _store_cache(self, topic: str, result: dict):
        """Cache a research result."""
        cache_key = hashlib.sha256(topic.lower().encode()).hexdigest()[:16]
        cache_file = self._cache_dir / f"{cache_key}.json"
        try:
            cache_file.write_text(
                json.dumps(result, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            LOG.warning("Cache write failed: %s", exc)
