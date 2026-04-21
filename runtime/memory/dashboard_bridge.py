"""Dashboard bridge for memory search and visualization."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from .store import MemoryStore


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
        units = await self.store._load_all_units()

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

    async def get_timeline(self, limit: int = 50) -> list[dict]:
        """
        Get timeline of recent memory events (creation, access, decay).

        Args:
            limit: Maximum events to return

        Returns:
            List of timeline events sorted by time (newest first)
        """
        units = await self.store._load_all_units()

        events = []
        for unit in units:
            # Creation event
            events.append(
                {
                    "timestamp": unit.created_at.isoformat(),
                    "type": "created",
                    "unit_id": unit.unit_id,
                    "source": unit.source,
                    "importance": unit.importance,
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
        # Use store's search for tag/importance/date filtering
        results = await self.store.search_units(
            tags=tags, importance_threshold=importance_threshold, days_back=days_back
        )

        # Apply text search filter if provided
        if query_text:
            query_lower = query_text.lower()
            results = [u for u in results if query_lower in u.content.lower()]

        # Convert to dashboard format
        return [
            {
                "unit_id": u.unit_id,
                "content": (
                    u.content[:200] + "..." if len(u.content) > 200 else u.content
                ),
                "source": u.source,
                "importance": round(self.store._apply_decay(u), 2),
                "tags": u.tags,
                "created_at": u.created_at.isoformat(),
                "reinforcement_count": u.reinforcement_count,
            }
            for u in results
        ]
