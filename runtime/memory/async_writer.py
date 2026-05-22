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

# Batch persist tunables — drainer collects up to BATCH_MAX items waiting at
# most BATCH_WINDOW_MS for the batch to fill, then hands the batch to
# memory_store.persist_units_batch() under a SINGLE write-lock acquisition.
# This is the fix for the Awarebot-flood wedge: previously every drainer
# acquired/released the write lock per item (500 acquisitions/scan), each
# of which raced against /chat and other synchronous writers.
DEFAULT_BATCH_MAX = int(os.getenv("NCL_ASYNC_WRITER_BATCH_MAX", "25"))
DEFAULT_BATCH_WINDOW_MS = int(os.getenv("NCL_ASYNC_WRITER_BATCH_WINDOW_MS", "100"))

# Model used for in-drainer LLM enrichment. SONNET, never Haiku.
SONNET_MODEL = "claude-sonnet-4-20250514"

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
        batch_max: int = DEFAULT_BATCH_MAX,
        batch_window_ms: int = DEFAULT_BATCH_WINDOW_MS,
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
            "avg_batch_size": 0.0,
            "batches_total": 0,
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
        self._batch_max = max(1, batch_max)
        self._batch_window_s = max(0.0, batch_window_ms / 1000.0)
        # Has memory_store.persist_units_batch? (Backwards-compat guard.)
        self._supports_batch = hasattr(memory_store, "persist_units_batch")
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
        """Pull → enrich → persist → mark done. Never crashes the pool.

        Batched mode (default when memory_store.persist_units_batch exists):
        - Block on first item
        - Greedily drain up to ``batch_max`` more items waiting at most
          ``batch_window_ms`` for the batch to fill
        - Run per-item enrichment concurrently (asyncio.gather)
        - Hand the finalized batch to persist_units_batch in ONE write-lock
          acquisition

        Under Awarebot flood (500 items): instead of 500 lock acquisitions
        we now take the lock ~20 times (500/25 batch_max), each lock-hold
        under 50ms. Hot-path /chat write now sees <1s of lock contention
        even at peak flood, vs >25s before.
        """
        log.debug(
            "[ASYNC_WRITER:%d] drainer started (batch_max=%d, window_ms=%d, batched=%s)",
            worker_id, self._batch_max, int(self._batch_window_s * 1000),
            self._supports_batch,
        )
        while True:
            # Block on the first item
            try:
                first = await self._queue.get()
            except asyncio.CancelledError:
                log.debug("[ASYNC_WRITER:%d] drainer cancelled", worker_id)
                return

            # Collect a batch (skipped entirely if batch_max==1 or no batch support)
            batch: list[WriteRequest] = [first]
            if self._supports_batch and self._batch_max > 1:
                deadline = time.monotonic() + self._batch_window_s
                while len(batch) < self._batch_max:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        # First try non-blocking — drain anything already queued
                        nxt = self._queue.get_nowait()
                        batch.append(nxt)
                    except asyncio.QueueEmpty:
                        # Wait up to the remaining window for one more
                        try:
                            nxt = await asyncio.wait_for(
                                self._queue.get(), timeout=remaining,
                            )
                            batch.append(nxt)
                        except asyncio.TimeoutError:
                            break
                        except asyncio.CancelledError:
                            # Push the partial batch back into DLQ-equivalent
                            # for retry on next start. For now, mark all done.
                            for _ in batch:
                                try:
                                    self._queue.task_done()
                                except ValueError:
                                    pass
                            raise

            t0 = time.monotonic()
            try:
                if self._supports_batch and len(batch) > 1:
                    await self._process_batch(batch, worker_id)
                else:
                    # Single-item path (also taken when persist_units_batch
                    # is missing on memory_store — backwards compat).
                    await self._process_one(batch[0], worker_id)
            except asyncio.CancelledError:
                # Mark all batch items done before unwinding
                for _ in batch:
                    try:
                        self._queue.task_done()
                    except ValueError:
                        pass
                raise
            except Exception as e:  # noqa: BLE001 - defensive catch-all
                # Catastrophic — _process_batch handles per-item DLQ itself;
                # this is the truly-unexpected case.
                log.error(
                    "[ASYNC_WRITER:%d] drainer caught unhandled: %s",
                    worker_id, e,
                )
                for req in batch:
                    self._stats["failed_total"] += 1
                    self._push_dlq(req, f"drainer_unhandled: {e}")
            finally:
                latency = time.monotonic() - t0
                cur = self._stats["avg_drain_latency_s"]
                self._stats["avg_drain_latency_s"] = (
                    cur + self._ema_alpha * (latency - cur)
                    if cur > 0 else latency
                )
                # Rolling avg batch size
                bs = float(len(batch))
                avg_bs = self._stats["avg_batch_size"]
                self._stats["avg_batch_size"] = (
                    avg_bs + self._ema_alpha * (bs - avg_bs)
                    if avg_bs > 0 else bs
                )
                self._stats["batches_total"] += 1
                self._stats["queue_size"] = self._queue.qsize()
                self._stats["dlq_size"] = len(self._dlq)
                for _ in batch:
                    try:
                        self._queue.task_done()
                    except ValueError:
                        pass  # already marked (race on shutdown)

    async def _process_one(self, req: WriteRequest, worker_id: int) -> None:
        """Single-item path — kept for backwards compatibility with stores
        that don't expose ``persist_units_batch``."""
        try:
            unit = await self._process(req)
            self._stats["drained_total"] += 1
            self._stats["last_drain_at"] = datetime.now(timezone.utc).isoformat()
            if req.callback:
                try:
                    req.callback(unit, None)
                except Exception as cb_e:
                    log.debug(
                        "[ASYNC_WRITER:%d] callback error: %s",
                        worker_id, cb_e,
                    )
        except Exception as e:  # noqa: BLE001
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

    async def _process_batch(
        self, batch: list[WriteRequest], worker_id: int
    ) -> None:
        """Batched path — enrich items concurrently, persist under one lock.

        Per-item failures during enrichment go to DLQ but do NOT abort the
        rest of the batch. Persist is all-or-nothing per the
        persist_units_batch durability contract.
        """
        # Step 1 — concurrent enrichment outside any lock
        enrich_tasks = [
            asyncio.create_task(self._enrich_only(req)) for req in batch
        ]
        enrich_results = await asyncio.gather(*enrich_tasks, return_exceptions=True)

        # Step 2 — split into persistable + failed
        to_persist: list[tuple[WriteRequest, "MemUnit"]] = []
        for req, result in zip(batch, enrich_results):
            if isinstance(result, BaseException):
                self._stats["failed_total"] += 1
                self._push_dlq(req, f"enrich_failed: {result}")
                log.debug(
                    "[ASYNC_WRITER:%d] enrich failed (source=%s): %s",
                    worker_id, req.source, result,
                )
                if req.callback:
                    try:
                        req.callback(None, result)
                    except Exception:
                        pass
                continue
            to_persist.append((req, result))

        if not to_persist:
            return

        # Step 3 — single-lock batch persist
        try:
            await self.memory_store.persist_units_batch(
                [u for _, u in to_persist]
            )
        except Exception as e:
            # Whole-batch failure — DLQ everything and let retry_dlq pick up
            log.warning(
                "[ASYNC_WRITER:%d] batch persist failed (n=%d): %s",
                worker_id, len(to_persist), e,
            )
            for req, _ in to_persist:
                self._stats["failed_total"] += 1
                self._push_dlq(req, f"batch_persist_failed: {e}")
                if req.callback:
                    try:
                        req.callback(None, e)
                    except Exception:
                        pass
            return

        # Step 4 — success bookkeeping + per-item callbacks
        self._stats["drained_total"] += len(to_persist)
        self._stats["last_drain_at"] = datetime.now(timezone.utc).isoformat()
        for req, unit in to_persist:
            if req.callback:
                try:
                    req.callback(unit, None)
                except Exception as cb_e:
                    log.debug(
                        "[ASYNC_WRITER:%d] callback error: %s",
                        worker_id, cb_e,
                    )

    async def _enrich_only(self, req: WriteRequest):
        """Run enrichment (PII redact + LLM scoring + entity extract) and
        build a MemUnit WITHOUT acquiring the write lock.

        Returns the constructed MemUnit ready for persist_units_batch.
        """
        # Reuse the existing enrichment chain
        await self._maybe_score(req)
        await self._maybe_extract_entities(req)
        return await self._build_unit(req)

    async def _build_unit(self, req: WriteRequest):
        """Construct a MemUnit from a WriteRequest without persisting.

        Mirrors the unit-construction logic in MemoryStore.create_unit so
        downstream consumers (decay, indexing, authority weighting) see
        identical fields.
        """
        # Lazy imports to avoid circular ref
        import uuid
        from ..ncl_brain.models import MemUnit
        from .pii_redactor import PIIRedactor
        from .authority import tier_for_source as _tier_for_source
        from .store import (
            MAX_CONTENT_LENGTH, LML_MEMORY_TYPES,
            DECAY_RATE_LML, DECAY_RATE_SML,
        )

        content = req.content or ""
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "[TRUNCATED]"

        # PII redaction (mirrors store.create_unit)
        pii_result = PIIRedactor.scan(content)
        pii_types: list[str] = []
        if pii_result.redaction_count > 0:
            content = pii_result.redacted_text
            pii_types = sorted({f["type"] for f in pii_result.findings})

        unit = MemUnit(
            unit_id=str(uuid.uuid4()),
            content=content,
            source=req.source,
            importance=min(100.0, max(0.0, req.importance)),
            tags=(req.tags or [])[:10],
        )

        # Authority tier stamping
        meta = getattr(unit, "metadata", None)
        if not isinstance(meta, dict):
            meta = {}
            unit.metadata = meta
        if "authority_tier" not in meta:
            meta["authority_tier"] = int(_tier_for_source(req.source))

        # PII audit record (fire-and-forget; doesn't gate persist)
        if pii_result.redaction_count > 0 and hasattr(
            self.memory_store, "_record_pii_redaction"
        ):
            try:
                await self.memory_store._record_pii_redaction(
                    unit_id=unit.unit_id,
                    source=req.source,
                    count=pii_result.redaction_count,
                    types_found=pii_types,
                )
            except Exception as e:
                log.debug("[ASYNC_WRITER] PII audit write failed: %s", e)

        unit.memory_type = req.memory_type
        if req.memory_type in LML_MEMORY_TYPES:
            unit.memory_tier = "LML"
            unit.decay_rate = DECAY_RATE_LML
        else:
            unit.memory_tier = "SML"
            unit.decay_rate = DECAY_RATE_SML

        # Entity attach (best-effort, mirrors create_unit post-step)
        if req.entities:
            try:
                unit.entities = sorted(set(req.entities))[:20]
            except Exception:
                pass

        return unit

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
