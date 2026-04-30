"""Memory system for NCL brain."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import uuid

import aiofiles
from pydantic import ValidationError

log = logging.getLogger("ncl.memory")

from ..ncl_brain.models import MemUnit

# Memory system constraints
MAX_CONTENT_LENGTH = 50_000  # Max characters per memory unit
MAX_TOTAL_UNITS = 10_000    # Max total memory units in store


class MemoryStore:
    """
    Three-phase memory lifecycle: episodic traces → semantic MemUnits → reconstructive recollection.

    Manages persistence, decay, reinforcement, and search.
    """

    def __init__(self, data_dir: str | Path) -> None:
        """
        Initialize memory store.

        Args:
            data_dir: Directory for memory storage (~/NCL/data/memory/)
        """
        self.data_dir = Path(data_dir).expanduser() / "memory"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.data_dir / "units.jsonl"

    async def create_unit(
        self,
        content: str,
        source: str,
        importance: float = 50.0,
        tags: Optional[list[str]] = None,
    ) -> MemUnit:
        """
        Create and persist a new memory unit.

        Args:
            content: Memory content
            source: Source of the memory
            importance: Initial importance score (0-100)
            tags: Search tags

        Returns:
            Created MemUnit
        """
        # Validate and truncate content if necessary
        truncated_content = content
        if len(content) > MAX_CONTENT_LENGTH:
            truncated_content = content[:MAX_CONTENT_LENGTH] + "[TRUNCATED]"
            log.warning(
                f"Memory unit content truncated from {len(content)} to {MAX_CONTENT_LENGTH} chars"
            )

        unit = MemUnit(
            unit_id=str(uuid.uuid4()),
            content=truncated_content,
            source=source,
            importance=min(100.0, max(0.0, importance)),
            tags=tags or [],
        )

        # Check total unit count and evict if necessary
        await self._ensure_capacity()

        await self._persist_unit(unit)
        return unit

    async def get_unit(self, unit_id: str) -> Optional[MemUnit]:
        """
        Retrieve a memory unit and update access time.

        Args:
            unit_id: Unit ID to retrieve

        Returns:
            MemUnit or None if not found
        """
        unit = await self._load_unit(unit_id)
        if unit:
            # Reinforce: boost importance and update access time
            unit.last_accessed = datetime.now(timezone.utc)
            unit.reinforcement_count += 1
            unit.importance = min(100.0, unit.importance * 1.2)
            await self._persist_unit(unit)
        return unit

    async def search_units(
        self,
        tags: Optional[list[str]] = None,
        importance_threshold: float = 0.0,
        days_back: Optional[int] = None,
    ) -> list[MemUnit]:
        """
        Search memory units by tags, importance, and date range.

        Args:
            tags: Tag filter (AND logic)
            importance_threshold: Minimum importance score
            days_back: Only include units from past N days

        Returns:
            List of matching MemUnits, sorted by importance descending
        """
        units = await self._load_all_units()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back) if days_back else None

        results = []
        for unit in units:
            # Apply importance decay
            unit.importance = self._apply_decay(unit)

            # Filter by cutoff date
            if cutoff and unit.created_at < cutoff:
                continue

            # Filter by importance
            if unit.importance < importance_threshold:
                continue

            # Filter by tags (AND logic: all provided tags must match)
            if tags and not all(tag in unit.tags for tag in tags):
                continue

            results.append(unit)

        # Sort by importance descending
        results.sort(key=lambda u: u.importance, reverse=True)
        return results

    async def consolidate(self) -> dict:
        """
        Merge related memory units and prune decayed ones.

        Follows MWP memory-processing conventions:
        1. Apply decay to all units
        2. Prune units below importance threshold
        3. Cluster related units by tag overlap + content similarity
        4. Merge clusters into consolidated semantic units

        Returns:
            Consolidation stats dict
        """
        units = await self._load_all_units()
        if not units:
            return {"total": 0, "pruned": 0, "merged": 0}

        pruned = 0
        merged = 0
        importance_threshold = 5.0  # Below this, units are pruned

        # Phase 1: Apply decay and separate prunable from active
        active_units = []
        for unit in units:
            decayed_importance = self._apply_decay(unit)
            unit.importance = decayed_importance
            if decayed_importance < importance_threshold:
                pruned += 1
            else:
                active_units.append(unit)

        # Phase 2: Cluster related units by tag overlap
        # Build adjacency by shared tags (2+ shared tags = related)
        clusters: list[list[MemUnit]] = []
        clustered: set[str] = set()

        for i, unit_a in enumerate(active_units):
            if unit_a.unit_id in clustered:
                continue
            cluster = [unit_a]
            clustered.add(unit_a.unit_id)

            tags_a = set(unit_a.tags)
            if not tags_a:
                continue

            for j, unit_b in enumerate(active_units[i + 1:], i + 1):
                if unit_b.unit_id in clustered:
                    continue
                tags_b = set(unit_b.tags)
                # Require 2+ shared tags for clustering
                shared = tags_a & tags_b
                if len(shared) >= 2:
                    # Also check content similarity (word overlap)
                    words_a = set(unit_a.content.lower().split())
                    words_b = set(unit_b.content.lower().split())
                    if len(words_a) > 0 and len(words_b) > 0:
                        similarity = len(words_a & words_b) / min(len(words_a), len(words_b))
                        if similarity >= 0.3:  # 30% word overlap
                            cluster.append(unit_b)
                            clustered.add(unit_b.unit_id)

            if len(cluster) >= 2:
                clusters.append(cluster)

        # Phase 3: Merge clusters into consolidated units
        consolidated_units = []
        merged_ids: set[str] = set()

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            # Merge: combine content, union tags, max importance, sum reinforcements
            combined_content = " | ".join(
                u.content[:200] for u in sorted(cluster, key=lambda x: x.importance, reverse=True)
            )
            all_tags = list(set(tag for u in cluster for tag in u.tags))
            max_importance = max(u.importance for u in cluster)
            total_reinforcements = sum(u.reinforcement_count for u in cluster)

            # Create consolidated unit
            consolidated = MemUnit(
                unit_id=cluster[0].unit_id,  # Keep oldest ID
                content=f"[CONSOLIDATED from {len(cluster)} units] {combined_content}"[:2000],
                source=f"consolidation:{','.join(u.source for u in cluster[:3])}",
                importance=min(100.0, max_importance * 1.1),  # Slight boost for consolidation
                tags=all_tags[:20],
                reinforcement_count=total_reinforcements,
            )
            consolidated_units.append(consolidated)
            merged_ids.update(u.unit_id for u in cluster)
            merged += len(cluster) - 1  # N units merged into 1 = N-1 merges

        # Phase 4: Rebuild the memory file with active + consolidated units
        surviving = [u for u in active_units if u.unit_id not in merged_ids]
        surviving.extend(consolidated_units)

        if pruned > 0 or merged > 0:
            # Rewrite memory file atomically
            tmp_file = self.memory_file.with_suffix(".tmp")
            async with aiofiles.open(tmp_file, "w") as f:
                for unit in surviving:
                    await f.write(unit.model_dump_json() + "\n")
            tmp_file.rename(self.memory_file)

            log.info(
                f"Memory consolidation: {len(units)} → {len(surviving)} units "
                f"(pruned={pruned}, merged={merged})"
            )

        # Stamp last consolidation timestamp for stats()
        try:
            self._last_consolidation = datetime.now(timezone.utc)
        except Exception:
            pass

        return {
            "total_before": len(units),
            "total_after": len(surviving),
            "pruned": pruned,
            "merged": merged,
            "clusters": len(clusters),
        }

    async def stats(self) -> dict:
        """
        Return memory store statistics: unit count, average importance,
        last consolidation time, file size.

        Used by /memory/stats endpoint and dashboard Overview tab.
        """
        units: list[MemUnit] = []
        try:
            units = await self._load_all_units()
        except Exception as e:
            log.warning(f"stats(): failed to load units: {e}")

        unit_count = len(units)
        if unit_count > 0:
            try:
                avg_importance = sum(u.importance for u in units) / unit_count
            except Exception:
                avg_importance = 0.0
            try:
                avg_reinforcements = sum(u.reinforcement_count for u in units) / unit_count
            except Exception:
                avg_reinforcements = 0.0
            try:
                latest_access = max(u.last_accessed for u in units).isoformat()
            except Exception:
                latest_access = None
        else:
            avg_importance = 0.0
            avg_reinforcements = 0.0
            latest_access = None

        last_consolidation = getattr(self, "_last_consolidation", None)
        if isinstance(last_consolidation, datetime):
            last_consolidation = last_consolidation.isoformat()

        file_size = 0
        try:
            if self.memory_file.exists():
                file_size = self.memory_file.stat().st_size
        except Exception:
            pass

        return {
            "unit_count": unit_count,
            "avg_importance": round(avg_importance, 2),
            "avg_reinforcements": round(avg_reinforcements, 2),
            "last_consolidation": last_consolidation,
            "last_access": latest_access,
            "memory_file_bytes": file_size,
            "max_total_units": MAX_TOTAL_UNITS,
        }

    def _apply_decay(self, unit: MemUnit) -> float:
        """
        Apply exponential decay to importance based on time since last access.

        Formula: importance *= decay_rate^(days_since_access)

        Args:
            unit: MemUnit to decay

        Returns:
            Decayed importance score
        """
        days_since = (datetime.now(timezone.utc) - unit.last_accessed).days
        decayed = unit.importance * (unit.decay_rate ** days_since)
        return max(0.0, min(100.0, decayed))

    async def _ensure_capacity(self) -> None:
        """
        Ensure memory store stays within capacity limits.

        If total units exceed MAX_TOTAL_UNITS, evict oldest low-importance units
        (importance < 30, sorted by creation date ascending).
        """
        units = await self._load_all_units()

        if len(units) >= MAX_TOTAL_UNITS:
            # Find units eligible for eviction: importance < 30
            evictable = [u for u in units if u.importance < 30]
            if not evictable:
                # If no low-importance units, evict oldest overall
                evictable = sorted(units, key=lambda u: u.created_at)

            # Sort by creation date (oldest first) and evict
            evictable.sort(key=lambda u: u.created_at)
            to_evict = evictable[:max(1, len(units) - MAX_TOTAL_UNITS + 1)]

            # Get IDs of units to keep
            evict_ids = {u.unit_id for u in to_evict}
            kept_units = [u for u in units if u.unit_id not in evict_ids]

            log.info(
                f"Memory store at capacity ({len(units)} units). "
                f"Evicting {len(to_evict)} low-importance units."
            )

            # Rewrite the memory file with only kept units
            await self._rewrite_units(kept_units)

    async def _rewrite_units(self, units: list[MemUnit]) -> None:
        """
        Rewrite the entire memory file with the given units.

        Args:
            units: List of MemUnits to persist
        """
        try:
            async with aiofiles.open(self.memory_file, "w") as f:
                for unit in units:
                    await f.write(unit.model_dump_json() + "\n")
            log.debug(f"Memory file rewritten with {len(units)} units")
        except Exception as e:
            log.error(f"Failed to rewrite memory file: {e}")

    async def _persist_unit(self, unit: MemUnit) -> None:
        """
        Persist a memory unit to NDJSON file.

        Args:
            unit: MemUnit to persist
        """
        async with aiofiles.open(self.memory_file, "a") as f:
            await f.write(unit.model_dump_json() + "\n")

    async def _load_unit(self, unit_id: str) -> Optional[MemUnit]:
        """
        Load a single memory unit by ID.

        Args:
            unit_id: Unit ID to load

        Returns:
            MemUnit or None if not found
        """
        try:
            async with aiofiles.open(self.memory_file, "r") as f:
                async for line in f:
                    if not line.strip():
                        continue
                    try:
                        unit = MemUnit(**json.loads(line))
                        if unit.unit_id == unit_id:
                            return unit
                    except (json.JSONDecodeError, ValidationError) as e:
                        log.warning(f"Failed to parse memory unit: {e}")
                        continue
        except FileNotFoundError:
            log.warning(f"Memory file not found: {self.memory_file}")
        return None

    async def _load_all_units(self) -> list[MemUnit]:
        """
        Load all memory units from NDJSON file.

        Returns:
            List of all MemUnits
        """
        units = []
        if not self.memory_file.exists():
            return units

        async with aiofiles.open(self.memory_file, "r") as f:
            async for line in f:
                if not line.strip():
                    continue
                try:
                    unit = MemUnit(**json.loads(line))
                    units.append(unit)
                except (json.JSONDecodeError, ValidationError) as e:
                    log.warning(f"Failed to parse memory unit: {e}")
                    continue
        return units

    async def get_stats(self) -> dict:
        """
        Get memory system statistics for MATRIX MONITOR.

        Returns:
            Dict with memory stats
        """
        units = await self._load_all_units()
        now = datetime.now(timezone.utc)
        today_units = [u for u in units if (now - u.created_at).days < 1]

        # Avoid zero-division: ensure units list is not empty before calculating average
        avg_importance = sum(u.importance for u in units) / len(units) if units else 0.0

        return {
            "total_units": len(units),
            "episodic_traces": len([u for u in units if u.reinforcement_count == 0]),
            "semantic_units": len([u for u in units if u.reinforcement_count > 0]),
            "decay_factor": 0.95,
            "retrievals_today": sum(1 for u in today_units if u.reinforcement_count > 0),
            "avg_importance": avg_importance,
        }

    async def close(self) -> None:
        """Cleanup (no-op for file-based store, placeholder for future DB)."""
        pass
