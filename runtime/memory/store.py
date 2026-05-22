"""Memory system for NCL brain."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import uuid

import aiofiles
from pydantic import ValidationError

log = logging.getLogger("ncl.memory")

from ..ncl_brain.models import MemUnit
from .reflection import MemoryReflector, MemoryCurator
from .entity_extractor import extract_entities_and_relationships
from .importance_scorer import score_memory
from .chroma_gc import delete_unit_embeddings
from .pii_redactor import PIIRedactor
from .authority import tier_for_source as _tier_for_source

# Memory system constraints
MAX_CONTENT_LENGTH = 50_000     # Max characters per memory unit
MAX_TOTAL_UNITS = 25_000        # Max total memory units in store
# Audit 2026-05-22: bumped 10K → 25K to stop eviction thrash. Awarebot
# ingest rate (~568/20min) was way above dedup throughput (200/6h merges),
# so eviction was running every ~4s and burning CPU+IO for no benefit.
# Real fix is dedup throughput; this raises the ceiling in the meantime.
MAX_MEMORY_FILE_BYTES = 200 * 1024 * 1024  # 200 MB — trigger compaction above this

# ChromaDB typed collections — one per memory type
COLLECTION_MAP = {
    "episodic": "ncl_episodic",
    "semantic": "ncl_semantic",
    "procedural": "ncl_procedural",
    "signal": "ncl_signals",
    "decision": "ncl_decisions",
    "preference": "ncl_preferences",
}
DEFAULT_COLLECTION = "ncl_memory"  # Fallback for untyped units

# Two-speed decay rates (FadeMem pattern)
DECAY_RATE_LML = 0.999   # Long-term Memory Layer: ~50% in 29 days (hourly basis: 0.999^24 ≈ 0.976/day)
DECAY_RATE_SML = 0.95     # Short-term Memory Layer: ~50% in ~14 days (daily basis)

# Memory types that auto-route to LML (slow decay)
LML_MEMORY_TYPES = {"semantic", "decision", "preference", "procedural"}
# Memory types that stay in SML (fast decay)
SML_MEMORY_TYPES = {"episodic", "signal"}


class MemoryStore:
    """
    Three-phase memory lifecycle: episodic traces → semantic MemUnits → reconstructive recollection.

    Manages persistence, decay, reinforcement, and search.
    """

    def __init__(self, data_dir: str | Path) -> None:
        """
        Initialize memory store.

        Args:
            data_dir: Directory for memory storage (~/dev/NCL/data/memory/)
        """
        self.data_dir = Path(data_dir).expanduser() / "memory"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.data_dir / "units.jsonl"

        # ── Reader/writer lock (2026-05-22 rewrite) ─────────────────────────
        # Replaces ad-hoc (asyncio.Lock + counter + asyncio.Event) trio that
        # had three cumulative bugs:
        #   1. Lost-wakeup: _acquire_write held _write_lock, then awaited
        #      _no_readers.wait(); a reader entering between writer's
        #      `await wait()` returning and the writer's first instruction
        #      would clear() the event and the writer would never see it.
        #   2. Reader-starvation: every new reader called event.clear()
        #      unconditionally — so a long stream of readers kept resetting
        #      the gate the writer was waiting on (Awarebot signal flood).
        #   3. Writer-preference: none. Writers could be queued behind an
        #      arbitrary number of readers. Under Awarebot's ~500/scan burst
        #      every `create_unit()` parked, blocking `/chat`.
        # The new implementation uses a single asyncio.Condition guarding two
        # counters and a writer-waiting flag. Writers get strict preference:
        # once a writer is waiting, new readers also park behind the
        # writer-waiting predicate, so the writer is guaranteed to drain.
        # All wakeups go through Condition.notify_all() — no lost wakeups.
        self._rw_cond = asyncio.Condition()
        self._readers = 0                # Active reader count
        self._writer_active = False      # True while a write is mutating
        self._writers_waiting = 0        # Queue length for writer-preference
        self._last_consolidation: Optional[datetime] = None
        self._knowledge_graph = None

    async def create_unit(
        self,
        content: str,
        source: str,
        importance: float = 50.0,
        tags: Optional[list[str]] = None,
        memory_type: str = "episodic",
        metadata: Optional[dict] = None,
    ) -> MemUnit:
        """
        Create and persist a new memory unit.

        Args:
            content: Memory content
            source: Source of the memory
            importance: Initial importance score (0-100)
            tags: Search tags
            memory_type: Memory type — "episodic", "semantic", "procedural",
                         "signal", "decision", or "preference". Controls
                         auto-tier assignment (LML vs SML) and decay rate.
            metadata: Optional provenance/runtime bag. Caller-supplied keys
                are preserved; ``authority_tier`` is auto-stamped from
                ``source`` if missing. Awarebot uses this to carry
                ``tier`` (focused/micro/macro), ``composite_score``, and
                ``signal_id`` so retrieval can filter by Awarebot route
                level without an extra join.

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

        # ── PII redaction (Loop 10) ─────────────────────────────────────────
        # Scrub emails, phones, SSNs, API keys, etc. BEFORE the unit is
        # persisted. Same-source strings get the same stable token so
        # cross-unit references survive. Findings recorded to a sidecar
        # ledger via _record_pii_redaction() — never stored alongside the
        # raw content. See runtime/memory/pii_redactor.py for patterns +
        # allowlist (Tailscale 100.x.x.x is infrastructure, not PII).
        _pii_result = PIIRedactor.scan(truncated_content)
        _pii_types_found: list[str] = []
        if _pii_result.redaction_count > 0:
            truncated_content = _pii_result.redacted_text
            _pii_types_found = sorted({f["type"] for f in _pii_result.findings})
            log.info(
                f"[PII] Redacted {_pii_result.redaction_count} items from "
                f"{source} (types={_pii_types_found})"
            )

        unit = MemUnit(
            unit_id=str(uuid.uuid4()),
            content=truncated_content,
            source=source,
            importance=min(100.0, max(0.0, importance)),
            tags=tags or [],
        )

        # ── Authority tier stamping ─────────────────────────────────────────
        # Every memory unit gets an authority_tier in its metadata bag at
        # create time, derived from the source string. This is consumed by
        # the salience formula in working_context.py and by FusedRetriever
        # ranking so a NATRIX directive (tier 100) outranks an Awarebot
        # scrape (tier 20) on identical recency/importance/relevance.
        # See runtime/memory/authority.py for the tier table.
        meta = getattr(unit, "metadata", None)
        if not isinstance(meta, dict):
            meta = {}
            unit.metadata = meta
        # 2026-05-22: caller-supplied metadata is merged FIRST so Awarebot's
        # `route_level`/`tier`/`signal_id` make it onto the unit. Then the
        # authority_tier auto-stamp runs (caller can override authority_tier
        # explicitly if they really want to; otherwise it falls back to
        # source-derived).
        if metadata:
            for k, v in metadata.items():
                if k not in meta:
                    meta[k] = v
        # Normalize Awarebot's `route_level` -> `tier` so downstream queries
        # have a single canonical key. Both stay populated for compat.
        if "tier" not in meta and "route_level" in meta:
            rl = str(meta.get("route_level") or "").strip().lower()
            if rl in {"focused", "micro", "macro"}:
                meta["tier"] = rl
            elif rl in {"critical", "high"}:
                meta["tier"] = "focused"
            elif rl == "medium":
                meta["tier"] = "micro"
            elif rl == "low":
                meta["tier"] = "macro"
        if "authority_tier" not in meta:
            meta["authority_tier"] = int(_tier_for_source(source))

        # Record PII audit entry now that we have the unit_id
        if _pii_result.redaction_count > 0:
            await self._record_pii_redaction(
                unit_id=unit.unit_id,
                source=source,
                count=_pii_result.redaction_count,
                types_found=_pii_types_found,
            )

        # Set memory_type on the unit
        unit.memory_type = memory_type

        # Auto-assign memory tier based on type
        mem_type = getattr(unit, 'memory_type', 'episodic')
        if mem_type in LML_MEMORY_TYPES:
            unit.memory_tier = "LML"
            unit.decay_rate = DECAY_RATE_LML
        else:
            unit.memory_tier = "SML"
            unit.decay_rate = DECAY_RATE_SML

        # Optional: LLM importance scoring for high-value content
        # Only score if importance was set to default (50.0) — caller-specified importance takes precedence
        if importance == 50.0:
            try:
                from .importance_scorer import score_memory, rule_based_score
                # Use LLM scoring for content that rule-based scoring rates >= 7 (high-value)
                rule_pre_score = rule_based_score(content, source, tags)
                use_llm = rule_pre_score >= 7.0
                scoring = await score_memory(content, source, tags, use_llm=use_llm)
                unit.importance = min(100.0, max(0.0, scoring["final_score"]))
                if scoring.get("llm_score") is not None:
                    unit.llm_importance_score = scoring["llm_score"]
                # Use inferred memory_type if not explicitly set
                if not hasattr(unit, '_type_set_explicitly'):
                    inferred_type = scoring.get("memory_type", "episodic")
                    if inferred_type != "episodic":  # Only override if not default
                        unit.memory_type = inferred_type
            except Exception as e:
                log.debug(f"Importance scoring skipped: {e}")

        # Acquire exclusive write lock (waits for readers to finish).
        await self._acquire_write()
        try:
            await self._ensure_capacity()
            await self._persist_unit(unit)
        finally:
            self._release_write()

        # Index in vector DB for semantic search (outside lock — read-only path)
        await self.index_unit(unit)

        return unit

    async def persist_units_batch(self, units: list[MemUnit]) -> int:
        """Persist a batch of pre-built MemUnits under a SINGLE write-lock
        acquisition.

        Used by AsyncMemoryWriter under Awarebot flood: instead of 500
        sequential ``create_unit`` calls each fighting for the write lock,
        the drainer collects a batch of WriteRequests, runs the expensive
        per-unit enrichment in parallel OUTSIDE the lock, then hands the
        finalized MemUnits to this batched persist.

        Durability contract: every unit in ``units`` is fsync'd before this
        method returns. Atomic per-unit — a crash mid-batch leaves a
        partial-but-valid JSONL prefix (last record may be missing, never
        torn since fsync is per-write).

        Args:
            units: Pre-built MemUnit instances. Authority tier + decay
                rate + memory_type/tier must already be set by caller.

        Returns:
            Number of units actually persisted.
        """
        if not units:
            return 0

        await self._acquire_write()
        try:
            # _ensure_capacity is fast-path now (file-size estimate); one
            # call is enough even for batch of 500.
            await self._ensure_capacity()
            # Single open, many appends, one fsync at the end. ~50x faster
            # than create_unit × N under flood.
            async with aiofiles.open(self.memory_file, "a") as f:
                for unit in units:
                    await f.write(unit.model_dump_json() + "\n")
                await f.flush()
                os.fsync(f.fileno())
        finally:
            self._release_write()

        # Index outside the write lock (ChromaDB has its own locking)
        for unit in units:
            try:
                await self.index_unit(unit)
            except Exception as e:
                log.debug(f"persist_units_batch: index_unit failed for {unit.unit_id}: {e}")

        return len(units)

    async def _acquire_read(self) -> None:
        """Acquire a shared read lock.

        Writer-preference: if any writer is queued or active we park here so
        a stream of readers (Awarebot signal flood => semantic_search calls)
        can never starve a pending write. Multiple readers may hold the
        lock concurrently once admitted.
        """
        async with self._rw_cond:
            # Park while a writer is mutating OR is queued ahead of us.
            while self._writer_active or self._writers_waiting > 0:
                await self._rw_cond.wait()
            self._readers += 1

    async def _release_read(self) -> None:
        """Release a shared read lock and notify waiters on the gate.

        Always notify_all so any writer parked on the predicate
        ``readers == 0 and not writer_active`` can re-evaluate.
        """
        async with self._rw_cond:
            if self._readers > 0:
                self._readers -= 1
            # Notify both queued writers (readers==0 may now hold) and
            # readers (writer may have just finished). Notify cost is O(N)
            # but coalesces — predicate filter is cheap.
            self._rw_cond.notify_all()

    async def _acquire_write(self) -> None:
        """Acquire an exclusive write lock.

        Single-writer semantics. Writes block on (a) the absence of any
        active reader and (b) the absence of any other active writer.
        Writer-waiting count is bumped BEFORE we await — new readers see
        this and queue behind us (writer-preference).
        """
        async with self._rw_cond:
            self._writers_waiting += 1
            acquired = False
            try:
                while self._writer_active or self._readers > 0:
                    await self._rw_cond.wait()
                self._writer_active = True
                acquired = True
            finally:
                # Decrement waiting count whether we acquired or were
                # cancelled — leaving it bumped would permanently block
                # readers behind a writer that never ran.
                self._writers_waiting -= 1
                # On cancellation, wake readers/other writers since the
                # writers_waiting decrement may have unblocked them.
                if not acquired:
                    self._rw_cond.notify_all()

    def _release_write(self) -> None:
        """Release the exclusive write lock and wake all waiters.

        Schedules an async task to take the condition + notify; this keeps
        the public API synchronous (matches the pre-rewrite contract — all
        ``finally: self._release_write()`` call sites stay unchanged).

        Safe to call when not held: logs and returns without raising. This
        prevents the consolidate_v2() double-release path from corrupting
        another writer's lock state.
        """
        if not self._writer_active:
            log.debug("_release_write called when no writer active (idempotent)")
            return
        # Flip flag synchronously so a same-microtask _acquire_write sees it
        self._writer_active = False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_release())

    async def _notify_release(self) -> None:
        """Background coroutine to wake waiters after a write completes."""
        async with self._rw_cond:
            self._rw_cond.notify_all()

    async def get_unit(self, unit_id: str) -> Optional[MemUnit]:
        """
        Retrieve a memory unit and update access time.

        Reinforcement changes are persisted to disk via a full rewrite
        so that updated scores survive restarts.

        Args:
            unit_id: Unit ID to retrieve

        Returns:
            MemUnit or None if not found
        """
        await self._acquire_read()
        try:
            unit = await self._load_unit(unit_id)
        finally:
            await self._release_read()
        if unit:
            # Reinforce: boost importance and update access time
            unit.last_accessed = datetime.now(timezone.utc)
            unit.reinforcement_count += 1
            unit.importance = min(100.0, unit.importance * 1.2)
            # Persist reinforcement to disk so changes survive restarts
            await self._persist_reinforcement(unit)
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
        await self._acquire_read()
        try:
            units = await self._load_all_units()
        finally:
            await self._release_read()
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
        # Acquire exclusive write lock BEFORE loading units so that any
        # concurrent create_unit() call either completes fully before we read
        # (and its new unit is included in our snapshot) or is blocked until
        # we finish the rewrite (and its append happens after our new file is
        # in place).  Without this lock the window between _load_all_units()
        # and the atomic rename could silently discard a concurrently appended
        # unit.
        units: list[MemUnit] = []
        surviving: list[MemUnit] = []
        pruned = 0
        merged = 0
        clusters: list[list[MemUnit]] = []
        pruned_ids: set[str] = set()

        await self._acquire_write()
        try:
            units = await self._load_all_units()
            if not units:
                return {"total_before": 0, "total_after": 0, "pruned": 0, "merged": 0, "clusters": 0}

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
                # Strip any existing [CONSOLIDATED ...] markers before merging to prevent stacking
                import re
                _consolidation_re = re.compile(r"\[CONSOLIDATED[^\]]*\]\s*")
                combined_content = " | ".join(
                    _consolidation_re.sub("", u.content).strip()[:200]
                    for u in sorted(cluster, key=lambda x: x.importance, reverse=True)
                )
                all_tags = list(set(tag for u in cluster for tag in u.tags))
                max_importance = max(u.importance for u in cluster)
                total_reinforcements = sum(u.reinforcement_count for u in cluster)

                # Extract original source labels — strip any nested "consolidation:" prefixes
                # so we don't get endlessly growing tags like
                # "consolidation:consolidation:awarebot:reddit,consolidation:..."
                original_sources: set[str] = set()
                for u in cluster:
                    for part in u.source.split(","):
                        part = part.strip()
                        while part.startswith("consolidation:"):
                            part = part[len("consolidation:"):]
                        if part:
                            original_sources.add(part)
                source_label = ",".join(sorted(original_sources)[:4])

                # Create consolidated unit
                consolidated = MemUnit(
                    unit_id=cluster[0].unit_id,  # Keep oldest ID
                    content=combined_content[:2000],
                    source=f"consolidation:{source_label}" if source_label else "consolidation",
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

            # Build the set of unit_ids that NO LONGER live in units.jsonl
            # so we can delete their embeddings inline (instead of waiting
            # for the GC loop). A consolidated unit re-uses cluster[0].unit_id,
            # so subtract those to avoid deleting the surviving embedding.
            surviving_ids = {u.unit_id for u in surviving}
            pruned_ids = {u.unit_id for u in units if u.unit_id not in surviving_ids}

            if pruned > 0 or merged > 0:
                # Rewrite memory file atomically (still inside the write lock)
                await self._rewrite_units(surviving)

                log.info(
                    f"Memory consolidation: {len(units)} → {len(surviving)} units "
                    f"(pruned={pruned}, merged={merged})"
                )

        finally:
            self._release_write()

        # Outside the write lock — delete embeddings for removed units.
        if pruned_ids:
            try:
                await delete_unit_embeddings(self, pruned_ids)
            except Exception as e:
                log.debug(f"consolidate: embedding cleanup failed: {e}")

        self._last_consolidation = datetime.now(timezone.utc)

        # Reindex vector DB to purge ghost entries from pruned/merged units
        try:
            reindex_result = await self.reindex_all()
            log.info(f"Post-consolidation reindex: {reindex_result.get('indexed', 0)} units indexed")
        except Exception as e:
            log.warning(f"Post-consolidation reindex failed: {e}")

        return {
            "total_before": len(units),
            "total_after": len(surviving),
            "pruned": pruned,
            "merged": merged,
            "clusters": len(clusters),
        }

    async def consolidate_v2(self) -> dict:
        """
        Enhanced consolidation with reflection loop and entity extraction.

        Pipeline:
        1. Load all units
        2. Apply two-speed decay
        3. Run fast reflection (quality scoring, dedup, conflict detection)
        4. Run curation (merge, prune, promote/demote tiers)
        5. Extract entities from new/modified units
        6. Persist surviving units

        Falls back to consolidate() if reflection modules are unavailable.
        """
        try:
            reflector = MemoryReflector()
            curator = MemoryCurator(
                knowledge_graph=getattr(self, '_knowledge_graph', None)
            )
        except Exception as e:
            log.warning(f"Reflection modules unavailable, falling back to basic consolidation: {e}")
            return await self.consolidate()

        await self._acquire_write()
        try:
            units = await self._load_all_units()
            if not units:
                return {
                    "total_before": 0, "total_after": 0,
                    "reflection": {}, "curation": {},
                }

            total_before = len(units)

            # Phase 1: Apply decay
            for unit in units:
                unit.importance = self._apply_decay(unit)

            # Phase 2: Prune below threshold (same as basic consolidation)
            active_units = [u for u in units if u.importance >= 5.0]
            pruned_by_decay = len(units) - len(active_units)

            # Phase 3: Run reflection
            reflection_result = await reflector.fast_reflect(active_units)

            # Phase 4: Run curation
            curation_result = await curator.curate(active_units, reflection_result)

            # Phase 5: Build surviving unit list
            pruned_ids = set(curation_result.get("pruned", []))
            merged_away_ids = set()
            for _, victim_ids in curation_result.get("merged", []):
                merged_away_ids.update(victim_ids)

            remove_ids = pruned_ids | merged_away_ids
            surviving = [u for u in active_units if u.unit_id not in remove_ids]

            # Phase 6: Entity extraction on units that don't have entities yet
            entities_extracted = 0
            for unit in surviving[:50]:  # Cap to avoid long runs
                if not getattr(unit, 'entities', None):
                    try:
                        # Use LLM extraction for high-importance units (>= 70)
                        use_llm_extract = unit.importance >= 70.0
                        extraction = await extract_entities_and_relationships(
                            unit.content, unit.source, use_llm=use_llm_extract
                        )
                        unit.entities = extraction.get("entities", [])
                        unit.relationships = extraction.get("relationships", [])
                        if unit.entities:
                            entities_extracted += 1
                    except Exception as e:
                        log.debug(f"Entity extraction failed for {unit.unit_id}: {e}")

            # Phase 7: Persist
            if len(surviving) != total_before or pruned_by_decay > 0:
                await self._rewrite_units(surviving)
                log.info(
                    f"Memory consolidation v2: {total_before} → {len(surviving)} units "
                    f"(decay_pruned={pruned_by_decay}, "
                    f"reflection_pruned={len(pruned_ids)}, "
                    f"merged={len(merged_away_ids)}, "
                    f"entities_extracted={entities_extracted})"
                )

                # Delete embeddings for every unit that's no longer in
                # units.jsonl: decay-pruned, reflection-pruned, merged away.
                surviving_ids = {u.unit_id for u in surviving}
                removed_ids = {u.unit_id for u in units if u.unit_id not in surviving_ids}
                if removed_ids:
                    try:
                        await delete_unit_embeddings(self, removed_ids)
                    except Exception as e:
                        log.debug(f"consolidate_v2: embedding cleanup failed: {e}")

            self._last_consolidation = datetime.now(timezone.utc)

            # Reindex vector DB to purge ghost entries from pruned/merged units
            try:
                reindex_result = await self.reindex_all()
                log.info(f"Post-consolidation-v2 reindex: {reindex_result.get('indexed', 0)} units indexed")
            except Exception as e:
                log.warning(f"Post-consolidation-v2 reindex failed: {e}")

            return {
                "total_before": total_before,
                "total_after": len(surviving),
                "pruned_by_decay": pruned_by_decay,
                "reflection": reflection_result.get("stats", {}),
                "curation": curation_result.get("stats", {}),
                "entities_extracted": entities_extracted,
            }

        except Exception as e:
            log.error(f"consolidate_v2 failed, falling back to basic: {e}")
            # Release the write lock BEFORE calling consolidate() so
            # consolidate() can acquire it itself. _release_write is now
            # idempotent — the finally below becomes a no-op.
            self._release_write()
            return await self.consolidate()

        finally:
            # Idempotent — safe even if the except-branch already released.
            self._release_write()

    def set_knowledge_graph(self, kg) -> None:
        """Set the knowledge graph instance for entity extraction during consolidation."""
        self._knowledge_graph = kg

    @staticmethod
    def _normalize_source(source: str) -> str:
        """Strip nested consolidation: prefixes from a source tag.

        Turns 'consolidation:consolidation:awarebot:reddit,consolidation:awarebot:google_trends'
        into  'consolidation:awarebot:google_trends,awarebot:reddit'
        """
        parts: set[str] = set()
        for part in source.split(","):
            part = part.strip()
            while part.startswith("consolidation:"):
                part = part[len("consolidation:"):]
            if part:
                parts.add(part)
        if not parts:
            return source  # can't normalize, leave as-is
        cleaned = ",".join(sorted(parts)[:4])
        return f"consolidation:{cleaned}" if "consolidation" in source.lower() else cleaned

    async def migrate_memory_types(self) -> dict:
        """One-time migration: infer memory_type and memory_tier for all existing units.

        Units created before the typed memory system default to episodic/SML.
        This scans content, source, and tags to assign proper types and tiers.
        """
        await self._acquire_write()
        try:
            units = await self._load_all_units()
            migrated = 0
            promoted_lml = 0

            for unit in units:
                old_type = getattr(unit, 'memory_type', 'episodic')
                old_tier = getattr(unit, 'memory_tier', 'SML')
                new_type = old_type
                source_lower = unit.source.lower()
                content_lower = unit.content.lower()
                tags_lower = [t.lower() for t in unit.tags]

                # Infer memory_type from source and content
                if "predictor" in source_lower or "prediction" in source_lower:
                    new_type = "signal"
                elif "council" in source_lower:
                    new_type = "semantic"
                elif "journal" in source_lower:
                    if "reflection" in source_lower:
                        new_type = "semantic"
                    else:
                        new_type = "episodic"
                elif any(kw in content_lower for kw in ["decided", "decision", "approved", "committed to", "mandate"]):
                    new_type = "decision"
                elif any(kw in content_lower for kw in ["always ", "never ", "prefer", "dislike"]):
                    new_type = "preference"
                elif any(kw in content_lower for kw in ["workflow", "procedure", "how to", "step 1", "step 2"]):
                    new_type = "procedural"
                elif any(kw in content_lower for kw in ["alert", "signal", "spike", "breaking", "surge", "crash"]):
                    new_type = "signal"
                elif "options_flow" in source_lower or "unusual_whales" in " ".join(tags_lower):
                    new_type = "signal"
                elif unit.reinforcement_count >= 3 and unit.importance >= 60:
                    new_type = "semantic"  # Frequently accessed high-importance → knowledge

                if new_type != old_type:
                    unit.memory_type = new_type
                    migrated += 1

                # Auto-assign tier based on new type
                if new_type in LML_MEMORY_TYPES:
                    if old_tier != "LML":
                        unit.memory_tier = "LML"
                        unit.decay_rate = DECAY_RATE_LML
                        promoted_lml += 1
                else:
                    unit.memory_tier = "SML"
                    unit.decay_rate = DECAY_RATE_SML

            if migrated > 0 or promoted_lml > 0:
                await self._rewrite_units(units)
                log.info(f"Memory type migration: {migrated} types reassigned, {promoted_lml} promoted to LML")

            # Count final distribution
            type_counts = {}
            tier_counts = {"LML": 0, "SML": 0}
            for unit in units:
                mt = getattr(unit, 'memory_type', 'episodic')
                type_counts[mt] = type_counts.get(mt, 0) + 1
                tier = getattr(unit, 'memory_tier', 'SML')
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            return {
                "total_units": len(units),
                "types_migrated": migrated,
                "promoted_to_lml": promoted_lml,
                "by_type": type_counts,
                "by_tier": tier_counts,
            }
        finally:
            self._release_write()

    async def cleanup_sources(self) -> dict:
        """One-time fix: normalize corrupted source tags AND strip
        [CONSOLIDATED from N units] markers from content fields.
        """
        import re
        _consolidation_re = re.compile(r"\[CONSOLIDATED[^\]]*\]\s*")
        await self._acquire_write()
        try:
            units = await self._load_all_units()
            sources_fixed = 0
            content_fixed = 0
            for unit in units:
                # Fix source tags
                normalized = self._normalize_source(unit.source)
                if normalized != unit.source:
                    unit.source = normalized
                    sources_fixed += 1
                # Fix content — strip all [CONSOLIDATED ...] markers
                if "[CONSOLIDATED" in unit.content:
                    cleaned = _consolidation_re.sub("", unit.content).strip()
                    if cleaned and cleaned != unit.content:
                        unit.content = cleaned
                        content_fixed += 1
            if sources_fixed or content_fixed:
                await self._rewrite_units(units)
                log.info(f"Source cleanup: {sources_fixed} sources + {content_fixed} content fields fixed ({len(units)} units)")
            return {"total_units": len(units), "sources_fixed": sources_fixed, "content_fixed": content_fixed}
        finally:
            self._release_write()

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
        Apply two-speed exponential decay (FadeMem pattern).

        LML (Long-term Memory Layer): slow decay for facts, decisions, preferences
        SML (Short-term Memory Layer): fast decay for ephemeral signals, episodes

        Formula: importance *= decay_rate^(days_since_access)
        """
        days_since = (datetime.now(timezone.utc) - unit.last_accessed).days

        # Determine effective decay rate based on tier
        tier = getattr(unit, 'memory_tier', 'SML')
        if tier == "LML":
            effective_rate = DECAY_RATE_LML
        else:
            effective_rate = DECAY_RATE_SML

        decayed = unit.importance * (effective_rate ** days_since)
        return max(0.0, min(100.0, decayed))

    async def _ensure_capacity(self) -> None:
        """
        Ensure memory store stays within capacity limits.

        If total units exceed MAX_TOTAL_UNITS, evict oldest low-importance units
        (importance < 30, sorted by creation date ascending).

        Fast-path optimization (2026-05-22): the previous implementation
        called _load_all_units() unconditionally on EVERY create_unit, which
        scanned the entire 9.7k-unit JSONL file (~50ms each). Under Awarebot
        flood (~500 writes/scan) that was 25+ seconds of write-lock time
        per drainer cycle, blocking /chat. We now estimate line count from
        the file size and only do the full scan when we're plausibly close
        to capacity (within 5% of MAX_TOTAL_UNITS).
        """
        try:
            file_size = (
                self.memory_file.stat().st_size
                if self.memory_file.exists() else 0
            )
        except OSError:
            file_size = 0

        # MemUnit JSONL lines avg ~1.5-2 KB. A conservative 800-byte/line
        # estimate keeps us safely on the slow path before real capacity.
        # 9,500 units * 800B = 7.6 MB — we slow-path scan once we cross
        # that threshold (5% under MAX_TOTAL_UNITS=10_000 cap).
        AVG_BYTES_PER_LINE = 800
        FAST_PATH_MAX_BYTES = int(MAX_TOTAL_UNITS * AVG_BYTES_PER_LINE * 0.95)
        if file_size < FAST_PATH_MAX_BYTES:
            return  # Far from capacity — skip the full-file scan

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

            # Drop embeddings for the evicted units so they don't ghost
            # in ChromaDB (loop-4 GC catches these too, but doing it
            # at the eviction point keeps the vector store accurate
            # between GC ticks).
            try:
                await delete_unit_embeddings(self, evict_ids)
            except Exception as e:
                log.debug(f"_ensure_capacity: embedding cleanup failed: {e}")

    async def _rewrite_units(self, units: list[MemUnit]) -> None:
        """
        Atomically rewrite the entire memory file with the given units.

        Writes to a .tmp file first, then uses os.replace() for an atomic
        rename so a crash mid-write never leaves a partial/corrupt file.

        Args:
            units: List of MemUnits to persist
        """
        tmp = str(self.memory_file) + ".tmp"
        try:
            async with aiofiles.open(tmp, "w") as f:
                for unit in units:
                    await f.write(unit.model_dump_json() + "\n")
                await f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(self.memory_file))
            log.debug(f"Memory file atomically rewritten with {len(units)} units")
        except Exception as e:
            log.error(f"Failed to rewrite memory file: {e}")
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def _persist_reinforcement(self, unit: MemUnit) -> None:
        """
        Persist a reinforced unit to disk by rewriting the JSONL file.

        This ensures that importance score updates, access times, and
        reinforcement counts survive process restarts.
        """
        try:
            await self._acquire_write()
            try:
                units = await self._load_all_units()
                for i, u in enumerate(units):
                    if u.unit_id == unit.unit_id:
                        units[i] = unit
                        break
                await self._rewrite_units(units)
            finally:
                self._release_write()
        except Exception as e:
            log.warning(f"Failed to persist reinforcement for {unit.unit_id}: {e}")

    # ── PII audit ledger (Loop 10) ──────────────────────────────────────
    # JSONL sidecar at data/memory/pii_redactions.jsonl so the user can
    # audit what got scrubbed without ever seeing the raw PII. MemUnit
    # itself has no `metadata` field, so we keep the audit trail in a
    # separate file (same pattern as runtime/cost_tracker.py).
    _PII_LEDGER_NAME = "pii_redactions.jsonl"

    @property
    def _pii_ledger_path(self) -> Path:
        return self.data_dir / self._PII_LEDGER_NAME

    async def _record_pii_redaction(
        self,
        unit_id: str,
        source: str,
        count: int,
        types_found: list[str],
    ) -> None:
        """Append a single PII redaction audit record.

        Never includes the raw matched substrings — only counts + types so
        the user can verify the redactor is doing the right thing without
        the audit log itself becoming a PII vector.
        """
        entry = {
            "unit_id": unit_id,
            "source": source,
            "count": count,
            "types_found": types_found,
            "redacted_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with aiofiles.open(self._pii_ledger_path, "a") as f:
                await f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.warning(f"Failed to record PII redaction for {unit_id}: {e}")

    async def get_pii_redactions(self, limit: int = 20) -> dict:
        """Read recent PII redaction audit records (most-recent first).

        Returns:
            {
              "redactions": [{unit_id, source, count, types_found, redacted_at}],
              "lifetime_total": int,
            }
        """
        path = self._pii_ledger_path
        if not path.exists():
            return {"redactions": [], "lifetime_total": 0}

        entries: list[dict] = []
        try:
            async with aiofiles.open(path, "r") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning(f"Failed to read PII ledger: {e}")
            return {"redactions": [], "lifetime_total": 0}

        lifetime_total = len(entries)
        recent = entries[-limit:][::-1] if limit > 0 else entries[::-1]
        return {"redactions": recent, "lifetime_total": lifetime_total}

    async def _persist_unit(self, unit: MemUnit) -> None:
        """
        Persist a memory unit to NDJSON file.

        Checks file size before appending; if the file exceeds
        MAX_MEMORY_FILE_BYTES it is compacted (rewritten with only the
        current live units) before the new entry is appended.

        Args:
            unit: MemUnit to persist
        """
        # File-size guard — compact before we grow beyond the limit
        try:
            if (
                self.memory_file.exists()
                and self.memory_file.stat().st_size >= MAX_MEMORY_FILE_BYTES
            ):
                log.warning(
                    "Memory file size %d bytes exceeds limit %d — compacting",
                    self.memory_file.stat().st_size,
                    MAX_MEMORY_FILE_BYTES,
                )
                await self._compact_memory_file()
        except OSError:
            pass

        async with aiofiles.open(self.memory_file, "a") as f:
            await f.write(unit.model_dump_json() + "\n")
            await f.flush()
            os.fsync(f.fileno())

    async def _compact_memory_file(self) -> None:
        """
        Rewrite the memory NDJSON file to eliminate duplicate/stale entries.

        Loads all units, applies decay, drops units below importance threshold,
        and rewrites the file — effectively removing tombstoned/updated entries
        that accumulate via append-only writes.
        """
        try:
            units = await self._load_all_units()
            # Apply decay and filter out very low-importance units
            surviving = [u for u in units if self._apply_decay(u) >= 1.0]
            await self._rewrite_units(surviving)
            log.info(
                "Memory file compacted: %d → %d units",
                len(units),
                len(surviving),
            )
            # Drop embeddings for the units that just got compacted out.
            surviving_ids = {u.unit_id for u in surviving}
            dropped_ids = {u.unit_id for u in units if u.unit_id not in surviving_ids}
            if dropped_ids:
                try:
                    await delete_unit_embeddings(self, dropped_ids)
                except Exception as e:
                    log.debug(f"_compact_memory_file: embedding cleanup failed: {e}")
        except Exception as e:
            log.error("Memory file compaction failed: %s", e)

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
        Load all memory units from NDJSON file, deduplicated by unit_id.

        When the same unit_id appears multiple times (e.g. from append-only
        updates), the last occurrence wins — it has the most recent state.

        Returns:
            List of unique MemUnits
        """
        seen: dict[str, MemUnit] = {}
        if not self.memory_file.exists():
            return []

        async with aiofiles.open(self.memory_file, "r") as f:
            async for line in f:
                if not line.strip():
                    continue
                try:
                    unit = MemUnit(**json.loads(line))
                    seen[unit.unit_id] = unit  # last occurrence wins
                except (json.JSONDecodeError, ValidationError) as e:
                    log.warning(f"Failed to parse memory unit: {e}")
                    continue
        return list(seen.values())

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
            "episodic_traces": len([u for u in units if getattr(u, 'memory_type', 'episodic') in ('episodic', 'signal')]),
            "semantic_units": len([u for u in units if getattr(u, 'memory_type', 'episodic') in ('semantic', 'decision', 'preference', 'procedural')]),
            "by_type": {
                mt: len([u for u in units if getattr(u, 'memory_type', 'episodic') == mt])
                for mt in ("episodic", "semantic", "procedural", "signal", "decision", "preference")
            },
            "by_tier": {
                "LML": len([u for u in units if getattr(u, 'memory_tier', 'SML') == 'LML']),
                "SML": len([u for u in units if getattr(u, 'memory_tier', 'SML') == 'SML']),
            },
            "decay_factor": 0.95,
            "retrievals_today": sum(1 for u in today_units if u.reinforcement_count > 0),
            "avg_importance": avg_importance,
        }

    # ── Vector Search (ChromaDB) ─────────────────────────────────────────────
    # Adds semantic similarity search alongside existing tag-based search.
    # Falls back to keyword matching if chromadb is not installed.

    def _init_vector_db(self) -> bool:
        """Lazily initialize typed ChromaDB collections. Returns True on success."""
        if hasattr(self, "_chroma_collections"):
            return bool(self._chroma_collections)
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(
                path=str(self.data_dir / "chromadb")
            )
            self._chroma_collections = {}
            # Create/get all typed collections
            for mem_type, col_name in COLLECTION_MAP.items():
                self._chroma_collections[mem_type] = self._chroma_client.get_or_create_collection(
                    name=col_name,
                    metadata={"hnsw:space": "cosine"},
                )
            # Legacy default collection for backward compatibility
            self._chroma_collections["default"] = self._chroma_client.get_or_create_collection(
                name=DEFAULT_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            # Keep _chroma_collection for any code that still references it
            self._chroma_collection = self._chroma_collections["default"]
            log.info(f"ChromaDB initialized with {len(self._chroma_collections)} typed collections at {self.data_dir / 'chromadb'}")
            return True
        except ImportError:
            log.info("chromadb not installed — using keyword fallback for semantic search")
            self._chroma_collections = {}
            self._chroma_collection = None
            return False
        except Exception as e:
            log.warning(f"ChromaDB init failed: {e} — using keyword fallback")
            self._chroma_collections = {}
            self._chroma_collection = None
            return False

    def _get_collection_for_type(self, memory_type: str):
        """Get the ChromaDB collection for a given memory type."""
        if not hasattr(self, "_chroma_collections") or not self._chroma_collections:
            return None
        return self._chroma_collections.get(memory_type, self._chroma_collections.get("default"))

    async def index_unit(self, unit: MemUnit) -> None:
        """Add a memory unit to the appropriate typed vector collection."""
        if not self._init_vector_db():
            return
        try:
            mem_type = getattr(unit, 'memory_type', 'episodic')
            collection = self._get_collection_for_type(mem_type)
            if not collection:
                collection = self._chroma_collections.get("default")
            if not collection:
                return
            await asyncio.to_thread(
                collection.upsert,
                ids=[unit.unit_id],
                documents=[unit.content],
                metadatas=[{
                    "source": unit.source,
                    "importance": unit.importance,
                    "tags": ",".join(unit.tags),
                    "created_at": unit.created_at.isoformat(),
                    "memory_type": mem_type,
                    "memory_tier": getattr(unit, 'memory_tier', 'SML'),
                }],
            )
        except Exception as e:
            log.warning(f"Failed to index unit {unit.unit_id}: {e}")

    async def _load_units_batch(self, unit_ids: set) -> dict[str, MemUnit]:
        """
        Load multiple memory units in a single sequential pass through the file.

        More efficient than calling _load_unit() N times (each of which opens
        and scans the file independently).

        Args:
            unit_ids: Set of unit IDs to retrieve.

        Returns:
            Dict mapping unit_id → MemUnit for all found IDs.
        """
        found: dict[str, MemUnit] = {}
        if not unit_ids or not self.memory_file.exists():
            return found
        remaining = set(unit_ids)
        try:
            async with aiofiles.open(self.memory_file, "r") as f:
                async for line in f:
                    if not remaining:
                        break
                    if not line.strip():
                        continue
                    try:
                        unit = MemUnit(**json.loads(line))
                        if unit.unit_id in remaining:
                            found[unit.unit_id] = unit
                            remaining.discard(unit.unit_id)
                    except (json.JSONDecodeError, ValidationError):
                        continue
        except FileNotFoundError:
            pass
        return found

    async def semantic_search(
        self,
        query: str,
        n_results: int = 10,
        importance_threshold: float = 0.0,
        memory_types: Optional[list[str]] = None,
    ) -> list[MemUnit]:
        """
        Search memory by semantic similarity across typed ChromaDB collections.

        Falls back to keyword matching if ChromaDB is unavailable.

        Args:
            query: Natural language search query
            n_results: Max results to return
            importance_threshold: Minimum importance score
            memory_types: Optional filter — only search these memory types.
                          If None, searches all collections.

        Returns:
            List of matching MemUnits sorted by relevance
        """
        if self._init_vector_db():
            try:
                all_unit_ids = []
                # Determine which collections to search
                if memory_types:
                    collections_to_search = [
                        (mt, self._get_collection_for_type(mt))
                        for mt in memory_types
                    ]
                else:
                    collections_to_search = list(self._chroma_collections.items())

                for type_name, collection in collections_to_search:
                    if not collection:
                        continue
                    try:
                        results = await asyncio.to_thread(
                            collection.query,
                            query_texts=[query],
                            n_results=min(n_results * 2, 20),
                        )
                        if results and results["ids"] and results["ids"][0]:
                            all_unit_ids.extend(results["ids"][0])
                    except Exception as e:
                        log.debug(f"Search in collection {type_name} failed: {e}")

                if all_unit_ids:
                    unit_ids = set(all_unit_ids)
                    units_by_id = await self._load_units_batch(unit_ids)
                    units = []
                    seen = set()
                    for uid in all_unit_ids:
                        if uid in seen:
                            continue
                        seen.add(uid)
                        unit = units_by_id.get(uid)
                        if unit and unit.importance >= importance_threshold:
                            units.append(unit)
                        if len(units) >= n_results:
                            break
                    return units
            except Exception as e:
                log.warning(f"ChromaDB search failed, using keyword fallback: {e}")

        # Keyword fallback — unchanged
        query_words = set(query.lower().split())
        units = await self._load_all_units()
        scored = []
        for unit in units:
            if unit.importance < importance_threshold:
                continue
            content_words = set(unit.content.lower().split())
            overlap = len(query_words & content_words)
            if overlap > 0:
                scored.append((overlap, unit))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [unit for _, unit in scored[:n_results]]

    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_fusion: bool = False,
        importance_threshold: float = 0.0,
        weights: Optional[dict] = None,
    ) -> list:
        """Unified memory search.

        Default (``use_fusion=False``): routes through ``semantic_search``
        (vector-only) and returns ``list[MemUnit]`` — preserves existing
        caller behaviour.

        With ``use_fusion=True``: routes through the Loop-11 ``FusedRetriever``
        (vector + BM25 + entity-overlap fused via Reciprocal Rank Fusion).
        Returns ``list[dict]`` with ``fused_score`` + ``signal_breakdown``.

        Falls back to vector-only if FusedRetriever or BM25 are unavailable
        (e.g. rank_bm25 not installed, index never built, KG missing).
        """
        if not use_fusion:
            return await self.semantic_search(
                query=query,
                n_results=top_k,
                importance_threshold=importance_threshold,
            )

        try:
            bm25 = getattr(self, "_bm25_index", None)
            if bm25 is None:
                from .retrieval.bm25 import BM25Index as _BM25
                self._bm25_index = _BM25(self)
                bm25 = self._bm25_index

            from .retrieval.fusion import FusedRetriever
            fr = FusedRetriever(
                self,
                bm25,
                knowledge_graph=getattr(self, "_knowledge_graph", None),
            )
            results = await fr.retrieve(query, top_k=top_k, weights=weights)
            if importance_threshold > 0:
                results = [r for r in results if r.get("importance", 0) >= importance_threshold]
            return results
        except Exception as e:
            log.warning(f"FusedRetriever failed ({e}) — falling back to vector-only")
            return await self.semantic_search(
                query=query,
                n_results=top_k,
                importance_threshold=importance_threshold,
            )

    async def reindex_all(self) -> dict:
        """Rebuild all typed vector indexes from JSONL store."""
        if not self._init_vector_db():
            return {"status": "chromadb_unavailable", "indexed": 0}
        units = await self._load_all_units()
        indexed = 0
        for unit in units:
            await self.index_unit(unit)
            indexed += 1
        return {"status": "ok", "indexed": indexed, "collections": len(self._chroma_collections)}

    async def store(self, data: dict) -> MemUnit:
        """
        Convenience alias used by the autonomous scheduler.

        Accepts a raw dict with optional fields:
          - content (str): text to store; falls back to JSON-encoding data
          - source  (str): origin label
          - importance (float): 0-100
          - tags (list[str])

        All other keys are ignored (they are scheduler-specific metadata).
        """
        content = data.get("content") or json.dumps(
            {k: v for k, v in data.items() if k not in ("importance", "tags", "source")},
            default=str,
        )
        # Truncate to store limit before passing to create_unit
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "[TRUNCATED]"

        source = str(data.get("source", "scheduler"))
        importance = float(data.get("importance", 50.0))
        tags: list[str] = [str(t) for t in data.get("tags", [])]

        return await self.create_unit(
            content=content,
            source=source,
            importance=importance,
            tags=tags,
        )

    async def close(self) -> None:
        """Cleanup resources."""
        # ChromaDB PersistentClient auto-persists; no explicit close needed
        pass
