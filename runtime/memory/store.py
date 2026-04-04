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
        unit = MemUnit(
            unit_id=str(uuid.uuid4()),
            content=content,
            source=source,
            importance=min(100.0, max(0.0, importance)),
            tags=tags or [],
        )
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

    async def consolidate(self) -> None:
        """
        Merge related memory units periodically.

        This is a background consolidation task that runs periodically
        to combine similar memories and improve recall efficiency.
        """
        units = await self._load_all_units()
        # Placeholder for intelligent consolidation logic
        # In production, this would cluster related units and merge them
        pass

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
