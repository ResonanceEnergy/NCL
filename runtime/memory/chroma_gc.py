"""
ChromaDB garbage collection for the NCL MemoryStore.

ChromaDB upserts happen via `MemoryStore.index_unit()` whenever a unit is
created, but until now there has been no inverse — when a unit was pruned,
merged away, evicted, or compacted out of `units.jsonl`, its embedding stayed
in the vector store forever. Production observed ~29,138 vectors backing
~9,836 live units (3x ghost ratio).

This module is a STANDALONE garbage collector. It walks every ChromaDB
collection the MemoryStore manages (6 typed + 1 legacy default), diffs the
stored IDs against the live unit IDs in `units.jsonl`, and:

  * find_ghost_ids()   -> {collection: [ghost_id, ...]}
  * purge_ghosts()     -> deletes ghosts (chunked, bounded)
  * reindex_missing()  -> upserts live units missing from any collection
  * stats()            -> {collection: {live, ghost, missing}}

Plus a `_chroma_gc_loop()` standalone async function the scheduler can wrap.

Design constraints:
- Do not touch scheduler.py — that integration is a separate spec.
- Do not touch LaunchAgent plists.
- Wrap every ChromaDB call in try/except — never crash on a single failure.
- Never delete > 1000 IDs in one call (chunked).
- Atomic JSONL append for the audit log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.memory.chroma_gc")

# Bounded batch size — ChromaDB delete() can handle a lot, but we keep it
# tight to avoid blocking the event loop and to make each batch atomic-ish.
MAX_DELETE_BATCH = 1000

# Loop cadence (seconds) and ghost threshold to trigger purges.
GC_LOOP_INTERVAL = 3600  # 1 hour
GHOST_PURGE_THRESHOLD = 50  # only purge collections with > 50 ghosts


class ChromaGC:
    """
    Garbage collector for MemoryStore's ChromaDB collections.

    Uses the live `memory_store._chroma_collections` dict so we share the
    exact same client/handles the store uses — no separate connection,
    no schema drift.
    """

    def __init__(self, memory_store) -> None:
        self.store = memory_store

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _collections(self) -> dict:
        """
        Get the {name -> Collection} dict from the store, initializing
        ChromaDB if it hasn't been touched yet.

        Returns {} if ChromaDB is unavailable.
        """
        # Trigger lazy init on the store side. _init_vector_db() is sync.
        try:
            self.store._init_vector_db()
        except Exception as e:
            log.warning(f"_init_vector_db failed: {e}")
            return {}
        return getattr(self.store, "_chroma_collections", {}) or {}

    async def _live_unit_ids(self) -> set[str]:
        """Set of every unit_id currently in units.jsonl (dedup-aware)."""
        try:
            units = await self.store._load_all_units()
            return {u.unit_id for u in units}
        except Exception as e:
            log.warning(f"_load_all_units failed: {e}")
            return set()

    @staticmethod
    async def _collection_all_ids(collection) -> list[str]:
        """
        Return every stored ID in a ChromaDB collection.

        `collection.get(include=[])` returns all rows with just the IDs,
        which is the cheapest way to enumerate.
        """
        try:
            res = await asyncio.to_thread(collection.get, include=[])
            return list(res.get("ids", []) or [])
        except Exception as e:
            log.warning(f"collection.get failed: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def find_ghost_ids(self) -> dict[str, list[str]]:
        """
        For each collection, return the IDs stored in ChromaDB but
        absent from units.jsonl.

        Previously this dropped any collection with zero ghosts from the
        return dict (`if gh:`), which made the audit log unreadable —
        `ghosts_found={}` could equally mean "no ghosts anywhere" OR "the
        selector silently mismatched every collection." We now return an
        entry for every collection (even when empty) so the audit ledger
        always shows the full topology. The purge step still skips empty
        lists.
        """
        collections = self._collections()
        if not collections:
            log.warning(
                "[CHROMA-GC] find_ghost_ids: no ChromaDB collections — _init_vector_db failed or store has none"  # noqa: E501
            )
            return {}

        live = await self._live_unit_ids()
        if not live:
            log.warning(
                "[CHROMA-GC] find_ghost_ids: 0 live unit_ids — refusing to compute ghosts to avoid mass-delete"  # noqa: E501
            )
            return {}

        ghosts: dict[str, list[str]] = {}

        for name, collection in collections.items():
            if collection is None:
                ghosts[name] = []
                continue
            try:
                stored = set(await self._collection_all_ids(collection))
                gh = sorted(stored - live)
                ghosts[name] = gh
            except Exception as e:
                log.warning(f"find_ghost_ids({name}) failed: {e}")
                ghosts[name] = []
        return ghosts

    async def purge_ghosts(self, dry_run: bool = False) -> dict:
        """
        Delete ghost IDs from every collection. Chunked to MAX_DELETE_BATCH.

        Returns {collection_name: count_purged}.
        """
        collections = self._collections()
        if not collections:
            return {}

        ghosts = await self.find_ghost_ids()
        result: dict[str, int] = {}

        for name, gh_ids in ghosts.items():
            collection = collections.get(name)
            if collection is None:
                continue
            if dry_run:
                result[name] = len(gh_ids)
                continue

            purged = 0
            for i in range(0, len(gh_ids), MAX_DELETE_BATCH):
                batch = gh_ids[i : i + MAX_DELETE_BATCH]
                try:
                    await asyncio.to_thread(collection.delete, ids=batch)
                    purged += len(batch)
                except Exception as e:
                    log.warning(f"purge_ghosts({name}) batch[{i}:{i+len(batch)}] failed: {e}")
            result[name] = purged
        return result

    async def reindex_missing(self) -> dict:
        """
        Find units that exist in units.jsonl but have NO embedding in
        the collection appropriate to their memory_type, and upsert them.

        This catches silent upsert failures during create_unit / consolidate.
        """
        collections = self._collections()
        if not collections:
            return {"status": "chromadb_unavailable", "reindexed": 0}

        try:
            units = await self.store._load_all_units()
        except Exception as e:
            log.warning(f"reindex_missing load failed: {e}")
            return {"status": "load_failed", "reindexed": 0}

        # Pre-cache every collection's stored IDs to avoid N round-trips
        # to ChromaDB inside the inner loop.
        stored_ids_by_collection: dict[str, set[str]] = {}
        for name, collection in collections.items():
            if collection is None:
                continue
            try:
                stored_ids_by_collection[name] = set(await self._collection_all_ids(collection))
            except Exception as e:
                log.warning(f"reindex_missing precache({name}) failed: {e}")
                stored_ids_by_collection[name] = set()

        # Set of all unit_ids that have ANY embedding anywhere
        all_stored: set[str] = set()
        for ids in stored_ids_by_collection.values():
            all_stored |= ids

        missing = [u for u in units if u.unit_id not in all_stored]
        reindexed = 0
        for unit in missing:
            try:
                await self.store.index_unit(unit)
                reindexed += 1
            except Exception as e:
                log.debug(f"reindex_missing index_unit({unit.unit_id}) failed: {e}")

        return {
            "status": "ok",
            "missing_count": len(missing),
            "reindexed": reindexed,
        }

    async def stats(self) -> dict:
        """
        Returns:
            {
              "collections": {
                  <collection_name>: {"live": N, "ghost": M, "missing": K},
                  ...
              },
              "totals": {"live": ..., "ghost": ..., "missing": ...},
              "live_unit_count": <units.jsonl size>,
            }

        - live    : stored IDs that ARE in units.jsonl (per collection)
        - ghost   : stored IDs that are NOT in units.jsonl (per collection)
        - missing : live unit_ids of this memory_type with NO embedding in
                    their target collection (per collection)
        """
        collections = self._collections()
        if not collections:
            return {
                "status": "chromadb_unavailable",
                "collections": {},
                "totals": {"live": 0, "ghost": 0, "missing": 0},
                "live_unit_count": 0,
            }

        try:
            units = await self.store._load_all_units()
        except Exception as e:
            log.warning(f"stats() unit load failed: {e}")
            units = []

        live_ids = {u.unit_id for u in units}

        # Map each unit to the collection name it SHOULD live in.
        # MemoryStore._get_collection_for_type returns the actual collection
        # object; we reverse-map via _chroma_collections keys.
        target_by_unit: dict[str, str] = {}
        for u in units:
            mtype = getattr(u, "memory_type", "episodic")
            if mtype in collections:
                target_by_unit[u.unit_id] = mtype
            else:
                target_by_unit[u.unit_id] = "default"

        per_collection: dict[str, dict[str, int]] = {}
        total_live = total_ghost = total_missing = 0

        for name, collection in collections.items():
            if collection is None:
                per_collection[name] = {"live": 0, "ghost": 0, "missing": 0}
                continue
            try:
                stored = set(await self._collection_all_ids(collection))
            except Exception as e:
                log.warning(f"stats({name}) get_ids failed: {e}")
                stored = set()

            live = stored & live_ids
            ghost = stored - live_ids
            expected = {uid for uid, tgt in target_by_unit.items() if tgt == name}
            missing = expected - stored

            per_collection[name] = {
                "live": len(live),
                "ghost": len(ghost),
                "missing": len(missing),
            }
            total_live += len(live)
            total_ghost += len(ghost)
            total_missing += len(missing)

        return {
            "status": "ok",
            "collections": per_collection,
            "totals": {
                "live": total_live,
                "ghost": total_ghost,
                "missing": total_missing,
            },
            "live_unit_count": len(live_ids),
        }


# ---------------------------------------------------------------------- #
# Eviction helper for store.py — call this from any code path that       #
# removes a MemUnit from units.jsonl so the embedding goes with it.      #
# ---------------------------------------------------------------------- #


async def delete_unit_embeddings(memory_store, unit_ids) -> int:
    """
    Delete the given unit_ids from EVERY ChromaDB collection.

    Memory-type → collection routing isn't always reliable (a unit may have
    been re-typed after indexing, or indexed into the default collection by
    legacy code), so we just call delete(ids=...) on each collection. ChromaDB
    silently ignores IDs that don't exist, so this is cheap and idempotent.

    Args:
        memory_store: MemoryStore instance
        unit_ids: iterable of unit_ids to remove

    Returns:
        Number of (collection, batch) deletes attempted — purely informational.
    """
    ids = list(unit_ids)
    if not ids:
        return 0

    # Lazy init the vector DB if necessary.
    try:
        memory_store._init_vector_db()
    except Exception as e:
        log.debug(f"delete_unit_embeddings: vector db unavailable: {e}")
        return 0

    collections = getattr(memory_store, "_chroma_collections", {}) or {}
    if not collections:
        return 0

    attempts = 0
    for name, collection in collections.items():
        if collection is None:
            continue
        for i in range(0, len(ids), MAX_DELETE_BATCH):
            batch = ids[i : i + MAX_DELETE_BATCH]
            try:
                await asyncio.to_thread(collection.delete, ids=batch)
                attempts += 1
            except Exception as e:
                log.debug(
                    f"delete_unit_embeddings({name}) batch[{i}:{i+len(batch)}] " f"failed: {e}"
                )
    return attempts


# ---------------------------------------------------------------------- #
# Standalone loop for the scheduler to wrap                              #
# ---------------------------------------------------------------------- #


async def _chroma_gc_loop(
    brain,
    *,
    interval: int = GC_LOOP_INTERVAL,
    threshold: int = GHOST_PURGE_THRESHOLD,
    is_running=None,
    emergency_stop=None,
    stats_dict: Optional[dict] = None,
    audit_path: Optional[Path] = None,
) -> None:
    """
    Loop 4 — ChromaDB garbage collection.

    Cadence: every `interval` seconds (default 1h).
    On each tick:
      1. find_ghost_ids()
      2. If any collection has > `threshold` ghosts, purge it for real.
      3. Append result line to data/memory/chroma_gc.jsonl.
      4. Log: "[CHROMA-GC] purged N ghosts across M collections".
      5. Update stats_dict["last_chroma_gc"] and
         stats_dict["chroma_ghosts_purged_lifetime"].

    Args:
        brain: NCL brain instance — uses brain.memory_store
        interval: seconds between GC ticks
        threshold: ghost count above which to purge
        is_running: optional zero-arg callable returning bool (loop guard)
        emergency_stop: optional asyncio.Event — break when set
        stats_dict: optional dict to mirror counters into (scheduler._stats)
        audit_path: optional path override; defaults to
                    <memory_store.data_dir>/chroma_gc.jsonl
    """
    # Brief startup grace period so we don't race the brain bootstrap.
    await asyncio.sleep(60)

    gc = ChromaGC(brain.memory_store)

    if audit_path is None:
        audit_path = Path(brain.memory_store.data_dir) / "chroma_gc.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _still_running() -> bool:
        if emergency_stop is not None and emergency_stop.is_set():
            return False
        if is_running is None:
            return True
        try:
            return bool(is_running())
        except Exception:
            return True

    while _still_running():
        tick_started = datetime.now(timezone.utc).isoformat()
        try:
            ghosts = await gc.find_ghost_ids()
            ghost_counts = {name: len(ids) for name, ids in ghosts.items()}
            total_ghosts = sum(ghost_counts.values())

            # Purge when EITHER a single collection exceeds the per-collection
            # threshold OR the total across all collections does. Without the
            # total trigger, slow steady drift across many collections (e.g.
            # the legacy `ncl_memory` default + 6 typed collections each
            # accumulating ~10-20 ghosts) would never cross the per-collection
            # bar even at hundreds of total ghosts.
            should_purge = (
                any(c > threshold for c in ghost_counts.values()) or total_ghosts > threshold
            )
            purge_result: dict = {}
            if should_purge:
                purge_result = await gc.purge_ghosts(dry_run=False)

            purged_total = sum(purge_result.values()) if purge_result else 0
            collections_touched = sum(1 for v in purge_result.values() if v > 0)

            log.info(
                f"[CHROMA-GC] purged {purged_total} ghosts across "
                f"{collections_touched} collections "
                f"(found={total_ghosts} ghosts across "
                f"{len(ghost_counts)} collections)"
            )

            # Mirror into scheduler stats
            if stats_dict is not None:
                stats_dict["last_chroma_gc"] = tick_started
                stats_dict["chroma_ghosts_purged_lifetime"] = (
                    stats_dict.get("chroma_ghosts_purged_lifetime", 0) + purged_total
                )

            # Audit log — JSONL append, single fsync per tick.
            record = {
                "ts": tick_started,
                "ghosts_found": ghost_counts,
                "ghosts_found_total": total_ghosts,
                "purged_per_collection": purge_result,
                "purged_total": purged_total,
                "purge_triggered": should_purge,
                "threshold": threshold,
            }
            try:
                with open(audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                log.warning(f"[CHROMA-GC] audit write failed: {e}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"[CHROMA-GC] tick failed: {e}", exc_info=True)

        await asyncio.sleep(interval)
