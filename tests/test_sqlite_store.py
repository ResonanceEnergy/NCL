"""
Tests for runtime/persistence/sqlite_store.py
"""
from __future__ import annotations

import asyncio
import json  # noqa: F401
import time
from pathlib import Path

import pytest

from runtime.persistence.sqlite_store import SqliteStore, _RWLock


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "ncl_test.db"


# ── 1. DB file is created on first use ───────────────────────────────

@pytest.mark.asyncio
async def test_sqlite_store_creates_db_file(tmp_db: Path):
    assert not tmp_db.exists()
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()
    assert tmp_db.exists(), "DB file should be created at initialize()"
    # WAL writes the actual data to <db>-wal during a transaction; ensure
    # the journal file shows up after a write.
    await store.execute_one("CREATE TABLE IF NOT EXISTS smoke (id INTEGER)")
    await store.execute_one("INSERT INTO smoke (id) VALUES (1)")
    # The -wal file lives alongside the db once a write has happened.
    wal = tmp_db.with_name(tmp_db.name + "-wal")
    assert wal.exists(), "WAL file should exist after a write under journal_mode=WAL"
    await store.close()


# ── 2. apply_migrations is idempotent ────────────────────────────────

@pytest.mark.asyncio
async def test_apply_migrations_idempotent(tmp_db: Path):
    store = SqliteStore(db_path=tmp_db)
    first = await store.apply_migrations()
    second = await store.apply_migrations()

    # First call should have applied SOMETHING (cost_ledger.sql at minimum
    # since it ships with the repo). Second call must apply NOTHING.
    assert isinstance(first, list)
    assert second == [], f"second apply_migrations() should be a no-op, got {second}"

    # The cost_ledger table must exist after either call.
    row = await store.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cost_ledger'"
    )
    assert row is not None, "cost_ledger table should be present after migrations"

    await store.close()


# ── 3. Concurrent writes — all rows persist ──────────────────────────

