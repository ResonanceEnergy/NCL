"""Canonical topics registry loader.

Single source of truth for ALL topic/keyword classification across
NCL and FPC intelligence engines.  Every intelligence engine imports
from here instead of maintaining its own keyword dicts.

Registry file: ``_config/topics_registry.json``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "_config" / "topics_registry.json"

_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        _cache = json.load(f)
    return _cache


def get_domain_keywords() -> dict[str, list[str]]:
    """Return ``{domain_name: [keyword, ...]}`` for classifiers."""
    registry = _load()
    return {
        name: info["keywords"]
        for name, info in registry["domains"].items()
        if info.get("keywords")
    }


def get_keywords_mapped(mapping: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return keywords remapped to engine-specific category names.

    ``mapping`` is ``{engine_category: [registry_domain, ...]}``.
    Keywords from all listed registry domains are merged into each
    engine category.
    """
    all_kw = get_domain_keywords()
    result: dict[str, list[str]] = {}
    for cat, domains in mapping.items():
        merged: list[str] = []
        for d in domains:
            merged.extend(all_kw.get(d, []))
        # deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for kw in merged:
            if kw not in seen:
                seen.add(kw)
                deduped.append(kw)
        result[cat] = deduped
    return result


def get_subreddits() -> list[str]:
    """Return the canonical list of monitored subreddits."""
    registry = _load()
    return registry["platform_sources"]["reddit"]["default_subreddits"]


def get_substack_publications() -> dict[str, str]:
    """Return ``{slug: display_name}`` for Substack monitoring."""
    registry = _load()
    return registry["platform_sources"]["substack"]["default_publications"]


def get_github_watched_repos() -> list[str]:
    """Return the canonical list of watched GitHub repos."""
    registry = _load()
    return registry["platform_sources"]["github"]["watched_repos"]


def get_github_topic_pages() -> list[str]:
    """Return GitHub topic page URLs."""
    registry = _load()
    return registry["platform_sources"]["github"]["topic_pages"]


def get_rss_feeds() -> list[str]:
    """Return RSS feed URLs."""
    registry = _load()
    return registry["platform_sources"]["rss_feeds"]


def get_fred_indicators() -> list[str]:
    """Return FRED economic indicator series IDs."""
    registry = _load()
    return registry["platform_sources"]["fred_indicators"]


def reload() -> None:
    """Force reload the registry from disk (e.g. after hot-edit)."""
    global _cache
    _cache = None
    _load()
