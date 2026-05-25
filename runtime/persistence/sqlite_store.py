"""
SqliteStore — pooled-connection SQLite wrapper for NCL.

Design goals:
    * WAL journal mode (concurrent readers, single writer)
    * Synchronous=NORMAL (good durability + perf balance)
    * Async-friendly: acquire(mode) context manager backed by a
      reader/writer lock (writer-preference). Concurrent readers may
      hold the lock simultaneously; writers run exclusively.
    * Idempotent schema migrations from runtime/persistence/schema/*.sql
    * Single shared DB at data/persistence/ncl.db (override NCL_SQLITE_PATH)

The store is intentionally minimal — it owns the connection pool, the
lock, and migration application. Domain code (cost_tracker, future
mandates store, etc.) writes SQL directly via `acquire()` rather than
building a heavy ORM on top.

Reader/writer lock (W4-11, 2026-05-23)
--------------------------------------
The original-original implementation serialised every operation — reads
included — through a single ``asyncio.Lock``. The W4-11 ``_RWLock``
admitted concurrent readers on a single connection but still pinned
every coroutine onto one ``sqlite3.Connection`` object (which is not
coroutine-safe), so reads still serialised at the GIL-released
``execute()`` boundary.

Connection pool (W10B-5, 2026-05-24)
------------------------------------
The store now holds:

    * ONE writer connection (``self._writer_conn``) guarded by the
      ``_RWLock`` for serialisation against itself and against migrations.
      ``execute_one`` / ``execute_many`` / ``apply_migrations`` route
      here and inherit the W10A-13 OperationalError retry semantics.
    * N reader connections in an ``asyncio.Queue`` (default 4,
      configurable via ``NCL_SQLITE_READ_POOL``). ``fetch_one`` /
      ``fetch_all`` pull a connection off the queue, run their query,
      and return it in ``finally``. SQLite WAL allows unlimited
      concurrent readers + one in-flight writer at the file level, so
      reads NEVER block on the writer lock.

``acquire("read")`` / ``acquire("write")`` retain the W4-11 RWLock
semantics so legacy callers that issue arbitrary SQL through the
context manager keep their consistency model. New code should prefer
``fetch_*`` (pool-routed) and ``execute_*`` (writer-routed) for the
parallelism win.

PRAGMAs (``journal_mode=WAL``, ``synchronous=NORMAL``,
``busy_timeout=5000``, ``foreign_keys=ON``) are applied to EVERY
connection on open — writer and every reader. Without per-connection
``journal_mode=WAL`` a reader can fall through into rollback-journal
mode and stall a concurrent writer.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Iterable, Optional, Sequence

log = logging.getLogger("ncl.persistence")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DEFAULT_DB_PATH = NCL_BASE / "data" / "persistence" / "ncl.db"
SCHEMA_DIR = Path(__file__).parent / "schema"

# W10B-5: read-only connection pool size. SQLite WAL supports many
# concurrent readers natively; 4 is sized for the ~4 hot fetch_* paths
# the Brain runs (memory recall, cost dashboard, mandate ledger,
# portfolio summary) and keeps the file-descriptor footprint trivial.
_DEFAULT_READ_POOL_SIZE = 4


def _read_pool_size() -> int:
    """Resolve pool size from env; clamp to >=1 to avoid empty queues."""
    raw = os.getenv("NCL_SQLITE_READ_POOL")
    if not raw:
        return _DEFAULT_READ_POOL_SIZE
    try:
        n = int(raw)
    except ValueError:
        log.warning(
            "[SQLITE] NCL_SQLITE_READ_POOL=%r is not an int — using default %d",
            raw,
            _DEFAULT_READ_POOL_SIZE,
        )
        return _DEFAULT_READ_POOL_SIZE
    return max(1, n)


# W10A-13: transient sqlite3.OperationalError retry schedule (in seconds).
# Three retry attempts (4 total tries: t=0, +0.1s, +0.5s, +2.0s) cover the
# overwhelming majority of "database is locked" / "disk I/O error" blips
# observed under the new triple double-write hook load (cost_tracker,
# brain mandate ledger, memory store). Anything that survives all four
# attempts is genuinely wedged and a stuck-checkpoint / disk-full alert.
_SQLITE_RETRY_DELAYS_S = (0.1, 0.5, 2.0)


def _is_retryable_sqlite_error(e: sqlite3.OperationalError) -> bool:
    """True for transient lock/disk errors worth retrying."""
    msg = str(e).lower()
    return ("database is locked" in msg) or ("disk i/o error" in msg)


def _ntfy_sqlite_exhausted(e: sqlite3.OperationalError) -> None:
    """Best-effort exhaustion alert. Import is local to avoid cycles."""
    try:
        from ..notifications.alert_dispatch import enqueue_alert

        enqueue_alert(
            title="SQLite write retry exhausted",
            body=str(e)[:200],
            priority="3",
            dedup_key="sqlite_retry_exhausted",
            source="persistence",
        )
    except Exception:
        # Never let alerting failures mask the underlying OperationalError.
        pass


class _RWLock:
    """
    Reader-many / writer-exclusive async lock with writer-preference.

    State
    -----
    * ``_readers_active`` (int) — count of currently-admitted readers
    * ``_writer_active`` (bool) — True while a writer holds the lock
    * ``_writers_waiting`` (int) — writers parked in ``acquire_write``

    All transitions happen under a single ``asyncio.Condition`` and
    every release issues ``notify_all`` so any predicate that may have
    flipped to True re-evaluates without a lost-wakeup window.

    Writer-preference rule
    ----------------------
    ``acquire_read`` blocks while ``_writer_active`` is True OR
    ``_writers_waiting`` > 0. A burst of readers can therefore never
    indefinitely delay a queued writer — the writer is guaranteed to
    drain ahead of the next reader cohort.
    """

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._readers_active: int = 0
        self._writer_active: bool = False
        self._writers_waiting: int = 0

    async def acquire_read(self) -> None:
        async with self._cond:
            # Writer-preference: park while a writer holds the lock OR
            # is queued ahead of us.
            await self._cond.wait_for(
                lambda: not self._writer_active and self._writers_waiting == 0
            )
            self._readers_active += 1

    async def release_read(self) -> None:
        async with self._cond:
            if self._readers_active > 0:
                self._readers_active -= 1
            # Notify so any queued writer can re-check
            # ``readers_active == 0 and not writer_active``.
            self._cond.notify_all()

    async def acquire_write(self) -> None:
        async with self._cond:
            self._writers_waiting += 1
            acquired = False
            try:
                # Wait for full drain: no active writer AND no readers.
                await self._cond.wait_for(
                    lambda: not self._writer_active and self._readers_active == 0
                )
                self._writer_active = True
                acquired = True
            finally:
                # Always decrement waiting count, even on cancellation,
                # so readers parked behind us don't deadlock.
                self._writers_waiting -= 1
                if not acquired:
                    # Wake everyone — our cancellation may have freed
                    # the writer-preference gate for queued readers.
                    self._cond.notify_all()

    async def release_write(self) -> None:
        async with self._cond:
            if self._writer_active:
                self._writer_active = False
            # Wake all — both queued writers (next in line) and readers
            # (writer-preference gate may now be open).
            self._cond.notify_all()

    # ── Introspection (tests / diagnostics) ──────────────────────────

    @property
    def readers_active(self) -> int:
        return self._readers_active

    @property
    def writer_active(self) -> bool:
        return self._writer_active

    @property
    def writers_waiting(self) -> int:
        return self._writers_waiting


class SqliteStore:
    """
    Thread-safe SQLite wrapper with a 1-writer + N-reader connection pool.

    SQLite handles multiple readers + one writer natively under WAL.
    The Python-side ``_RWLock`` continues to guard the legacy
    ``acquire(mode)`` context manager (which still serves the writer
    connection) so callers that issue arbitrary SQL keep their
    consistency model. ``fetch_*`` calls bypass the RWLock entirely
    and pull a dedicated read-only connection from an
    ``asyncio.Queue[sqlite3.Connection]`` so concurrent ``fetch_*``
    coroutines actually run in parallel inside SQLite as well — not
    just inside the Python lock.

    Usage:
        store = await get_store()
        async with store.acquire("write") as conn:
            conn.execute("INSERT INTO cost_ledger (...) VALUES (...)", row)
            conn.commit()

        async with store.acquire("read") as conn:
            cur = conn.execute("SELECT * FROM cost_ledger LIMIT 10")
            rows = cur.fetchall()

        # Bulk:
        await store.execute_many(
            "INSERT INTO cost_ledger (ts, date_utc, source, actual_cost_usd) VALUES (?, ?, ?, ?)",
            rows,
        )
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path: Path = Path(db_path or os.getenv("NCL_SQLITE_PATH") or DEFAULT_DB_PATH)
        # Reader/writer lock for runtime data access via ``acquire()``
        # and ``execute_*``. ``fetch_*`` bypass this and use the read
        # pool directly.
        self._rwlock = _RWLock()
        # Separate exclusive lock for lifecycle ops (open/close/migrations).
        # These mutate the connection slot itself and must not race against
        # active readers or writers.
        self._lifecycle_lock = asyncio.Lock()
        # W10B-5: one writer + N readers in a pool.
        self._writer_conn: Optional[sqlite3.Connection] = None
        self._read_pool_size: int = _read_pool_size()
        self._reader_pool: Optional[asyncio.Queue[sqlite3.Connection]] = None
        # Kept on the instance for diagnostics + clean shutdown.
        self._reader_conns: list[sqlite3.Connection] = []
        self._initialized: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _open_connection(self, *, read_only: bool = False) -> sqlite3.Connection:
        """
        Open a SQLite connection with the canonical pragmas.

        Args:
            read_only: when True, opens via the ``file:...?mode=ro`` URI so
                SQLite itself rejects any stray write attempt. The
                writer connection always opens read-write.

        PRAGMAs (applied to EVERY connection — writer and every pool
        reader):
            * ``journal_mode=WAL``      — concurrent readers + 1 writer
            * ``synchronous=NORMAL``    — fsync on checkpoint, ~3x write speedup
            * ``foreign_keys=ON``       — enforce FK constraints
            * ``busy_timeout=5000``     — 5s wait under contention
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if read_only:
            # URI form lets us pass mode=ro; cache=shared is intentionally
            # NOT set so each reader has its own SQLite connection state
            # (lock table position, statement cache, txn slot).
            conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro",
                uri=True,
                check_same_thread=False,
                isolation_level=None,
                timeout=30.0,
            )
        else:
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,  # autocommit OFF via explicit BEGIN/COMMIT
                timeout=30.0,
            )
        conn.row_factory = sqlite3.Row
        if read_only:
            # Read-only connections can't change the file-level journal
            # mode (no write privileges); the writer has already set it
            # to WAL. We only set session-scoped pragmas here.
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
        else:
            # WAL gives us concurrent reads while a write is in flight.
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL: fsync on checkpoint, not on every commit. Cuts write
            # latency ~3x with no real durability loss on a single-node Mac.
            conn.execute("PRAGMA synchronous=NORMAL")
            # Enforce FKs (we don't use them today but cheap to be safe).
            conn.execute("PRAGMA foreign_keys=ON")
            # Reasonable busy timeout — under WAL this is rarely hit but
            # keeps us safe if a long migration runs at the same time as
            # a writer.
            conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def initialize(self) -> None:
        """Open the connection pool and apply any pending schema migrations."""
        if self._initialized:
            return
        async with self._lifecycle_lock:
            if self._initialized:
                return
            # 1. Open the writer FIRST so it lays down the WAL files and
            #    creates the DB if it doesn't exist — readers opened with
            #    mode=ro against a non-existent file would otherwise fail.
            self._writer_conn = self._open_connection(read_only=False)
            self._ensure_migrations_table_unlocked()
            self._apply_migrations_unlocked()
            # 2. Open N read-only connections and seed the pool queue.
            self._reader_pool = asyncio.Queue(maxsize=self._read_pool_size)
            self._reader_conns = []
            for _ in range(self._read_pool_size):
                rc = self._open_connection(read_only=True)
                self._reader_conns.append(rc)
                self._reader_pool.put_nowait(rc)
            self._initialized = True
            log.info(
                "[SQLITE] Store initialized at %s "
                "(WAL, synchronous=NORMAL, busy_timeout=5000, read_pool=%d)",
                self._db_path,
                self._read_pool_size,
            )

    async def close(self) -> None:
        async with self._lifecycle_lock:
            # Tear down readers first — they hold no transactions worth
            # committing and closing them releases their lock-table slots.
            if self._reader_pool is not None:
                # Drain the queue so we know how many readers are idle
                # and can close them deterministically. Readers checked
                # out by an in-flight ``fetch_*`` call will leak their
                # connection close until the caller returns it; that's
                # acceptable because ``close()`` is a shutdown path.
                drained = 0
                while not self._reader_pool.empty():
                    try:
                        rc = self._reader_pool.get_nowait()
                    except asyncio.QueueEmpty:  # pragma: no cover - defensive
                        break
                    try:
                        rc.close()
                    except Exception:
                        pass
                    drained += 1
                self._reader_pool = None
            # Any reader objects not in the queue at close-time (e.g.
            # checked out by a coroutine that never returned) are still
            # tracked on ``self._reader_conns`` — close them too, with
            # best-effort error swallowing.
            for rc in self._reader_conns:
                try:
                    rc.close()
                except Exception:
                    pass
            self._reader_conns = []
            if self._writer_conn is not None:
                try:
                    self._writer_conn.commit()
                except Exception:
                    pass
                self._writer_conn.close()
                self._writer_conn = None
            self._initialized = False

    # ── Migrations ───────────────────────────────────────────────────

    def _ensure_migrations_table_unlocked(self) -> None:
        assert self._writer_conn is not None
        self._writer_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name       TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._writer_conn.commit()

    def _applied_migrations_unlocked(self) -> set[str]:
        assert self._writer_conn is not None
        cur = self._writer_conn.execute("SELECT name FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}

    def _apply_migrations_unlocked(self) -> list[str]:
        """
        Apply every *.sql file in SCHEMA_DIR (lex order) that hasn't been
        recorded in schema_migrations. Each file runs in its own transaction.

        Returns:
            List of migration names applied during this call (empty if up to date).
        """
        assert self._writer_conn is not None
        if not SCHEMA_DIR.exists():
            return []

        applied = self._applied_migrations_unlocked()
        files = sorted(SCHEMA_DIR.glob("*.sql"))
        newly_applied: list[str] = []

        for path in files:
            name = path.name
            if name in applied:
                continue
            sql = path.read_text()
            # NOTE: sqlite3's executescript() issues an implicit COMMIT
            # before running and does NOT participate in an outer txn.
            # We run the schema script, then atomically stamp the
            # migration row in its own statement. If the script throws,
            # we don't stamp — re-run will retry the file. Schema files
            # MUST be idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX
            # IF NOT EXISTS) to make partial-application retries safe.
            try:
                self._writer_conn.executescript(sql)
                self._writer_conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)",
                    (name,),
                )
                self._writer_conn.commit()
                newly_applied.append(name)
                log.info("[SQLITE] applied migration %s", name)
            except Exception as e:
                log.error("[SQLITE] migration %s failed: %s", name, e)
                raise

        return newly_applied

    async def apply_migrations(self) -> list[str]:
        """Public entry: idempotent — safe to call repeatedly."""
        await self.initialize()
        # Migrations mutate schema — run under exclusive write.
        await self._rwlock.acquire_write()
        try:
            return self._apply_migrations_unlocked()
        finally:
            await self._rwlock.release_write()

    async def applied_migrations(self) -> set[str]:
        await self.initialize()
        # Pure read of schema_migrations — readable concurrently.
        await self._rwlock.acquire_read()
        try:
            return self._applied_migrations_unlocked()
        finally:
            await self._rwlock.release_read()

    # ── Access ───────────────────────────────────────────────────────

    @asynccontextmanager
    async def acquire(self, mode: str = "write") -> AsyncIterator[sqlite3.Connection]:
        """
        Acquire the writer connection under the reader/writer lock.

        Args:
            mode: "read" admits concurrent readers; "write" is exclusive.
                  Default stays "write" for back-compat with callers
                  that pre-date the lock split (they may issue any SQL).

        Yields:
            The sqlite3.Connection. Callers run .execute()/.commit() directly.

        Notes:
            * Both "read" and "write" yield the **writer** connection so
              callers retain full SQL access (including DDL). The new
              read-only connection pool is reserved for the dedicated
              ``fetch_*`` entry points where we know the call is purely
              SELECT.
            * Readers MUST NOT call ``commit()`` / ``execute("INSERT ...")``
              / DDL via this code path either — the RWLock would not
              serialise that against a concurrent writer.
            * Writers see no other coroutine touching the connection, so
              they may run ``BEGIN``/``COMMIT``/``ROLLBACK`` freely.
        """
        if mode not in ("read", "write"):
            raise ValueError(f"mode must be 'read' or 'write', got {mode!r}")
        await self.initialize()
        if mode == "read":
            await self._rwlock.acquire_read()
            try:
                assert self._writer_conn is not None
                yield self._writer_conn
            finally:
                await self._rwlock.release_read()
        else:
            await self._rwlock.acquire_write()
            try:
                assert self._writer_conn is not None
                yield self._writer_conn
            finally:
                await self._rwlock.release_write()

    # ── Read-pool helpers (W10B-5) ───────────────────────────────────

    @asynccontextmanager
    async def _checkout_reader(self) -> AsyncIterator[sqlite3.Connection]:
        """
        Pull a read-only connection from the pool, return it in finally.

        Concurrent readers do NOT contend on the RWLock. SQLite's WAL
        already permits unlimited concurrent readers + one writer at the
        file level; the pool gives each in-flight ``fetch_*`` coroutine
        its own ``sqlite3.Connection`` (the C object is not coroutine-
        safe so a shared connection would serialise here anyway).

        The Queue blocks when all readers are checked out — callers wait
        rather than failing fast. With a default pool of 4 this never
        bites in practice; under genuinely-bursty load tune the pool
        via ``NCL_SQLITE_READ_POOL``.
        """
        await self.initialize()
        assert self._reader_pool is not None
        conn = await self._reader_pool.get()
        try:
            yield conn
        finally:
            # Always return the connection — even on cancellation /
            # exception — so the pool doesn't bleed slots.
            try:
                self._reader_pool.put_nowait(conn)
            except asyncio.QueueFull:  # pragma: no cover - pool never grows
                # Pool size is fixed at init time; we should never hit
                # this. Close the orphan rather than leak it.
                try:
                    conn.close()
                except Exception:
                    pass

    async def execute_one(
        self,
        sql: str,
        params: Sequence = (),
        *,
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """
        Run a single statement and (optionally) commit. WRITER.

        W10A-13: wraps the cursor call in a 4-try retry loop for transient
        ``sqlite3.OperationalError`` ("database is locked" / "disk I/O
        error"). Retry happens INSIDE the RWLock so we don't queue-jump
        other writers; the lock is held for the full duration of the
        retry schedule (max ~2.6s). Non-retryable OperationalErrors raise
        immediately; exhaustion fires a deduped ntfy and re-raises so
        callers still see the failure.
        """
        await self.initialize()
        await self._rwlock.acquire_write()
        try:
            assert self._writer_conn is not None
            conn = self._writer_conn

            def _do_execute() -> sqlite3.Cursor:
                # Runs in a worker thread — sync sqlite3 calls only.
                # W13 P0-4: was blocking the event loop on big writes.
                cur = conn.execute(sql, params)
                if commit:
                    conn.commit()
                return cur

            for attempt, delay in enumerate((0.0,) + _SQLITE_RETRY_DELAYS_S):
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    return await asyncio.to_thread(_do_execute)
                except sqlite3.OperationalError as e:
                    if _is_retryable_sqlite_error(e):
                        if attempt < len(_SQLITE_RETRY_DELAYS_S):
                            log.warning(
                                "[sqlite] %s — retry %d/%d",
                                e,
                                attempt + 1,
                                len(_SQLITE_RETRY_DELAYS_S),
                            )
                            continue
                        _ntfy_sqlite_exhausted(e)
                        raise
                    raise  # non-retryable OperationalError
            # Unreachable: loop either returns or raises.
            raise RuntimeError("sqlite retry loop exited without return")  # pragma: no cover
        finally:
            await self._rwlock.release_write()

    async def execute_many(
        self,
        sql: str,
        rows: Iterable[Sequence],
        *,
        commit: bool = True,
    ) -> int:
        """
        Run executemany() inside a single transaction. Returns rowcount. WRITER.

        W10A-13: same retry wrapper as ``execute_one``. ``rows`` is
        materialized to a list ONCE up front so each retry attempt
        replays the identical batch (an arbitrary iterator would be
        drained on the first attempt). Any partial transaction left
        behind by a locked BEGIN/executemany is rolled back before the
        next sleep so the connection is clean for the retry.
        """
        await self.initialize()
        # Materialize so retries can replay; cheap for the typical
        # ledger-batch sizes we see (hundreds of rows max).
        rows_list = list(rows)
        await self._rwlock.acquire_write()
        try:
            assert self._writer_conn is not None
            conn = self._writer_conn

            def _do_executemany() -> int:
                # Runs in a worker thread — sync sqlite3 calls only.
                # W13 P0-4: was blocking the event loop on bulk writes.
                conn.execute("BEGIN")
                cur = conn.executemany(sql, rows_list)
                if commit:
                    conn.execute("COMMIT")
                return cur.rowcount

            def _do_rollback() -> None:
                if conn.in_transaction:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.OperationalError:
                        # Rollback itself can fail under the same lock
                        # condition — best-effort.
                        pass

            for attempt, delay in enumerate((0.0,) + _SQLITE_RETRY_DELAYS_S):
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    return await asyncio.to_thread(_do_executemany)
                except sqlite3.OperationalError as e:
                    # Always clean up any half-open txn before deciding.
                    await asyncio.to_thread(_do_rollback)
                    if _is_retryable_sqlite_error(e):
                        if attempt < len(_SQLITE_RETRY_DELAYS_S):
                            log.warning(
                                "[sqlite] %s — retry %d/%d",
                                e,
                                attempt + 1,
                                len(_SQLITE_RETRY_DELAYS_S),
                            )
                            continue
                        _ntfy_sqlite_exhausted(e)
                        raise
                    raise  # non-retryable OperationalError
                except Exception:
                    # Non-OperationalError: original behaviour — rollback + re-raise.
                    await asyncio.to_thread(_do_rollback)
                    raise
            # Unreachable: loop either returns or raises.
            raise RuntimeError("sqlite retry loop exited without return")  # pragma: no cover
        finally:
            await self._rwlock.release_write()

    async def fetch_all(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        """
        Read a result set. READER (concurrent, pool-routed).

        W10B-5: routes through the read-only connection pool. Each
        in-flight ``fetch_all`` uses its own ``sqlite3.Connection`` —
        no RWLock contention, no blocking on the writer. Signature
        unchanged from the W4-11 implementation.

        W13 P0-4: the sync ``conn.execute()/cur.fetchall()`` pair runs
        off the event loop inside ``asyncio.to_thread`` so big result
        sets don't block other coroutines. The reader checkout itself
        stays async.
        """
        async with self._checkout_reader() as conn:
            def _do_fetch_all() -> list[sqlite3.Row]:
                cur = conn.execute(sql, params)
                return cur.fetchall()

            return await asyncio.to_thread(_do_fetch_all)

    async def fetch_one(self, sql: str, params: Sequence = ()) -> Optional[sqlite3.Row]:
        """
        Read a single row. READER (concurrent, pool-routed).

        W10B-5: see ``fetch_all`` — same pool semantics. Signature
        unchanged.

        W13 P0-4: sync sqlite call wrapped in ``asyncio.to_thread``.
        """
        async with self._checkout_reader() as conn:
            def _do_fetch_one() -> Optional[sqlite3.Row]:
                cur = conn.execute(sql, params)
                return cur.fetchone()

            return await asyncio.to_thread(_do_fetch_one)


# ── Singleton ────────────────────────────────────────────────────────

_store_instance: Optional[SqliteStore] = None
_store_lock = asyncio.Lock()


async def get_store(db_path: Optional[Path] = None) -> SqliteStore:
    """
    Get or create the singleton SqliteStore.

    The first caller wins on db_path — subsequent callers ignore the arg.
    Pass `db_path` only in tests; production code uses NCL_SQLITE_PATH.
    """
    global _store_instance
    async with _store_lock:
        if _store_instance is None:
            _store_instance = SqliteStore(db_path=db_path)
            await _store_instance.initialize()
        return _store_instance


async def _reset_singleton_for_tests() -> None:
    """Test helper — drops the singleton without closing it."""
    global _store_instance
    if _store_instance is not None:
        await _store_instance.close()
    _store_instance = None