@pytest.mark.asyncio
async def test_concurrent_writes(tmp_db: Path):
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()

    async def writer(i: int) -> None:
        await store.execute_one(
            """
            INSERT INTO cost_ledger
                (ts, date_utc, source, purpose, actual_cost_usd)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"2026-05-23T00:00:{i:02d}", "2026-05-23", f"src{i}", "test", 0.01 * i),
        )

    await asyncio.gather(*(writer(i) for i in range(10)))

    rows = await store.fetch_all("SELECT * FROM cost_ledger ORDER BY id")
    assert len(rows) == 10, f"expected 10 rows after 10 concurrent writes, got {len(rows)}"
    assert {r["source"] for r in rows} == {f"src{i}" for i in range(10)}

    await store.close()


# ── 4. schema_migrations table is populated ──────────────────────────

@pytest.mark.asyncio
async def test_schema_migration_appears_in_schema_migrations_table(tmp_db: Path):
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()

    applied = await store.applied_migrations()
    assert "cost_ledger.sql" in applied, (
        f"cost_ledger.sql should be in schema_migrations, got {applied}"
    )

    # Verify the row really lives in the table (not just the in-memory set).
    row = await store.fetch_one(
        "SELECT name, applied_at FROM schema_migrations WHERE name = ?",
        ("cost_ledger.sql",),
    )
    assert row is not None
    assert row["name"] == "cost_ledger.sql"
    assert row["applied_at"]  # non-empty timestamp

    await store.close()


# ── Bonus: indexes from the schema are actually created ──────────────

@pytest.mark.asyncio
async def test_cost_ledger_indexes_present(tmp_db: Path):
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()
    rows = await store.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='cost_ledger'"
    )
    names = {r["name"] for r in rows}
    assert "idx_cost_ledger_date" in names
    assert "idx_cost_ledger_source" in names
    assert "idx_cost_ledger_date_source" in names
    await store.close()


# ── Reader/Writer lock concurrency (W4-11, 2026-05-23) ───────────────
#
# These tests verify that the Python-side lock split actually admits
# concurrent readers. The asserts use `_RWLock` introspection plus
# wall-clock timing measured around `asyncio.sleep` markers inside the
# `acquire()` context manager — the sleep simulates an I/O-bound query
# and lets us prove that readers genuinely overlap (rather than
# serialising). Writer-preference is verified by observing completion
# order across a reader-writer-reader sandwich.


SLEEP_INSIDE_LOCK = 0.10  # seconds — long enough to dwarf scheduler jitter


@pytest.mark.asyncio
async def test_concurrent_readers_dont_block_each_other(tmp_db: Path):
    """
    10 readers issued via asyncio.gather should complete in roughly the
    time of a *single* reader, not 10x. We simulate the query body with
    `asyncio.sleep` so the test is decoupled from sqlite3's
    GIL-blocking execute() and from disk speed — it measures the lock,
    which is what we actually changed.
    """
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()

    max_overlap_seen: list[int] = [0]

    async def reader(i: int) -> int:
        async with store.acquire("read"):
            # Track peak concurrent readers via the lock's own counter.
            n = store._rwlock.readers_active
            if n > max_overlap_seen[0]:
                max_overlap_seen[0] = n
            await asyncio.sleep(SLEEP_INSIDE_LOCK)
            return i

    t0 = time.perf_counter()
    results = await asyncio.gather(*(reader(i) for i in range(10)))
    elapsed = time.perf_counter() - t0

    # Sanity — every reader ran.
    assert sorted(results) == list(range(10))

    # 10 readers serialised would take ~10 * SLEEP_INSIDE_LOCK = 1.0s.
    # Concurrent readers should finish in well under 3x a single sleep
    # (allow generous slack for scheduler jitter and test-runner noise).
    assert elapsed < SLEEP_INSIDE_LOCK * 3, (
        f"10 concurrent readers took {elapsed:.3f}s — expected < "
        f"{SLEEP_INSIDE_LOCK * 3:.3f}s. Lock is still serialising reads."
    )

    # At some point during the gather, the readers_active counter must
    # have exceeded 1 — that's the whole point of the split.
    assert max_overlap_seen[0] > 1, (
        f"max concurrent readers observed was {max_overlap_seen[0]} — "
        f"readers were not actually overlapping"
    )

    await store.close()


@pytest.mark.asyncio
async def test_writer_blocks_readers(tmp_db: Path):
    """
    A slow writer (sleeps inside the write context) must block any
    reader that starts after the writer acquired the lock. We measure
    by observing the reader's wait time: it should be >= the writer's
    remaining sleep, not roughly zero.
    """
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()

    writer_done = asyncio.Event()
    writer_acquired = asyncio.Event()

    async def slow_writer() -> None:
        async with store.acquire("write"):
            writer_acquired.set()
            await asyncio.sleep(SLEEP_INSIDE_LOCK * 2)
        writer_done.set()

    reader_ran_before_writer_done: list[bool] = []

    async def reader() -> None:
        # Wait until the writer is definitely inside the lock.
        await writer_acquired.wait()
        # Confirm the writer is active per the lock's own state.
        assert store._rwlock.writer_active is True
        async with store.acquire("read"):
            # We only get here after the writer released — record state.
            reader_ran_before_writer_done.append(not writer_done.is_set())

    t0 = time.perf_counter()
    await asyncio.gather(slow_writer(), reader())
    elapsed = time.perf_counter() - t0

    # The reader should NOT have run before the writer finished — i.e.
    # `writer_done` should have been set first.
    assert reader_ran_before_writer_done == [False], (
        "Reader acquired the lock while the writer was still active"
    )

    # The overall run should be at least one writer-sleep — the reader
    # could not have shortened it.
    assert elapsed >= SLEEP_INSIDE_LOCK * 2 * 0.9, (
        f"Total elapsed {elapsed:.3f}s shorter than writer sleep — "
        f"writer didn't actually hold the lock exclusively"
    )

    await store.close()


@pytest.mark.asyncio
async def test_writer_preference(tmp_db: Path):
    """
    5 readers, then 1 writer, then 5 more readers — the writer must
    complete BEFORE any of the trailing readers, even though they
    were spawned after the writer. This proves writer-preference.

    Implementation detail: we await the first 5 readers' acquisition
    before spawning the writer, then schedule the trailing readers
    *after* the writer has had a chance to enter its waiting state.
    """
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()

    completion_order: list[str] = []

    leading_readers_in = asyncio.Event()
    leading_readers_in_counter = [0]
    release_leading_readers = asyncio.Event()
    writer_queued = asyncio.Event()

    async def leading_reader(i: int) -> None:
        async with store.acquire("read"):
            leading_readers_in_counter[0] += 1
            if leading_readers_in_counter[0] == 5:
                leading_readers_in.set()
            # Hold the lock until we explicitly allow drain.
            await release_leading_readers.wait()
            completion_order.append(f"LR{i}")

    async def the_writer() -> None:
        # We expect to QUEUE (5 readers are already holding).
        # Signal that we are about to call acquire_write so the test
        # driver can release the leading readers AFTER our queue entry.
        async def _signal_then_acquire():
            writer_queued.set()
            await store._rwlock.acquire_write()
        await _signal_then_acquire()
        try:
            completion_order.append("W")
        finally:
            await store._rwlock.release_write()

    async def trailing_reader(i: int) -> None:
        async with store.acquire("read"):
            completion_order.append(f"TR{i}")

    # 1. Start the 5 leading readers and wait until they are all inside.
    leading_tasks = [asyncio.create_task(leading_reader(i)) for i in range(5)]
    await leading_readers_in.wait()

    # 2. Start the writer; it will park because readers_active == 5.
    writer_task = asyncio.create_task(the_writer())
    # Give the writer a moment to actually enter acquire_write().
    await writer_queued.wait()
    # Yield a few times so writers_waiting gets incremented.
    for _ in range(5):
        await asyncio.sleep(0)
    assert store._rwlock.writers_waiting >= 1, (
        "Writer should be queued at this point"
    )

    # 3. Start the 5 trailing readers — they should park BEHIND the
    #    writer because writers_waiting > 0 (writer-preference).
    trailing_tasks = [asyncio.create_task(trailing_reader(i)) for i in range(5)]
    # Let them all reach their wait_for inside acquire_read.
    for _ in range(5):
        await asyncio.sleep(0)

    # At this point: readers_active == 5, writer queued, 5 trailing
    # readers parked. Now release the leading readers.
    release_leading_readers.set()

    # Drain everything.
    await asyncio.gather(*leading_tasks, writer_task, *trailing_tasks)

    # Sanity: all 11 events recorded.
    assert len(completion_order) == 11, completion_order

    # Writer-preference assertion: the writer must appear in the
    # completion order BEFORE any TR* entry.
    writer_idx = completion_order.index("W")
    first_trailing_idx = min(
        i for i, e in enumerate(completion_order) if e.startswith("TR")
    )
    assert writer_idx < first_trailing_idx, (
        f"Writer ran AFTER a trailing reader. Order: {completion_order}"
    )

    await store.close()


@pytest.mark.asyncio
async def test_rwlock_release_when_not_held_is_safe(tmp_db: Path):
    """
    release_write/release_read called when nothing is held must not
    blow up or corrupt the counters — guards against double-release.
    """
    lock = _RWLock()
    # Idempotent / safe — must not raise.
    await lock.release_write()
    await lock.release_read()
    assert lock.readers_active == 0
    assert lock.writer_active is False
    assert lock.writers_waiting == 0


@pytest.mark.asyncio
async def test_rwlock_writer_then_reader_serial(tmp_db: Path):
    """
    After a writer completes, a subsequent reader must be able to
    acquire immediately (no stuck state).
    """
    lock = _RWLock()
    await lock.acquire_write()
    assert lock.writer_active is True
    await lock.release_write()
    assert lock.writer_active is False

    await lock.acquire_read()
    assert lock.readers_active == 1
    await lock.release_read()
    assert lock.readers_active == 0
