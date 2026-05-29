"""Memory system for NCL brain."""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiofiles
from pydantic import ValidationError


log = logging.getLogger("ncl.memory")

from ..config import flags  # noqa: E402
from ..ncl_brain.models import MemUnit  # noqa: E402
from .authority import tier_for_source as _tier_for_source  # noqa: E402
from .chroma_gc import delete_unit_embeddings  # noqa: E402
from .entity_extractor import extract_entities_and_relationships  # noqa: E402
from .pii_redactor import PIIRedactor  # noqa: E402
from .reflection import MemoryCurator, MemoryReflector  # noqa: E402


# Memory system constraints
MAX_CONTENT_LENGTH = 50_000  # Max characters per memory unit
MAX_TOTAL_UNITS = 25_000  # Max total memory units in store
# Audit 2026-05-22: bumped 10K → 25K to stop eviction thrash. Awarebot
# ingest rate (~568/20min) was way above dedup throughput (200/6h merges),
# so eviction was running every ~4s and burning CPU+IO for no benefit.
# Real fix is dedup throughput; this raises the ceiling in the meantime.
MAX_MEMORY_FILE_BYTES = 200 * 1024 * 1024  # 200 MB — trigger compaction above this

# Schema version stamped on every NEW MemUnit metadata bag at create_unit /
# persist_units_batch time (W4-15, 2026-05-23). Existing units are NOT
# back-migrated — readers should treat absence as schema_version=0. Bump
# this constant whenever the on-disk MemUnit shape gains/loses fields so
# future migrators can detect old records and rewrite them.
_UNITS_SCHEMA_VERSION = 1

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
DECAY_RATE_LML = (
    0.999  # Long-term Memory Layer: ~50% in 29 days (hourly basis: 0.999^24 ≈ 0.976/day)
)
DECAY_RATE_SML = 0.95  # Short-term Memory Layer: ~50% in ~14 days (daily basis)

# Memory types that auto-route to LML (slow decay)
LML_MEMORY_TYPES = {"semantic", "decision", "preference", "procedural"}
# Memory types that stay in SML (fast decay)
SML_MEMORY_TYPES = {"episodic", "signal"}


