"""
Async Memory Write Queue (Fire-and-Forget)
==========================================

Mem0 2026 names the synchronous LLM-in-hot-path the "most common production
footgun" for ingest pipelines. Awarebot's signal ingest previously *blocked*
on Sonnet roundtrips (~500-1500ms each for importance scoring + entity
extraction). With 100+ signals per scan cycle that is multiple minutes of
wall-clock latency for what should be background work.

This module provides ``AsyncMemoryWriter`` — a bounded asyncio queue with a
configurable pool of drainer tasks that handle:

    1. PII redaction (sync, fast — Loop 10)
    2. LLM importance scoring (Sonnet, conditional)
    3. LLM entity extraction (Sonnet, conditional)
    4. ``memory_store.create_unit(...)`` persist
    5. Dead-letter capture on failure

Producers (Awarebot, council, /chat, etc.) call ``enqueue(WriteRequest)``
and return *immediately*. They never block on memory writes again.

Design rules:
    - Backpressure: drop OLDEST on full queue. Old hasn't been useful;
      newest signals carry the most situational value.
    - DLQ cap 500: ring-buffer semantics, oldest entry purged.
    - Drainer concurrency tunable via ``NCL_ASYNC_WRITER_CONCURRENCY``.
    - All Sonnet calls go through ``cost_tracker.check_budget(...)``.
      If the anthropic budget is exhausted the unit is still persisted
      *without* LLM augmentation — never block a write on cost gates.
    - Defensive — a drainer never crashes the pool; failures go to DLQ.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger("ncl.memory.async_writer")


# ── Tunables (env-overridable) ────────────────────────────────────────────
DEFAULT_MAX_QUEUE = int(os.getenv("NCL_ASYNC_WRITER_QUEUE_MAX", "5000"))
DEFAULT_CONCURRENCY = int(os.getenv("NCL_ASYNC_WRITER_CONCURRENCY", "4"))
DEFAULT_DLQ_CAP = int(os.getenv("NCL_ASYNC_WRITER_DLQ_CAP", "500"))

# Model used for in-drainer LLM enrichment. SONNET, never Haiku.
SONNET_MODEL = "claude-sonnet-4-6-20250514"

# Per-call cost estimate ($) — used for budget pre-checks against cost_tracker.
SONNET_PER_CALL_EST = 0.01

# Drainer-internal thresholds (matches existing memory_store conventions)
SCORING_DEFAULT_IMPORTANCE = 50.0   # `importance == 50.0` => unscored
SCORING_RULE_TRIGGER = 7.0          # rule score >= 7 => worth Sonnet pass
ENTITY_LLM_TRIGGER = 70.0           # importance >= 70 => worth Sonnet extract


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class WriteRequest:
    """A single fire-and-forget memory write."""

    content: str
    source: str
    importance: float = SCORING_DEFAULT_IMPORTANCE
    memory_type: str = "episodic"
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    enqueued_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Optional sync (non-async) callback fired AFTER the unit is persisted.
    # Signature: callback(unit_or_None, error_or_None) -> None
    callback: Optional[Callable] = None

    # Internal — bumped on each DLQ retry. Drop after MAX_ATTEMPTS.
    _attempts: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# WRITER
# ═══════════════════════════════════════════════════════════════════════════


class AsyncMemoryWriter:
    """Fire-and-forget memory write queue.

    Producers call ``enqueue(req)`` and return instantly.
    Drainer tasks dequeue, enrich, and persist.

    Lifecycle: ``start()`` → ``stop()``. Re-entrant ``start()`` is a no-op.
    """

    MAX_ATTEMPTS = 3  # DLQ retry budget per WriteRequest

    def __init__(
        self,
        memory_store,
        max_queue: int = DEFAULT_MAX_QUEUE,
        drainer_concurrency: int = DEFAULT_CONCURRENCY,
        dlq_cap: int = DEFAULT_DLQ_CAP,
    ) -> None:
        self.memory_store = memory_store
        self._queue: asyncio.Queue[WriteRequest] = asyncio.Queue(maxsize=max_queue)
        self._dlq: deque[dict] = deque(maxlen=dlq_cap)
        self._stats: dict[str, Any] = {
            "enqueued_total": 0,
            "drained_total": 0,
            "failed_total": 0,
            "queue_size": 0,
            "avg_drain_latency_s": 0.0,
            "llm_scoring_calls": 0,
            "llm_scoring_budget_skips": 0,
            "llm_entity_calls": 0,
            "llm_entity_budget_skips": 0,
            "dropped_oldest_total": 0,
            "dlq_size": 0,
            "started_at": None,
            "last_drain_at": None,
        }
        # Rolling exponential moving average of drain latency
        self._ema_alpha = 0.1
        self._drainer_concurrency = drainer_concurrency
        self._running = False
        self._drainer_tasks: list[asyncio.Task] = []

    # ── Producer API ─────────────────────────────────────────────────────

    async def enqueue(self, req: WriteRequest) -> None:
        """Fire-and-forget. Returns instantly. Drops oldest if full."""
        try:
            self._queue.put_nowait(req)
        except asyncio.QueueFull:
            # Backpressure: drop oldest (best-effort — another producer may
            # race us, but the queue's internal lock keeps it consistent).
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                self._stats["dropped_oldest_total"] += 1
                log.warning(
                    "[ASYNC_WRITER] queue full (%d) — dropped oldest from %s "
                    "(enqueued_at=%s)",
                    self._queue.maxsize, dropped.source, dropped.enqueued_at,
                )
            except asyncio.QueueEmpty:
                pass
            # Re-enqueue current request — must succeed now
            try:
                self._queue.put_nowait(req)
            except asyncio.QueueFull:
                # Pathological: another producer refilled the queue between
                # our get and our put. Push the *current* req into DLQ rather
                # than block. This is exceptional.
                self._push_dlq(req, "queue_full_after_drop")
                return
        self._stats["enqueued_total"] += 1
        self._stats["queue_size"] = self._queue.qsize()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn drainer task pool. Idempotent — second call is a no-op.

        Returns immediately after spawn; the drainers run forever until
        ``stop()``.
        """
        if self._running:
            log.debug("[ASYNC_WRITER] start() called while already running")
            return
        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()
        self._drainer_tasks = [
            asyncio.create_task(
                self._drainer(worker_id=i),
                name=f"async-writer-drainer-{i}",
            )
            for i in range(self._drainer_concurrency)
        ]
        log.info(
            "[ASYNC_WRITER] started %d drainer(s), queue_max=%d, dlq_cap=%d",
            self._drainer_concurrency, self._queue.maxsize, self._dlq.maxlen,
        )

    async def stop(self) -> None:
        """Drain remaining items (up to 5s grace) then cancel drainers."""
        if not self._running:
            return
        log.info(
            "[ASYNC_WRITER] stopping — draining %d remaining...",
            self._queue.qsize(),
        )
        self._running = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning(
                "[ASYNC_WRITER] drain timeout — %d still queued, cancelling",
                self._queue.qsize(),
            )
        for t in self._drainer_tasks:
            t.cancel()
        await asyncio.gather(*self._drainer_tasks, return_exceptions=True)
        self._drainer_tasks = []
        log.info("[ASYNC_WRITER] stopped")

    # ── Drainer ──────────────────────────────────────────────────────────

    async def _drainer(self, worker_id: int) -> None:
        """Pull → enrich → persist → mark done. Never crashes the pool."""
        log.debug("[ASYNC_WRITER:%d] drainer started", worker_id)
        while True:
            try:
                req = await self._queue.get()
            except asyncio.CancelledError:
                log.debug("[ASYNC_WRITER:%d] drainer cancelled", worker_id)
                return
            t0 = time.monotonic()
            try:
                unit = await self._process(req)
                self._stats["drained_total"] += 1
                self._stats["last_drain_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                if req.callback:
                    try:
                        req.callback(unit, None)
                    except Exception as cb_e:
                        log.debug(
                            "[ASYNC_WRITER:%d] callback error: %s",
                            worker_id, cb_e,
                        )
            except asyncio.CancelledError:
                # Re-raise so the task actually unwinds.
                self._queue.task_done()
                raise
            except Exception as e:  # noqa: BLE001 - defensive catch-all
                self._stats["failed_total"] += 1
                self._push_dlq(req, str(e))
                log.warning(
                    "[ASYNC_WRITER:%d] drain failed (source=%s): %s",
                    worker_id, req.source, e,
                )
                if req.callback:
                    try:
                        req.callback(None, e)
                    except Exception:
                        pass
            finally:
                latency = time.monotonic() - t0
                cur = self._stats["avg_drain_latency_s"]
                self._stats["avg_drain_latency_s"] = (
                    cur + self._ema_alpha * (latency - cur)
                    if cur > 0 else latency
                )
                self._stats["queue_size"] = self._queue.qsize()
                self._stats["dlq_size"] = len(self._dlq)
                try:
                    self._queue.task_done()
                except ValueError:
                    pass  # already marked (race on shutdown)

    # ── Drainer steps ────────────────────────────────────────────────────

    async def _process(self, req: WriteRequest):
        """Enrich + persist a single WriteRequest.

        PII redaction is performed inside ``memory_store.create_unit`` (see
        store.py — it runs PIIRedactor.scan unconditionally before persist),
        so we do NOT duplicate it here. The contract change is that the
        EXPENSIVE steps (Sonnet scoring + extraction) now run *before*
        create_unit, and create_unit's own optional LLM-scoring branch
        becomes a no-op because we pass an explicit ``importance`` !=
        SCORING_DEFAULT_IMPORTANCE.
        """
        # Step 1 — LLM importance scoring (only when default + rule-worthy)
        await self._maybe_score(req)

        # Step 2 — LLM entity extraction (only when importance >= 70)
        await self._maybe_extract_entities(req)

        # Step 3 — persist
        unit = await self.memory_store.create_unit(
            content=req.content,
            source=req.source,
            importance=req.importance,
            tags=req.tags[:10] if req.tags else [],
            memory_type=req.memory_type,
        )

        # Step 4 — attach entities to the persisted unit (best effort)
        if req.entities and unit is not None:
            try:
                # Dedup, cap at 20
                merged = sorted(set(req.entities))[:20]
                unit.entities = merged
                if hasattr(self.memory_store, "index_unit"):
                    # index_unit is the path that flushes to ChromaDB
                    await self.memory_store.index_unit(unit)
            except Exception as e:
                log.debug("[ASYNC_WRITER] entity attach failed: %s", e)

        return unit

    async def _maybe_score(self, req: WriteRequest) -> None:
        """Run Sonnet importance scoring when criteria met.

        Criteria: ``importance == 50.0`` (caller didn't override) AND the
        cheap rule-based scorer rates content >= 7. Budget-gated.
        """
        if req.importance != SCORING_DEFAULT_IMPORTANCE:
            return

        # Cheap rule-based pre-check (no LLM, no API call)
        try:
            from .importance_scorer import rule_based_score
            rule_score = rule_based_score(req.content, req.source, req.tags)
        except Exception as e:
            log.debug("[ASYNC_WRITER] rule_based_score failed: %s", e)
            return

        if rule_score < SCORING_RULE_TRIGGER:
            # Not high-value — use the rule score (1-10 → 0-100 scale)
            req.importance = max(0.0, min(100.0, rule_score * 10.0))
            return

        # Budget gate — never block a write because the cost gate is closed
        try:
            from ..cost_tracker import check_budget
            if not await check_budget("anthropic", SONNET_PER_CALL_EST):
                self._stats["llm_scoring_budget_skips"] += 1
                req.importance = max(0.0, min(100.0, rule_score * 10.0))
                return
        except Exception as e:
            log.debug("[ASYNC_WRITER] budget check failed (allow): %s", e)

        try:
            from .importance_scorer import score_memory
            scoring = await score_memory(
                req.content, req.source, req.tags,
                use_llm=True, model=SONNET_MODEL,
            )
            self._stats["llm_scoring_calls"] += 1
            req.importance = max(0.0, min(100.0, scoring["final_score"]))
            inferred = scoring.get("memory_type")
            if inferred and inferred != "episodic":
                req.memory_type = inferred
        except TypeError:
            # Backward compat: score_memory without model kwarg
            try:
                from .importance_scorer import score_memory
                scoring = await score_memory(
                    req.content, req.source, req.tags, use_llm=True,
                )
                self._stats["llm_scoring_calls"] += 1
                req.importance = max(0.0, min(100.0, scoring["final_score"]))
            except Exception as e:
                log.debug("[ASYNC_WRITER] score_memory fallback failed: %s", e)
        except Exception as e:
            log.debug("[ASYNC_WRITER] score_memory failed: %s", e)

    async def _maybe_extract_entities(self, req: WriteRequest) -> None:
        """Run Sonnet entity extraction when importance >= 70."""
        if req.importance < ENTITY_LLM_TRIGGER:
            return

        try:
            from ..cost_tracker import check_budget
            if not await check_budget("anthropic", SONNET_PER_CALL_EST):
                self._stats["llm_entity_budget_skips"] += 1
                return
        except Exception:
            pass  # allow through

        try:
            from .entity_extractor import extract_entities_and_relationships
            try:
                result = await extract_entities_and_relationships(
                    req.content, req.source, use_llm=True, model=SONNET_MODEL,
                )
            except TypeError:
                # Backward compat
                result = await extract_entities_and_relationships(
                    req.content, req.source, use_llm=True,
                )
            self._stats["llm_entity_calls"] += 1
            new_ents = result.get("entities", []) if isinstance(result, dict) else []
            if new_ents:
                req.entities = sorted(set(req.entities) | set(new_ents))[:20]
        except Exception as e:
            log.debug("[ASYNC_WRITER] entity extract failed: %s", e)

    # ── DLQ ──────────────────────────────────────────────────────────────

    def _push_dlq(self, req: WriteRequest, reason: str) -> None:
        """Append a failure to the DLQ (ring-buffer)."""
        self._dlq.append({
            "source": req.source,
            "content_preview": (req.content or "")[:160],
            "importance": req.importance,
            "memory_type": req.memory_type,
            "tags": list(req.tags or [])[:10],
            "entities": list(req.entities or [])[:10],
            "metadata": dict(req.metadata or {}),
            "enqueued_at": req.enqueued_at,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "attempts": req._attempts,
        })
        self._stats["dlq_size"] = len(self._dlq)

    async def retry_dlq(self) -> int:
        """Re-enqueue all DLQ entries that haven't exhausted MAX_ATTEMPTS.

        Returns the number requeued. Exhausted entries stay in DLQ as a
        permanent record.
        """
        requeued = 0
        keep: list[dict] = []
        while self._dlq:
            entry = self._dlq.popleft()
            attempts = entry.get("attempts", 0) + 1
            if attempts >= self.MAX_ATTEMPTS:
                entry["attempts"] = attempts
                entry["status"] = "exhausted"
                keep.append(entry)
                continue
            req = WriteRequest(
                content=entry.get("content_preview", ""),
                source=entry.get("source", "dlq_retry"),
                importance=entry.get("importance", SCORING_DEFAULT_IMPORTANCE),
                memory_type=entry.get("memory_type", "episodic"),
                tags=list(entry.get("tags", []) or []),
                entities=list(entry.get("entities", []) or []),
                metadata=dict(entry.get("metadata", {}) or {}),
            )
            req._attempts = attempts
            await self.enqueue(req)
            requeued += 1
        # Re-insert exhausted entries (they will be at the right of the ring)
        for e in keep:
            self._dlq.append(e)
        self._stats["dlq_size"] = len(self._dlq)
        return requeued

    # ── Observability ────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Snapshot of writer health stats."""
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "queue_max": self._queue.maxsize,
            "dlq_size": len(self._dlq),
            "dlq_cap": self._dlq.maxlen,
            "drainer_concurrency": self._drainer_concurrency,
            "running": self._running,
            "model": SONNET_MODEL,
        }

    def get_dlq(self, limit: int = 50) -> list[dict]:
        """Most-recent N DLQ entries (newest first)."""
        if limit <= 0:
            return []
        # deque slicing isn't supported; convert.
        items = list(self._dlq)
        items.reverse()
        return items[:limit]


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON ACCESSOR
# ═══════════════════════════════════════════════════════════════════════════

_writer_singleton: Optional[AsyncMemoryWriter] = None


def get_async_writer() -> AsyncMemoryWriter:
    """Return the singleton. Raises if ``init_async_writer`` hasn't run."""
    global _writer_singleton
    if _writer_singleton is None:
        raise RuntimeError(
            "AsyncMemoryWriter not initialized — "
            "call init_async_writer(memory_store) first"
        )
    return _writer_singleton


def init_async_writer(memory_store, **kwargs) -> AsyncMemoryWriter:
    """Construct (or reuse) the singleton writer.

    Safe to call multiple times — returns the existing instance if already
    initialized. Pass ``force=True`` to replace.
    """
    global _writer_singleton
    force = kwargs.pop("force", False)
    if _writer_singleton is not None and not force:
        return _writer_singleton
    _writer_singleton = AsyncMemoryWriter(memory_store, **kwargs)
    return _writer_singleton


def _reset_singleton_for_tests() -> None:
    """Test helper — DO NOT use in production code."""
    global _writer_singleton
    _writer_singleton = None
