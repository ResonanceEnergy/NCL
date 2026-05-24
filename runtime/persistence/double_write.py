"""
Unified SQLite double-write hook (W10B-1, 2026-05-24).

Wave 9 D1: three SQLite double-write hooks (cost_tracker, brain mandates,
units_index) had drifted into three slightly different patterns. W10A-14
added a fourth (predictions_writer). This module collapses the four
hand-rolled hooks into ONE abstraction so:

  * env-flag check semantics are identical (read at call time so launchd
    .env values are always honoured),
  * lazy persistence import lives in one place,
  * INSERT OR REPLACE / OR IGNORE SQL is compiled once per (table,
    columns, strategy) triple,
  * the "warn once per outage, never raise" semantics is uniform across
    every call site,
  * SqliteStore's W10A-13 retry loop is reused automatically (we still
    call execute_one / execute_many on the store).

Public surface:

    DoubleWriteHook[T] — generic, single-row + batch entry points.

Each call site instantiates ONE hook at module import (or instance init)
and then calls ``await hook.try_write(entity)`` /
``await hook.try_write_many(entities)``. The hook returns a bool /
rowcount and NEVER raises.

W10A-4 pillar-enum-guard semantics are preserved by making ``build_row``
return ``None`` for rows that fail validation — the hook just skips them.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    Iterable,
    Literal,
    Optional,
    Sequence,
    TypeVar,
)

log = logging.getLogger("ncl.persistence.double_write")

T = TypeVar("T")

ConflictStrategy = Literal["replace", "ignore"]

# Compiled-SQL cache keyed by (table, tuple(columns), strategy). Sharing
# this across hook instances is safe — the resulting string is a pure
# function of its inputs.
_SQL_CACHE: dict[tuple[str, tuple[str, ...], ConflictStrategy], str] = {}


def _compile_insert_sql(
    table: str,
    columns: Sequence[str],
    strategy: ConflictStrategy,
) -> str:
    """Return a cached ``INSERT OR <strategy> INTO`` SQL string."""
    key = (table, tuple(columns), strategy)
    cached = _SQL_CACHE.get(key)
    if cached is not None:
        return cached
    col_list = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    verb = "REPLACE" if strategy == "replace" else "IGNORE"
    sql = f"INSERT OR {verb} INTO {table} ({col_list}) VALUES ({placeholders})"
    _SQL_CACHE[key] = sql
    return sql


class DoubleWriteHook(Generic[T]):
    """
    Flag-gated, fire-and-forget mirror of an in-memory / on-disk entity
    into a SQLite table.

    The hook owns:

      * The env-flag toggle (read fresh on every call so a launchd
        .env reload is honoured without a process restart).
      * Lazy acquisition of the SqliteStore singleton.
      * The compiled INSERT SQL (cached across hook instances).
      * A one-shot warning on the first backend failure (subsequent
        failures are silent until process restart — burn-in pattern).

    The caller owns:

      * ``build_row(entity) -> Optional[Sequence]`` — maps an entity to
        a positional tuple matching ``columns``. Returning ``None``
        signals "skip this entity" (e.g. W10A-4 pillar-enum guard).
        Exceptions raised inside build_row are caught + warned once
        like any other backend failure, so a malformed entity never
        kills the JSON write path.

    Behaviour invariants:

      * ``try_write`` / ``try_write_many`` NEVER raise.
      * When the env flag is OFF, both methods return immediately with
        ``False`` / ``0`` — no SQL is compiled, no store is acquired.
      * The hook holds NO reference to the entity after the write
        completes (no leak across long-running services).

    Example::

        _PRED_HOOK: DoubleWriteHook[dict] = DoubleWriteHook(
            env_flag="NCL_PREDICTIONS_SQLITE",
            table="predictions",
            columns=("id", "created_at", "topic", ...),
            build_row=_pred_to_row,
        )

        # Later, in the producer:
        await _PRED_HOOK.try_write(prediction_dict)
    """

    __slots__ = (
        "_env_flag",
        "_table",
        "_columns",
        "_build_row",
        "_strategy",
        "_log_prefix",
        "_sql",
        "_warned",
        # W10B-6: background-queue mode internals.
        "_queue",
        "_queue_maxsize",
        "_drain_batch_max",
        "_drainer_task",
        "_drainer_started",
        "_dropped_count",
    )

    def __init__(
        self,
        *,
        env_flag: str,
        table: str,
        columns: Sequence[str],
        build_row: Callable[[T], Optional[Sequence[Any]]],
        conflict_strategy: ConflictStrategy = "replace",
        log_prefix: Optional[str] = None,
        queue_maxsize: int = 10000,
        drain_batch_max: int = 50,
    ) -> None:
        if not columns:
            raise ValueError("DoubleWriteHook requires at least one column")
        self._env_flag = env_flag
        self._table = table
        self._columns = tuple(columns)
        self._build_row = build_row
        self._strategy: ConflictStrategy = conflict_strategy
        self._log_prefix = log_prefix or f"[{table}]"
        # Compile-once; cached globally too so identical hooks reuse the
        # same string.
        self._sql = _compile_insert_sql(self._table, self._columns, self._strategy)
        # One-shot guard so a persistent backend outage doesn't spam the
        # log on every call. Reset by process restart — matches the
        # pre-merge per-hook behaviour.
        self._warned: bool = False
        # W10B-6: background-queue mode. The queue is created lazily on
        # first try_write_async() call because we may be at module import
        # time when no event loop exists yet. ``_drain_batch_max`` caps
        # the per-acquire batch so a runaway backlog can't hold the
        # SqliteStore writer lock for too long; the drainer simply loops
        # and grabs the next batch on the next iteration.
        self._queue: Optional[asyncio.Queue[Sequence[Any]]] = None
        self._queue_maxsize = queue_maxsize
        self._drain_batch_max = drain_batch_max
        self._drainer_task: Optional[asyncio.Task[None]] = None
        self._drainer_started: bool = False
        self._dropped_count: int = 0

    # ── Introspection ────────────────────────────────────────────────

    @property
    def table(self) -> str:
        return self._table

    @property
    def env_flag(self) -> str:
        return self._env_flag

    @property
    def sql(self) -> str:
        """Compiled INSERT SQL — handy for tests + diagnostic output."""
        return self._sql

    def enabled(self) -> bool:
        """True iff the env flag is set to a truthy value RIGHT NOW.

        Read at call time so launchd-loaded .env edits take effect on
        the next call without a process restart — matches the
        cost_tracker / units_index / mandates / predictions semantics.
        """
        return os.getenv(self._env_flag, "false").lower() == "true"

    def reset_warning(self) -> None:
        """Re-arm the one-shot warning. For tests / explicit recovery."""
        self._warned = False

    # ── Write paths ──────────────────────────────────────────────────

    async def try_write(self, entity: T) -> bool:
        """Mirror a single entity into the configured table.

        Returns True on a successful INSERT, False on any no-op
        (flag off, build_row returned None, backend error). NEVER
        raises — every exception is caught and absorbed.
        """
        if not self.enabled():
            return False

        try:
            row = self._build_row(entity)
        except Exception as e:  # noqa: BLE001
            self._warn_once(f"build_row raised — skipping entity: {e}")
            return False

        if row is None:
            return False

        try:
            store = await self._acquire_store()
            if store is None:
                return False
            await store.execute_one(self._sql, tuple(row))
            return True
        except Exception as e:  # noqa: BLE001 — defensive on purpose
            self._warn_once(f"SQLite double-write failed (will keep trying silently): {e}")
            return False

    async def try_write_many(self, entities: Iterable[T]) -> int:
        """Mirror an iterable of entities in a single SQLite transaction.

        Entities whose ``build_row`` returns ``None`` are skipped (the
        W10A-4 pillar-enum guard pattern). Returns the number of rows
        that were submitted to ``execute_many``; 0 on any no-op (flag
        off, empty batch, backend error). NEVER raises.
        """
        if not self.enabled():
            return 0

        rows: list[Sequence[Any]] = []
        for entity in entities:
            try:
                row = self._build_row(entity)
            except Exception as e:  # noqa: BLE001
                # Don't kill the whole batch on a single bad entity; one
                # warning suffices (warn-once still in effect).
                self._warn_once(f"build_row raised for one entity in batch: {e}")
                continue
            if row is None:
                continue
            rows.append(tuple(row))

        if not rows:
            return 0

        try:
            store = await self._acquire_store()
            if store is None:
                return 0
            await store.execute_many(self._sql, rows)
            return len(rows)
        except Exception as e:  # noqa: BLE001 — defensive on purpose
            self._warn_once(f"SQLite double-write (batch) failed: {e}")
            return 0

    # ── Background-queue mode (W10B-6) ───────────────────────────────

    async def try_write_async(self, entity: T) -> bool:
        """Enqueue an entity for background SQLite mirroring.

        W10B-6: replaces the inline ``try_write`` on hot paths where the
        synchronous SqliteStore writer lock was back-pressuring the
        primary JSONL/JSON writer it was supposed to be a side-channel
        for. The single drainer task ``_drain_queue`` pulls batches of
        up to ``drain_batch_max`` rows and submits them via a single
        ``execute_many`` per loop, amortising the writer-lock acquire
        cost across the batch.

        Durability contract: SQLite mirror is best-effort
        eventually-consistent. JSONL (or equivalent source-of-truth)
        is the durable record. A process kill mid-drain loses whatever
        is still queued — by design.

        Returns:
            True if the row was enqueued, False on any no-op
            (flag off, build_row returned None, queue full, build_row
            raised). NEVER raises.
        """
        if not self.enabled():
            return False

        try:
            row = self._build_row(entity)
        except Exception as e:  # noqa: BLE001
            self._warn_once(f"build_row raised — skipping entity: {e}")
            return False

        if row is None:
            return False

        try:
            queue = self._ensure_queue_running()
        except RuntimeError as e:
            # No running event loop — fall back to inline write so we
            # don't silently drop the row. Tests that exercise the hook
            # outside an event loop hit this path.
            self._warn_once(f"no running event loop — falling back to inline: {e}")
            try:
                return await self.try_write(entity)
            except Exception:  # noqa: BLE001
                return False

        try:
            queue.put_nowait(tuple(row))
            return True
        except asyncio.QueueFull:
            # Queue is full — drop the row rather than block the caller
            # (defeats the whole purpose of the queue). Count drops so
            # the next drain loop can log how far behind we are.
            self._dropped_count += 1
            self._warn_once(
                f"async queue full (maxsize={self._queue_maxsize}) — "
                f"dropping row; SQLite mirror will be skewed until catch-up"
            )
            return False

    def _ensure_queue_running(self) -> "asyncio.Queue[Sequence[Any]]":
        """Lazily build the queue and start the drainer on first use.

        Must be called from inside a running event loop — raises
        ``RuntimeError`` otherwise.
        """
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._queue_maxsize)
        if not self._drainer_started or (
            self._drainer_task is not None and self._drainer_task.done()
        ):
            # asyncio.get_running_loop() raises RuntimeError if no loop.
            loop = asyncio.get_running_loop()
            self._drainer_task = loop.create_task(
                self._drain_queue(),
                name=f"double_write_drain[{self._table}]",
            )
            self._drainer_started = True
        return self._queue

    async def _drain_queue(self) -> None:
        """Single drainer: pulls batches of up to ``drain_batch_max`` rows
        and submits them via one ``execute_many`` per iteration.

        Loop semantics:
            * Block on ``queue.get()`` for the first row of each batch.
            * Drain any additional ready rows up to the batch cap with
              ``get_nowait`` (non-blocking).
            * Submit the batch under a single writer-lock acquire.
            * On backend failure: warn-once + sleep briefly + continue
              (rows are dropped — best-effort contract). The queue
              keeps filling in the background so we shed load naturally.
        """
        assert self._queue is not None
        while True:
            try:
                first = await self._queue.get()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._warn_once(f"drainer queue.get failed: {e}")
                await asyncio.sleep(0.5)
                continue

            batch: list[Sequence[Any]] = [first]
            # Greedy non-blocking drain up to the cap.
            while len(batch) < self._drain_batch_max:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            try:
                store = await self._acquire_store()
                if store is not None:
                    await store.execute_many(self._sql, batch)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._warn_once(
                    f"drainer execute_many failed (batch={len(batch)}): {e}"
                )
                # Brief backoff so we don't hot-loop against a stuck DB.
                await asyncio.sleep(0.25)
            finally:
                # Mark all items done so .join() (used in tests) works.
                for _ in batch:
                    try:
                        self._queue.task_done()
                    except ValueError:
                        # task_done() called more than queued — defensive.
                        break

    async def flush_queue(self, timeout: float = 5.0) -> bool:
        """Block until all pending rows have been drained (or timeout).

        Used by tests to assert eventual consistency. Returns True if
        the queue drained cleanly, False on timeout.
        """
        if self._queue is None:
            return True
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def queue_depth(self) -> int:
        """Current queued-but-not-yet-drained row count (diagnostics)."""
        if self._queue is None:
            return 0
        return self._queue.qsize()

    @property
    def dropped_count(self) -> int:
        """Number of rows dropped due to a full queue (diagnostics)."""
        return self._dropped_count

    async def stop_drainer(self) -> None:
        """Cancel the drainer task (test cleanup / shutdown)."""
        task = self._drainer_task
        if task is None or task.done():
            self._drainer_task = None
            self._drainer_started = False
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._drainer_task = None
        self._drainer_started = False

    # ── Direct execute (for non-INSERT statements like outcome UPDATE) ─

    async def execute_custom(
        self,
        sql: str,
        params: Sequence[Any],
    ) -> Optional[int]:
        """Run an arbitrary parameterized statement against the same store.

        Used by the predictions hook for the outcome-only UPDATE — same
        env flag, same warn-once, same lazy store. Returns the cursor's
        rowcount on success, or None on any no-op.
        """
        if not self.enabled():
            return None
        try:
            store = await self._acquire_store()
            if store is None:
                return None
            cur = await store.execute_one(sql, tuple(params))
            try:
                return cur.rowcount
            except Exception:
                return 0
        except Exception as e:  # noqa: BLE001 — defensive on purpose
            self._warn_once(f"SQLite custom-exec failed: {e}")
            return None

    # ── Internals ────────────────────────────────────────────────────

    async def _acquire_store(self):
        """Lazy SqliteStore acquisition.

        We do NOT cache the store on the hook — the persistence layer
        already memoizes the singleton, and re-binding it across test
        re-points (e.g. ``_reset_singleton_for_tests``) would break the
        existing mandates / units_index test fixtures.
        """
        try:
            from . import get_store  # local import — avoid cycles
        except Exception as e:  # noqa: BLE001
            self._warn_once(f"persistence module not importable: {e}")
            return None
        store = await get_store()
        return store

    def _warn_once(self, message: str) -> None:
        if self._warned:
            return
        log.warning("%s %s", self._log_prefix, message)
        self._warned = True


__all__ = ["DoubleWriteHook", "ConflictStrategy"]