class MemoryStoreReadTimeout(Exception):  # noqa: N818
    """Raised when a reader could not acquire the rw-lock within the
    configured timeout (default 30s, env NCL_MEMORY_READ_TIMEOUT_S).

    Indicates that writers/readers ahead in the queue have been holding the
    lock too long. Callers should degrade gracefully (return empty results,
    cached values, or a 503) rather than blocking forever on /chat or the
    working-context loop.
    """


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

        # Sweep orphaned .tmp files left behind by atomic-write failures.
        # Prevents indefinite disk bloat (audit found 15M orphan).
        try:
            for p in self.data_dir.glob("*.tmp"):
                try:
                    p.unlink()
                    log.info("[store] cleared orphan tmp: %s", p.name)
                except Exception:
                    pass
        except Exception:
            pass

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
        self._readers = 0  # Active reader count
        self._writer_active = False  # True while a write is mutating
        self._writers_waiting = 0  # Queue length for writer-preference
        # Reader-acquisition timeout (seconds). If a reader has been parked
        # behind writers/readers longer than this, raise MemoryStoreReadTimeout
        # so the caller can degrade gracefully instead of hanging /chat or
        # the working-context loop. Tunable via env for ops.
        self._read_timeout_s: float = float(os.getenv("NCL_MEMORY_READ_TIMEOUT_S", "30.0"))
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
        # W4-15: stamp schema_version on every NEW write so future migrations
        # can detect pre-versioned records (treat absence as version 0).
        meta.setdefault("schema_version", _UNITS_SCHEMA_VERSION)

        # ── Wave 14W-C — Lane routing + write-time gate ───────────────────
        # Every unit gets a `lane` stamp at write-time, derived from the
        # source string (or caller-supplied kind via metadata["lane_kind"]).
        # The MEMORY_MANDATE §3 write-gate runs here — units that fail the
        # gate are NOT persisted (returns the unit object so callers don't
        # crash, but the unit has metadata["lane_gate_rejected"]=True and
        # never lands in JSONL/Chroma/BM25/KG). Disable via
        # NCL_LANE_MEMORY_GATE=0 if you need pass-through.
        try:
            from ..lane_router import (
                DatumKind as _DK,  # noqa: N814 — short alias for hot path
            )
            from ..lane_router import (
                route as _lane_route,
            )

            # Resolve optional kind hint
            _kind_hint = meta.get("lane_kind")
            _kind = None
            if _kind_hint:
                try:
                    _kind = _DK(_kind_hint) if isinstance(_kind_hint, str) else _kind_hint
                except (ValueError, KeyError):
                    _kind = None
            # Extract score hints from metadata for the gate
            _score = float(meta.get("composite_score", 0) or 0)
            _xsrc = int(meta.get("cross_source", 0) or 0)
            _decision = _lane_route(
                source=source,
                kind=_kind,
                importance=float(unit.importance or 0),
                score=_score,
                cross_source=_xsrc,
                authority_tier=int(meta.get("authority_tier", 0) or 0),
                tags=list(unit.tags or []),
                memory_type=str(unit.memory_type or memory_type or ""),
            )
            # Stamp the lane info on metadata so consumers can filter
            meta["lane"] = _decision.primary_lane.value
            if _decision.secondary_refs:
                meta["lane_refs"] = [ln.value for ln in _decision.secondary_refs]
            meta["lane_gate_passed"] = bool(_decision.memory_gate_passed)
            meta["lane_gate_reason"] = _decision.memory_gate_reason
            # GATE: if rejected, short-circuit before persist
            if not _decision.memory_gate_passed:
                meta["lane_gate_rejected"] = True
                log.debug(
                    "[MEMORY-GATE] DROP source=%s lane=%s reason=%s",
                    source,
                    _decision.primary_lane.value,
                    _decision.memory_gate_reason,
                )
                # Bump counter for observability if the store has stats
                if hasattr(self, "_stats"):
                    self._stats.setdefault("lane_gate_dropped", 0)
                    self._stats["lane_gate_dropped"] += 1
                # Return the un-persisted unit so callers don't crash —
                # they can inspect metadata["lane_gate_rejected"] if they
                # care, but most callers fire-and-forget so this is just
                # graceful degradation.
                return unit
        except Exception as e:
            # Lane routing is fail-safe: any error falls through to the
            # legacy path (write as before). Logged at debug so we don't
            # spam.
            log.debug("[MEMORY-GATE] lane_router skipped: %s", e)

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
        mem_type = getattr(unit, "memory_type", "episodic")
        if mem_type in LML_MEMORY_TYPES:
            unit.memory_tier = "LML"
            unit.decay_rate = DECAY_RATE_LML
        else:
            unit.memory_tier = "SML"
            unit.decay_rate = DECAY_RATE_SML

        # Optional: LLM importance scoring for high-value content
        # Only score if importance was set to default (50.0) — caller-specified importance takes precedence  # noqa: E501
        if importance == 50.0:
            try:
                from .importance_scorer import rule_based_score, score_memory

                # Use LLM scoring for content that rule-based scoring rates >= 7 (high-value)
                rule_pre_score = rule_based_score(content, source, tags)
                use_llm = rule_pre_score >= 7.0
                scoring = await score_memory(content, source, tags, use_llm=use_llm)
                unit.importance = min(100.0, max(0.0, scoring["final_score"]))
                if scoring.get("llm_score") is not None:
                    unit.llm_importance_score = scoring["llm_score"]
                # Use inferred memory_type if not explicitly set
                if not hasattr(unit, "_type_set_explicitly"):
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
            # Invalidate snapshot cache so next _load_all_units re-reads
            # (Wave-8 audit #8 / 2026-05-24).
            self._units_cache = None
        finally:
            self._release_write()

        # Index outside the write lock (ChromaDB has its own locking).
        # W10B-15: single batched ChromaDB upsert per collection instead of
        # N per-unit thread hops (~10-30x faster on 500-unit batches).
        try:
            await self.index_units(units)
        except Exception as e:
            log.debug(f"persist_units_batch: index_units failed: {e}")

        # SQLite units_index double-write — gated by NCL_UNITS_INDEX_SQLITE.
        # Same contract as _persist_unit's hook: outside the write lock,
        # never raises, silent failure with a one-shot warning.
        #
        # W10B-6 (2026-05-24): switched to try_write_async — each unit
        # is enqueued for the background drainer instead of fighting the
        # SqliteStore writer lock inline. Under Awarebot 500-signal
        # floods the drainer batches them into ~10 execute_many calls
        # (50 rows each) instead of 500 separate execute_one acquires.
        if flags.units_index_sqlite():
            hook = self._units_sqlite_hook()
            for unit in units:
                # try_write_async never raises — no need for the
                # per-unit guard the inline path required.
                await hook.try_write_async(unit)

        return len(units)

    async def _acquire_read(self) -> None:
        """Acquire a shared read lock.

        Writer-preference: if any writer is queued or active we park here so
        a stream of readers (Awarebot signal flood => semantic_search calls)
        can never starve a pending write. Multiple readers may hold the
        lock concurrently once admitted.

        Bounded wait: a reader stalled longer than ``self._read_timeout_s``
        (default 30s) raises :class:`MemoryStoreReadTimeout` so callers can
        degrade gracefully instead of hanging /chat or the working-context
        loop on a wedged writer.
        """
        timeout = self._read_timeout_s
        async with self._rw_cond:
            # Park while a writer is mutating OR is queued ahead of us.
            try:
                await asyncio.wait_for(
                    self._rw_cond.wait_for(
                        lambda: not self._writer_active and self._writers_waiting == 0
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                log.warning(
                    "[MEMORY] reader timed out after %.1fs "
                    "(writer_active=%s, writers_waiting=%d, readers=%d)",
                    timeout,
                    self._writer_active,
                    self._writers_waiting,
                    self._readers,
                )
                raise MemoryStoreReadTimeout(f"reader stalled >{timeout:.1f}s") from exc
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
        try:
            await self._acquire_read()
        except MemoryStoreReadTimeout:
            log.warning("[MEMORY] get_unit(%s) degraded: read-lock timeout", unit_id)
            return None
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
        # P1-B fast-path (2026-05-24): if the snapshot cache is fresh
        # (<10s) skip the read lock entirely so we don't queue behind
        # the Awarebot drainer's batch write. Under warm-start flood this
        # is what unblocks /memory/working-context/pin (which traverses
        # search_units via the working-context lock).
        units: Optional[list[MemUnit]] = None
        cache = getattr(self, "_units_cache", None)
        if cache is not None:
            cache_ts, cached_units = cache
            if (time.monotonic() - cache_ts) < self._UNITS_FAST_PATH_TTL_S:
                units = list(cached_units)
        if units is None:
            try:
                await self._acquire_read()
            except MemoryStoreReadTimeout:
                log.warning("[MEMORY] search_units degraded: read-lock timeout")
                # Last-ditch: serve the stale cache rather than empty
                # results (Wave-13 P1-B).
                snapshot = self._last_known_snapshot()
                return snapshot if snapshot is not None else []
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

    async def _search_units_via_sqlite_index(
        self,
        tags: Optional[list[str]] = None,
        importance_threshold: float = 0.0,
        days_back: Optional[int] = None,
        memory_type: Optional[str] = None,
        min_authority_tier: Optional[int] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[str]:
        """
        SQLite-backed fast path for filtered unit-id lookups (W4-14).

        This is the *index-only* sibling of ``search_units`` — it returns
        a list of ``unit_id`` strings that match the supplied filters by
        querying the ``units_index`` SQLite table instead of full-scanning
        the 200MB ``data/memory/units.jsonl``. Callers are expected to
        hydrate the bodies they actually need via the existing batch
        loader (``_load_units_batch``) — only a small set typically needs
        hydration on any given query, which is the whole point.

        Flag-gated: returns an empty list (no work, no error) unless
        ``NCL_UNITS_INDEX_SQLITE`` is set to ``"true"``. The existing
        ``search_units`` JSONL full-scan stays the canonical path and the
        fallback — this method does NOT replace it, it sits beside it
        until NATRIX flips the flag and the 18+ callers are retrofitted.

        Args mirror ``search_units`` with three additions:
            tags: AND-match on tags (JSON-string LIKE per tag).
            importance_threshold: ``importance >= threshold``.
            days_back: only units created in the past N days.
            memory_type: episodic / semantic / procedural / signal / decision / preference.
            min_authority_tier: ≥ NATRIX(100) / COUNCIL(80) / BRAIN(60) / CALENDAR(50) / LLM_SINGLE(40) / SCANNER(20) / RAW(10).
            source: exact-match on ``source`` column.
            limit: SQL LIMIT (None = no cap).

        Returns:
            List of unit_id strings sorted by importance DESC. Empty list
            when the flag is OFF or no rows match.
        """  # noqa: E501
        if not flags.units_index_sqlite():
            return []

        # Lazy import — keeps the heavy MemoryStore module free of a
        # hard dep on the persistence layer when the flag is off.
        try:
            from ..persistence import get_store as _get_sqlite_store
        except Exception as e:  # pragma: no cover - import safety
            log.warning("[UNITS_INDEX] SQLite path unavailable: %s", e)
            return []

        clauses: list[str] = []
        params: list = []

        if importance_threshold and importance_threshold > 0:
            clauses.append("importance >= ?")
            params.append(float(importance_threshold))

        if days_back is not None and days_back >= 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            clauses.append("created_at >= ?")
            params.append(cutoff)

        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)

        if min_authority_tier is not None:
            clauses.append("authority_tier >= ?")
            params.append(int(min_authority_tier))

        if source:
            clauses.append("source = ?")
            params.append(source)

        if tags:
            # Tags are stored as a compact JSON array string, e.g.
            # ["natrix","council"].  AND-match by LIKE on the
            # double-quoted tag — safe enough since tags are
            # alphanumerics + hyphens in NCL's content rules and the
            # double-quote scopes the match to the array element.
            for tag in tags:
                clauses.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

        sql = "SELECT unit_id FROM units_index"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY importance DESC"
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        try:
            sqlite_store = await _get_sqlite_store()
            rows = await sqlite_store.fetch_all(sql, tuple(params))
        except Exception as e:
            log.warning("[UNITS_INDEX] SQLite query failed: %s — caller should fall back", e)
            return []

        return [row["unit_id"] for row in rows]

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
                return {
                    "total_before": 0,
                    "total_after": 0,
                    "pruned": 0,
                    "merged": 0,
                    "clusters": 0,
                }

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

            # Phase 2: Cluster related units by tag overlap + content similarity
            #
            # Audit 2026-05-23 (W4-10): The previous nested loop was O(n²) on
            # active_units — at 25K units, that's 312M pairwise comparisons
            # inside the write lock, blocking every read for the duration.
            # We now use MinHash + LSH (datasketch) to bucket candidates in
            # O(n·log n) and only do the O(k) refinement inside each bucket.
            #
            # The MinHash sketches are pure functions of unit.content — no
            # mutation of the underlying units. We keep the build phase inside
            # the write lock because the snapshot semantics (no concurrent
            # writes can change active_units while we cluster) are easier to
            # reason about, and the CPU win is already enormous.
            #
            # Hard requirement (W8-A2 Q3, 2026-05-24): datasketch is now a
            # mandatory runtime dependency. The fallback below used to run an
            # O(n²) pairwise scan inside the write lock — at 25K active units
            # that's ~312M comparisons, which froze the event loop and was
            # the proximate cause of issue #91. We refuse to boot rather than
            # let that path execute silently. datasketch is pinned in
            # requirements.txt; if this assertion fires the runtime is
            # mis-installed.
            clustered: set[str] = set()

            try:
                from datasketch import MinHash, MinHashLSH  # type: ignore

                _have_datasketch = True
            except ImportError:
                _have_datasketch = False

            assert _have_datasketch, (
                "datasketch required for memory consolidation — "
                "install with: pip install datasketch>=1.6.0"
            )

            if _have_datasketch:
                # Build MinHash sketches for every active unit. Use whitespace
                # tokenization on lowercased content — matches the original
                # similarity heuristic (`unit.content.lower().split()`).
                _NUM_PERM = 64  # noqa: N806
                _LSH_THRESHOLD = 0.7  # Jaccard threshold ≈ 0.3 word overlap on  # noqa: N806
                # short bags; matches original 0.3 floor
                # tightly enough for our consolidation
                # purpose. (Jaccard vs min-overlap differ
                # but the LSH gives candidate buckets
                # only; final 0.3 min-overlap re-check
                # is done in the refinement step below.)
                lsh = MinHashLSH(threshold=_LSH_THRESHOLD, num_perm=_NUM_PERM)
                sketches: dict[str, MinHash] = {}
                words_by_id: dict[str, set[str]] = {}
                tags_by_id: dict[str, set[str]] = {}

                for unit in active_units:
                    words = set(unit.content.lower().split())
                    words_by_id[unit.unit_id] = words
                    tags_by_id[unit.unit_id] = set(unit.tags)
                    if not words:
                        continue
                    m = MinHash(num_perm=_NUM_PERM)
                    for w in words:
                        m.update(w.encode("utf-8", errors="replace"))
                    sketches[unit.unit_id] = m
                    # MinHashLSH requires unique keys; unit_id is unique.
                    try:
                        lsh.insert(unit.unit_id, m)
                    except ValueError:
                        # Already inserted (shouldn't happen — defensive).
                        pass

                # Walk active_units in original order. For each unclaimed
                # unit, query LSH for candidates and refine with the original
                # 2+ shared-tag + 0.3 min-overlap rule.
                for unit_a in active_units:
                    if unit_a.unit_id in clustered:
                        continue
                    tags_a = tags_by_id.get(unit_a.unit_id, set())
                    if not tags_a:
                        continue
                    sketch_a = sketches.get(unit_a.unit_id)
                    if sketch_a is None:
                        continue

                    candidates = lsh.query(sketch_a)
                    if not candidates:
                        continue

                    cluster = [unit_a]
                    clustered.add(unit_a.unit_id)
                    words_a = words_by_id[unit_a.unit_id]

                    for cand_id in candidates:
                        if cand_id == unit_a.unit_id or cand_id in clustered:
                            continue
                        tags_b = tags_by_id.get(cand_id, set())
                        if len(tags_a & tags_b) < 2:
                            continue
                        words_b = words_by_id.get(cand_id, set())
                        if not words_a or not words_b:
                            continue
                        similarity = len(words_a & words_b) / min(len(words_a), len(words_b))
                        if similarity < 0.3:
                            continue
                        # Find the actual unit object by id (one lookup per
                        # match is fine; LSH already pruned the candidate set).
                        unit_b = next(
                            (u for u in active_units if u.unit_id == cand_id),
                            None,
                        )
                        if unit_b is None:
                            continue
                        cluster.append(unit_b)
                        clustered.add(cand_id)

                    if len(cluster) >= 2:
                        clusters.append(cluster)
            # NOTE (W8-A2 Q3, 2026-05-24): the O(n²) fallback was removed.
            # The assert above guarantees we never reach a non-LSH branch.

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
                            part = part[len("consolidation:") :]
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
            log.info(
                f"Post-consolidation reindex: {reindex_result.get('indexed', 0)} units indexed"
            )
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
            curator = MemoryCurator(knowledge_graph=getattr(self, "_knowledge_graph", None))
        except Exception as e:
            log.warning(f"Reflection modules unavailable, falling back to basic consolidation: {e}")
            return await self.consolidate()

        await self._acquire_write()
        try:
            units = await self._load_all_units()
            if not units:
                return {
                    "total_before": 0,
                    "total_after": 0,
                    "reflection": {},
                    "curation": {},
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
                if not getattr(unit, "entities", None):
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
                log.info(
                    f"Post-consolidation-v2 reindex: {reindex_result.get('indexed', 0)} units indexed"  # noqa: E501
                )
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
                part = part[len("consolidation:") :]
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
                old_type = getattr(unit, "memory_type", "episodic")
                old_tier = getattr(unit, "memory_tier", "SML")
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
                elif any(
                    kw in content_lower
                    for kw in ["decided", "decision", "approved", "committed to", "mandate"]
                ):
                    new_type = "decision"
                elif any(kw in content_lower for kw in ["always ", "never ", "prefer", "dislike"]):
                    new_type = "preference"
                elif any(
                    kw in content_lower
                    for kw in ["workflow", "procedure", "how to", "step 1", "step 2"]
                ):
                    new_type = "procedural"
                elif any(
                    kw in content_lower
                    for kw in ["alert", "signal", "spike", "breaking", "surge", "crash"]
                ):
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
                log.info(
                    f"Memory type migration: {migrated} types reassigned, {promoted_lml} promoted to LML"  # noqa: E501
                )

            # Count final distribution
            type_counts = {}
            tier_counts = {"LML": 0, "SML": 0}
            for unit in units:
                mt = getattr(unit, "memory_type", "episodic")
                type_counts[mt] = type_counts.get(mt, 0) + 1
                tier = getattr(unit, "memory_tier", "SML")
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
                log.info(
                    f"Source cleanup: {sources_fixed} sources + {content_fixed} content fields fixed ({len(units)} units)"  # noqa: E501
                )
            return {
                "total_units": len(units),
                "sources_fixed": sources_fixed,
                "content_fixed": content_fixed,
            }
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
        tier = getattr(unit, "memory_tier", "SML")
        if tier == "LML":
            effective_rate = DECAY_RATE_LML
        else:
            effective_rate = DECAY_RATE_SML

        decayed = unit.importance * (effective_rate**days_since)
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
            file_size = self.memory_file.stat().st_size if self.memory_file.exists() else 0
        except OSError:
            file_size = 0

        # MemUnit JSONL lines avg ~1.5-2 KB. A conservative 800-byte/line
        # estimate keeps us safely on the slow path before real capacity.
        # 9,500 units * 800B = 7.6 MB — we slow-path scan once we cross
        # that threshold (5% under MAX_TOTAL_UNITS=10_000 cap).
        AVG_BYTES_PER_LINE = 800  # noqa: N806
        FAST_PATH_MAX_BYTES = int(MAX_TOTAL_UNITS * AVG_BYTES_PER_LINE * 0.95)  # noqa: N806
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
            to_evict = evictable[: max(1, len(units) - MAX_TOTAL_UNITS + 1)]

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
            # Invalidate snapshot cache after atomic rewrite
            # (Wave-8 audit #8 / 2026-05-24).
            self._units_cache = None
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
        # Invalidate snapshot cache so next _load_all_units re-reads
        # (Wave-8 audit #8 / 2026-05-24).
        self._units_cache = None

        # SQLite units_index double-write side-channel (2026-05-24).
        # W10B-1: routed through the unified DoubleWriteHook. The hook
        # owns the env-flag check (NCL_UNITS_INDEX_SQLITE), lazy
        # persistence import, compiled-once INSERT OR REPLACE SQL, and
        # warn-once flap suppression. NEVER raises — a SQLite outage
        # cannot block a memory write.
        #
        # W10B-6 (2026-05-24): switched to try_write_async to move the
        # SQLite writer-lock acquire OFF the JSONL hot path. The inline
        # try_write was serializing JSONL writes inside the MemoryStore
        # writer lock whenever the SqliteStore writer was busy. The
        # async variant enqueues + returns; a single background drainer
        # task batches up to 50 rows per execute_many acquire.
        await self._units_sqlite_hook().try_write_async(unit)

    async def _sqlite_write_unit(self, unit: MemUnit) -> None:
        """Mirror one MemUnit into the SQLite ``units_index`` table.

        W10B-1: kept as a thin compatibility wrapper around the unified
        DoubleWriteHook. Field mapping still matches
        ``scripts/migrate_units_index_to_sqlite.py`` so a migrated row
        and a live-double-written row are bit-identical (the burn-in
        verifier compares sha256 across both).
        """
        await self._units_sqlite_hook().try_write(unit)

    @staticmethod
    def _build_units_index_row(unit):
        """Map one MemUnit to the units_index column tuple.

        Returns ``None`` to signal "skip this unit" only if mapping
        catastrophically fails — for normal units this always returns a
        full row (matches pre-W10B-1 behaviour).
        """
        meta = unit.metadata if isinstance(getattr(unit, "metadata", None), dict) else {}
        tags = list(getattr(unit, "tags", []) or [])

        # Auth tier: prefer metadata.authority_tier, fall back to source-derived.
        # Tolerate string aliases (some old units stored the tier NAME instead
        # of the int — e.g. "scanner" → 20). RAW(10) is the safe fallback.
        _NAME_TO_TIER = {  # noqa: N806
            "natrix": 100,
            "council": 80,
            "brain": 60,
            "calendar": 50,
            "llm_single": 40,
            "llm": 40,
            "scanner": 20,
            "raw": 10,
        }
        _raw_auth = meta.get("authority_tier")
        auth: int = 10  # RAW fallback default
        if isinstance(_raw_auth, (int, float)):
            auth = int(_raw_auth)
        elif isinstance(_raw_auth, str):
            stripped = _raw_auth.strip().lower()
            if stripped.isdigit():
                auth = int(stripped)
            elif stripped in _NAME_TO_TIER:
                auth = _NAME_TO_TIER[stripped]
            else:
                # Unknown string — try source-derived next.
                _raw_auth = None
        if _raw_auth is None:
            try:
                from .authority import _tier_for_source

                derived = _tier_for_source(unit.source)
                if isinstance(derived, (int, float)):
                    auth = int(derived)
                elif isinstance(derived, str) and derived.strip().lower() in _NAME_TO_TIER:
                    auth = _NAME_TO_TIER[derived.strip().lower()]
            except Exception as _auth_err:
                # keep RAW(10) default
                log.warning(
                    "[store] authority-tier derivation swallowed (source=%s): %s",
                    getattr(unit, "source", "?"),
                    _auth_err,
                )

        # content_hash: sha256 of first 1KB (matches migration script).
        content_hash = None
        try:
            import hashlib as _hashlib

            text = str(unit.content or "")[:1000]
            content_hash = _hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        except Exception as _hash_err:
            log.warning("[store] content_hash compute swallowed: %s", _hash_err)

        def _iso(v):
            """Format a datetime to match the JSONL/migration on-disk form.

            Pydantic emits ``2026-05-24T17:14:38.751636Z`` (RFC 3339, ``Z``
            suffix). Python's bare ``str(datetime)`` emits
            ``2026-05-24 17:14:38.751636+00:00`` which the burn-in
            verifier sees as a DIFFERENT row. Normalizing to the Pydantic
            shape keeps live double-writes byte-identical with migrated
            rows.
            """
            if v is None:
                return None
            if isinstance(v, str):
                return v
            try:
                iso = v.isoformat()
                if iso.endswith("+00:00"):
                    iso = iso[:-6] + "Z"
                return iso
            except Exception:
                return str(v)

        return (
            unit.unit_id,
            content_hash,
            unit.source,
            getattr(unit, "memory_type", "episodic"),
            int(auth),
            float(getattr(unit, "importance", 0.0) or 0.0),
            _iso(getattr(unit, "created_at", None)),
            _iso(getattr(unit, "last_accessed", None)),
            json.dumps(tags, separators=(",", ":")) if tags else None,
            int(getattr(unit, "reinforcement_count", 0) or 0),
            float(getattr(unit, "decay_rate", 0.95) or 0.95),
            # Optional fields — best effort, may be None
            float(getattr(unit, "decay_score", 0.0)) if hasattr(unit, "decay_score") else None,
            meta.get("tier"),
            meta.get("chroma_collection"),
            meta.get("signal_id"),
            meta.get("fingerprint"),
        )

    def _units_sqlite_hook(self):
        """Lazily build (and cache) the DoubleWriteHook for units_index."""
        hook = getattr(self, "_units_dw_hook", None)
        if hook is not None:
            return hook
        from ..persistence import DoubleWriteHook

        hook = DoubleWriteHook(
            env_flag="NCL_UNITS_INDEX_SQLITE",
            table="units_index",
            columns=(
                "unit_id",
                "content_hash",
                "source",
                "memory_type",
                "authority_tier",
                "importance",
                "created_at",
                "last_accessed",
                "tags",
                "reinforcement_count",
                "decay_rate",
                "decay_score",
                "tier",
                "chroma_collection",
                "signal_id",
                "fingerprint",
            ),
            build_row=MemoryStore._build_units_index_row,
            conflict_strategy="replace",
            log_prefix="[units_index]",
        )
        self._units_dw_hook = hook
        return hook

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

    # ── Snapshot cache TTL (Wave-8 audit #8 / 2026-05-24) ────────────
    # 13K JSONL units × Pydantic-parse on EVERY caller ate ~200MB/min in
    # allocation churn. 30s TTL is short enough that working-context /
    # decay reads see new units fast, long enough to eliminate the
    # per-second hot path. Cache is invalidated on every write path
    # below (single + batch append).
    _UNITS_CACHE_TTL_S: float = 30.0
    # P1-B fast-path TTL (2026-05-24): under sustained writer flood the
    # 30s cache window plus reader-starvation produced /memory/timeline
    # and /memory/working-context/pin 30s-timeouts even though a fresh
    # snapshot was sitting in memory. Below this short TTL we serve the
    # cached snapshot WITHOUT acquiring the read lock at all — writers
    # never block readers on a hot cache hit.
    _UNITS_FAST_PATH_TTL_S: float = 10.0

    async def _load_all_units(self) -> list[MemUnit]:
        """
        Load all memory units from NDJSON file, deduplicated by unit_id.

        When the same unit_id appears multiple times (e.g. from append-only
        updates), the last occurrence wins — it has the most recent state.

        Wave-8 (2026-05-24): now backed by a 30s snapshot cache to avoid
        re-Pydantic-parsing 13K units on every call. Invalidated on write
        via ``self._units_cache = None`` in the JSONL append sites.

        Wave-13 P1-B (2026-05-24): on a hot cache hit (cache age < 10s)
        this method returns the cached snapshot WITHOUT acquiring the
        rw-lock. Under Awarebot warm-start flood the writer queue can
        block readers past the 30s timeout — but the in-memory snapshot
        was perfectly serviceable. Timeline + pin endpoints benefit
        directly. Cache invalidation contract is unchanged: every write
        path (``_persist_unit``, ``persist_units_batch``,
        ``_rewrite_units``) sets ``self._units_cache = None``, so the
        first stale-cache load after a write goes back through the
        normal full-scan path.

        Returns:
            List of unique MemUnits (defensive copy)
        """
        # Lazy cache init (we don't touch __init__ — A4 owns it; using
        # getattr keeps this edit self-contained).
        cache = getattr(self, "_units_cache", None)
        if cache is not None:
            cache_ts, cached_units = cache
            age = time.monotonic() - cache_ts
            # P1-B fast-path: hot cache hit, return without ever touching
            # the rw-lock. Saves /memory/timeline from blocking behind
            # the Awarebot drainer's batch write lock under flood.
            if age < self._UNITS_FAST_PATH_TTL_S:
                return list(cached_units)
            if age < self._UNITS_CACHE_TTL_S:
                # Defensive shallow copy — callers may mutate the list
                # (sort, filter in place) without poisoning the cache.
                return list(cached_units)

        seen: dict[str, MemUnit] = {}
        if not self.memory_file.exists():
            self._units_cache = (time.monotonic(), [])
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

        units = list(seen.values())
        self._units_cache = (time.monotonic(), units)
        return list(units)

    def _last_known_snapshot(self) -> Optional[list[MemUnit]]:
        """Return the most recent cached snapshot regardless of age.

        Used as a graceful-degrade lifeline by ``dashboard_bridge.get_timeline``
        when ``_load_all_units`` times out under a writer flood. Returns
        ``None`` if the cache has never been populated. Defensive shallow
        copy so callers can sort/filter without poisoning the cache.

        Wave-13 P1-B (2026-05-24).
        """
        cache = getattr(self, "_units_cache", None)
        if cache is None:
            return None
        try:
            _cache_ts, cached_units = cache
        except (TypeError, ValueError):
            return None
        return list(cached_units)

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
            "episodic_traces": len(
                [
                    u
                    for u in units
                    if getattr(u, "memory_type", "episodic") in ("episodic", "signal")
                ]
            ),
            "semantic_units": len(
                [
                    u
                    for u in units
                    if getattr(u, "memory_type", "episodic")
                    in ("semantic", "decision", "preference", "procedural")
                ]
            ),
            "by_type": {
                mt: len([u for u in units if getattr(u, "memory_type", "episodic") == mt])
                for mt in ("episodic", "semantic", "procedural", "signal", "decision", "preference")
            },
            "by_tier": {
                "LML": len([u for u in units if getattr(u, "memory_tier", "SML") == "LML"]),
                "SML": len([u for u in units if getattr(u, "memory_tier", "SML") == "SML"]),
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

            self._chroma_client = chromadb.PersistentClient(path=str(self.data_dir / "chromadb"))
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
            log.info(
                f"ChromaDB initialized with {len(self._chroma_collections)} typed collections at {self.data_dir / 'chromadb'}"  # noqa: E501
            )
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
            mem_type = getattr(unit, "memory_type", "episodic")
            collection = self._get_collection_for_type(mem_type)
            if not collection:
                collection = self._chroma_collections.get("default")
            if not collection:
                return
            await asyncio.to_thread(
                collection.upsert,
                ids=[unit.unit_id],
                documents=[unit.content],
                metadatas=[
                    {
                        "source": unit.source,
                        "importance": unit.importance,
                        "tags": ",".join(unit.tags),
                        "created_at": unit.created_at.isoformat(),
                        "memory_type": mem_type,
                        "memory_tier": getattr(unit, "memory_tier", "SML"),
                    }
                ],
            )
        except Exception as e:
            log.warning(f"Failed to index unit {unit.unit_id}: {e}")

    async def index_units(self, units: list[MemUnit]) -> None:
        """Batched variant of ``index_unit`` — groups by ChromaDB collection
        and issues ONE ``collection.upsert(ids=[...], documents=[...],
        metadatas=[...])`` call per collection.

        W10B-15 (2026-05-24): under Awarebot 500-signal floods the per-unit
        ``asyncio.to_thread(collection.upsert, ...)`` round-trip was the
        dominant cost in ``persist_units_batch`` (~15s for 500 units). One
        upsert per typed collection is ~10-30x faster because each thread
        hop also drags ChromaDB's internal write lock.

        BM25 + KG node creation are still per-unit — they're cheap and not
        trivially batched.
        """
        if not units:
            return
        if not self._init_vector_db():
            return
        # Group by collection object (multiple memory_types may map to the
        # same default-fallback collection).
        grouped: dict[int, tuple[object, list[str], list[str], list[dict]]] = {}
        for unit in units:
            mem_type = getattr(unit, "memory_type", "episodic")
            collection = self._get_collection_for_type(mem_type)
            if not collection:
                collection = self._chroma_collections.get("default")
            if not collection:
                continue
            key = id(collection)
            if key not in grouped:
                grouped[key] = (collection, [], [], [])
            _, ids, docs, metas = grouped[key]
            ids.append(unit.unit_id)
            docs.append(unit.content)
            metas.append(
                {
                    "source": unit.source,
                    "importance": unit.importance,
                    "tags": ",".join(unit.tags),
                    "created_at": unit.created_at.isoformat(),
                    "memory_type": mem_type,
                    "memory_tier": getattr(unit, "memory_tier", "SML"),
                }
            )
        # One thread hop + one upsert per collection.
        for collection, ids, docs, metas in grouped.values():
            if not ids:
                continue
            try:
                await asyncio.to_thread(
                    collection.upsert,
                    ids=ids,
                    documents=docs,
                    metadatas=metas,
                )
            except Exception as e:
                log.warning(
                    f"index_units: batch upsert failed for {len(ids)} units "
                    f"(collection={getattr(collection, 'name', '?')}): {e} — "
                    f"falling back to per-unit"
                )
                # Best-effort per-unit fallback so a single bad metadata
                # entry can't poison the whole batch.
                for uid, doc, meta in zip(ids, docs, metas):
                    try:
                        await asyncio.to_thread(
                            collection.upsert,
                            ids=[uid],
                            documents=[doc],
                            metadatas=[meta],
                        )
                    except Exception as ee:
                        log.warning(f"index_units: per-unit fallback failed for {uid}: {ee}")

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
                        (mt, self._get_collection_for_type(mt)) for mt in memory_types
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
                from .retrieval.bm25 import BM25Index as _BM25  # noqa: N814

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
