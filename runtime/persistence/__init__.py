"""
NCL Persistence layer — SQLite-backed durable stores.

Replaces hand-rolled JSONL writers (50+ across the codebase) with a
single-node SQLite database providing atomic transactions, schema
migrations, and indexed reads. ChromaDB remains the home for vector
embeddings; this layer is for relational + lookup-heavy data.

Public surface:
    from runtime.persistence import SqliteStore, get_store, init_db
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .double_write import DoubleWriteHook
from .sqlite_store import SqliteStore, get_store

__all__ = ["DoubleWriteHook", "SqliteStore", "get_store", "init_db"]

log = logging.getLogger("ncl.persistence")


def init_db(db_path: Optional[Path] = None) -> dict:
    """
    Synchronous boot-time entry point. Idempotently:
      1. ensures ``data/persistence/`` exists,
      2. opens the SQLite connection (creates ``ncl.db`` if missing),
      3. applies every pending migration in ``schema/`` in lex order.

    Safe to call repeatedly from launch scripts, verifiers, and tests.
    Returns a dict with ``db_path`` and ``applied`` (the list of
    migration names applied during this call — empty if up-to-date).

    Use this from sync contexts (e.g. ``scripts/launch-brain.sh``
    pre-flight, ``sqlite_burn_in_verify.py``). Async callers should
    call ``await get_store()`` directly — same effect, no
    asyncio.run() overhead.
    """

    async def _do() -> dict:
        store = await get_store(db_path=db_path)
        applied = await store.apply_migrations()
        return {
            "db_path": str(store.db_path),
            "applied": applied,
            "schema_applied_count": len(await store.applied_migrations()),
        }

    # Allow callers inside an existing event loop to fall back gracefully.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're already in an event loop — can't use asyncio.run().
        # Schedule the coroutine and block on its result via a new task.
        # This path is exercised by tests; production callers run sync.
        raise RuntimeError(
            "init_db() called from inside a running event loop — "
            "use `await get_store()` and `await store.apply_migrations()` instead"
        )

    result = asyncio.run(_do())
    log.info(
        "[INIT] persistence ready: db=%s migrations_applied_now=%d total_applied=%d",
        result["db_path"],
        len(result["applied"]),
        result["schema_applied_count"],
    )
    return result
