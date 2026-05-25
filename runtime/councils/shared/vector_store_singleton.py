"""
Process-wide singleton for the council CouncilVectorStore.

Why this exists
---------------
Before this module, three call sites instantiated their own
``CouncilVectorStore`` against the same on-disk persistent store:

* ``runtime/councils/runner.py::_auto_ingest_report`` — *fresh per video*,
  called 20-50× per hourly YTC dedicated loop
* ``runtime/api/routers/council.py`` — three handlers, each with its own
  module-level singleton + double-checked lock
* ``runtime/lde/sandbox.py`` — one per LDE init

``CouncilVectorStore.__init__()`` calls ``chromadb.PersistentClient(path=...)``
which mmaps the index files and spawns background HNSW threads. Multiple
short-lived clients pointed at the same persistent directory can deadlock
the Rust HNSW write lock — observed 2026-05-24 19:20 with pid 27623 stuck
at 99% CPU entirely inside ``chromadb_rust_bindings.abi3.so``, frozen
mid-YTC-loop on video 24/33.

Public API
----------
``get_council_vector_store(data_dir)`` returns a single shared
``CouncilVectorStore``. First call initializes the backend; subsequent
calls return the already-initialized instance. Double-checked locking on
an ``asyncio.Lock`` prevents two concurrent boots.

Callers MUST go through this function, not ``CouncilVectorStore(...)``
directly. The constructor is fine — it just creates a Python object —
but ``.init()`` opens the persistent client, and that's the bit we have
to keep singular.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .vector_store import CouncilVectorStore


log = logging.getLogger("ncl.councils.vector_store_singleton")


_instance: CouncilVectorStore | None = None
_lock: asyncio.Lock | None = None
_data_dir_used: Path | None = None


def _get_lock() -> asyncio.Lock:
    """Lazily build the asyncio.Lock so it binds to the running event loop."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_council_vector_store(data_dir: str | Path) -> CouncilVectorStore:
    """Return the process-wide ``CouncilVectorStore`` singleton.

    Args:
        data_dir: NCL data directory (e.g. ``~/dev/NCL/data``). Used to
            seed the singleton on first call. Subsequent calls reuse the
            already-initialized instance regardless of what ``data_dir``
            is passed — we log a warning if it diverges.

    Returns:
        The shared ``CouncilVectorStore`` with ``.init()`` already awaited.
    """
    global _instance, _data_dir_used

    if _instance is not None:
        # Hot path: instance already exists. No lock needed for the
        # read; Python attribute reads are atomic enough for this.
        requested = Path(data_dir).expanduser().resolve()
        if _data_dir_used is not None and requested != _data_dir_used:
            log.warning(
                "[VS-SINGLETON] data_dir mismatch — singleton was bound to %s, "
                "caller requested %s. Reusing existing singleton.",
                _data_dir_used,
                requested,
            )
        return _instance

    async with _get_lock():
        # Re-check inside the lock (double-checked locking).
        if _instance is not None:
            return _instance

        resolved = Path(data_dir).expanduser().resolve()
        log.info("[VS-SINGLETON] initializing CouncilVectorStore at %s", resolved)
        store = CouncilVectorStore(data_dir=resolved)
        backend = await store.init()
        log.info("[VS-SINGLETON] initialized — backend=%s", backend)

        _instance = store
        _data_dir_used = resolved
        return _instance


def reset_for_tests() -> None:
    """Drop the cached instance. Test-only — never call in prod."""
    global _instance, _data_dir_used
    _instance = None
    _data_dir_used = None
