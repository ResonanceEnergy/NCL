"""Dashboard bridge for memory search and visualization."""

import asyncio
import logging
from typing import Optional

from ..config import flags
from .store import MemoryStore


log = logging.getLogger("ncl.memory.dashboard")

# Maximum time (seconds) allowed for any single bridge call
_BRIDGE_TIMEOUT = 30.0


# ── SQLite units-index fast path (W5-07) ─────────────────────────────────
#
# NOTE: ``get_stats()`` and ``get_timeline()`` both still need the FULL
# ``_load_all_units()`` snapshot (they compute aggregate stats / per-unit
# events over every record), so the SQLite fast path doesn't fit them —
# only the filtered ``search()`` call below benefits. When the flag is
# off or the SQLite query fails for any reason, we fall back to the
# canonical search_units path — flag-off behavior is bit-identical to
# before this retrofit.
async def _maybe_indexed_search(memory_store, **kwargs):
    """Drop-in replacement for ``memory_store.search_units(**kwargs)``."""
    if flags.units_index_sqlite():
        try:
            unit_ids = await memory_store._search_units_via_sqlite_index(**kwargs)
            if unit_ids:
                units_by_id = await memory_store._load_units_batch(set(unit_ids))
                return [units_by_id[uid] for uid in unit_ids if uid in units_by_id]
        except Exception as e:
            log.debug("sqlite index search failed (%s) — falling back", e)
    return await memory_store.search_units(**kwargs)


class MemoryDashboardBridge:
    """Bridges MemoryStore to dashboard queries and visualization."""

    def __init__(self, memory_store: MemoryStore) -> None:
        """
        Initialize the dashboard bridge.

        Args:
            memory_store: MemoryStore instance
        """
        self.store = memory_store

    async def get_stats(self) -> dict:
        """
        Get comprehensive memory statistics for dashboard display.

        Returns:
            Dict containing: total_units, avg_importance, decay_factor,
            units_by_source (dict), top_tags (list), importance_distribution (dict)
        """
        try:
            units = await asyncio.wait_for(self.store._load_all_units(), timeout=_BRIDGE_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("get_stats: _load_all_units timed out after %.0fs", _BRIDGE_TIMEOUT)
            units = []
        except Exception as e:
            log.error("get_stats: failed to load units: %s", e)
            units = []

        if not units:
            return {
                "total_units": 0,
                "avg_importance": 0.0,
                "decay_factor": 0.95,
                "units_by_source": {},
                "top_tags": [],
                "importance_distribution": {
                    "0-20": 0,
                    "20-40": 0,
                    "40-60": 0,
                    "60-80": 0,
                    "80-100": 0,
                },
            }

        # Calculate statistics
        avg_importance = sum(u.importance for u in units) / len(units)

        # Count by source
        units_by_source = {}
        for unit in units:
            units_by_source[unit.source] = units_by_source.get(unit.source, 0) + 1

        # Count tags
        tag_counts = {}
        for unit in units:
            for tag in unit.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Sort tags by frequency and get top 10
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_tags = [{"tag": tag, "count": count} for tag, count in top_tags]

        # Importance distribution
        importance_dist = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
        for unit in units:
            importance = self.store._apply_decay(unit)
            if importance < 20:
                importance_dist["0-20"] += 1
            elif importance < 40:
                importance_dist["20-40"] += 1
            elif importance < 60:
                importance_dist["40-60"] += 1
            elif importance < 80:
                importance_dist["60-80"] += 1
            else:
                importance_dist["80-100"] += 1

        return {
            "total_units": len(units),
            "avg_importance": round(avg_importance, 2),
            "decay_factor": 0.95,
            "units_by_source": units_by_source,
            "top_tags": top_tags,
            "importance_distribution": importance_dist,
        }

    async def get_timeline(self, limit: int = 50) -> dict:
        """
        Get timeline of recent memory events (creation, access, decay).

        Args:
            limit: Maximum events to return

        Returns:
            ``{"events": [...], "degraded": bool}``. ``degraded=True`` when
            the underlying ``_load_all_units`` call timed out and we fell
            back to the last in-memory snapshot (still useful for iOS —
            shows something instead of an empty page). Wave-13 P1-B.
        """
        degraded = False
        try:
            units = await asyncio.wait_for(self.store._load_all_units(), timeout=_BRIDGE_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning(
                "get_timeline: _load_all_units timed out after %.0fs — "
                "serving last known snapshot (degraded)",
                _BRIDGE_TIMEOUT,
            )
            # P1-B graceful degrade: return the most recent cached snapshot
            # rather than an empty list. Under Awarebot warm-start flood
            # the writer queue can park readers past the timeout, but the
            # last-known snapshot is still serviceable for the iOS UI.
            snapshot = self.store._last_known_snapshot()
            if snapshot is None:
                return {"events": [], "degraded": True}
            units = snapshot
            degraded = True
        except Exception as e:
            log.error("get_timeline: failed to load units: %s", e)
            return {"events": [], "degraded": True}

        events = []
        for unit in units:
            # Creation event — carries full unit payload so iOS detail
            # view doesn't need a second round-trip. 2026-05-24: was
            # stripped to {timestamp, type, unit_id, source, importance}
            # which left iOS MemoryDetailView showing an empty CONTENT
            # card; the unit's actual content was on disk but the wire
            # format didn't carry it. Adding content + created_at + tags
            # + entities + memory_type + memory_tier + reinforcement_count
            # so the detail view can render without an extra fetch.
            events.append(
                {
                    "timestamp": unit.created_at.isoformat(),
                    "type": "created",
                    "unit_id": unit.unit_id,
                    "source": unit.source,
                    "importance": unit.importance,
                    "content": unit.content,
                    "created_at": unit.created_at.isoformat(),
                    "tags": list(unit.tags or []),
                    "entities": list(unit.entities or []),
                    "memory_type": getattr(unit.memory_type, "value", unit.memory_type) if unit.memory_type is not None else None,
                    "memory_tier": getattr(unit.memory_tier, "value", unit.memory_tier) if unit.memory_tier is not None else None,
                    "reinforcement_count": unit.reinforcement_count,
                }
            )

            # Last access event (if accessed)
            if unit.reinforcement_count > 0:
                events.append(
                    {
                        "timestamp": unit.last_accessed.isoformat(),
                        "type": "accessed",
                        "unit_id": unit.unit_id,
                        "reinforcement_count": unit.reinforcement_count,
                    }
                )

            # Decay warning (if importance below threshold)
            decayed = self.store._apply_decay(unit)
            if decayed < 20 and unit.importance >= 20:
                events.append(
                    {
                        "timestamp": unit.last_accessed.isoformat(),
                        "type": "decay_warning",
                        "unit_id": unit.unit_id,
                        "original_importance": unit.importance,
                        "decayed_importance": round(decayed, 2),
                    }
                )

        # Sort by timestamp descending (newest first)
        events.sort(key=lambda e: e["timestamp"], reverse=True)

        return events[:limit]

    async def search(
        self,
        query_text: Optional[str] = None,
        tags: Optional[list[str]] = None,
        importance_threshold: float = 0.0,
        days_back: int = 30,
    ) -> list[dict]:
        """
        Search memory units with combined filters.

        Performs text search on content (substring matching) combined with
        tag, importance, and date filters.

        Args:
            query_text: Substring to search in content
            tags: Tag filters (AND logic)
            importance_threshold: Minimum importance score
            days_back: Only include units from past N days

        Returns:
            List of matching units as dicts with truncated content
        """
        try:
            results = await asyncio.wait_for(
                _maybe_indexed_search(
                    self.store,
                    tags=tags,
                    importance_threshold=importance_threshold,
                    days_back=days_back,
                ),
                timeout=_BRIDGE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning("search: search_units timed out after %.0fs", _BRIDGE_TIMEOUT)
            return []
        except Exception as e:
            log.error("search: search_units failed: %s", e)
            return []

        # Apply text search filter if provided
        if query_text:
            query_lower = query_text.lower()
            results = [u for u in results if query_lower in u.content.lower()]

        # Convert to dashboard format
        return [
            {
                "unit_id": u.unit_id,
                "content": (u.content[:200] + "..." if len(u.content) > 200 else u.content),
                "source": u.source,
                "importance": round(self.store._apply_decay(u), 2),
                "tags": u.tags,
                "created_at": u.created_at.isoformat(),
                "reinforcement_count": u.reinforcement_count,
            }
            for u in results
        ]
