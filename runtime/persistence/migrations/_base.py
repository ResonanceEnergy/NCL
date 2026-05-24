"""
_base.py — shared boilerplate for the 00N_*.py migration shims.

The schema for every NCL migration is a ``.sql`` file under
``runtime/persistence/schema/`` and is applied automatically by
``SqliteStore.apply_migrations()`` (which discovers files by lex-order
glob, NOT by Python imports). The 00N_*.py files here exist purely to
give callers an explicit ``migrate()`` / ``status()`` entry point that
mirrors the SQL file's lifecycle without needing to know the
schema-application is implicit.

Because every shim is the same boilerplate (call ``apply_migrations()``,
log, return ``applied_migrations()`` for ``status()``), this module
factors the 95% into ``build_migration(name)`` and each 00N_*.py file
becomes a 2-3 line declaration:

    from ._base import build_migration

    NAME = "001_create_cost_ledger"
    migrate, status = build_migration(NAME)

The objects exported by each shim — ``NAME``, ``migrate``, ``status`` —
keep the same names and signatures the old hand-rolled files had, so
nothing on the call side has to change.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from ..sqlite_store import get_store


def build_migration(
    name: str,
) -> tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[dict]]]:
    """Return ``(migrate, status)`` coroutines for a migration named ``name``.

    Both are idempotent. ``migrate()`` delegates to
    ``SqliteStore.apply_migrations()`` (a no-op if every ``.sql`` file
    has already been recorded in ``schema_migrations``) and logs whether
    anything was applied this call. ``status()`` returns the full set
    of applied migrations plus the DB path — useful for diagnostics.

    The returned callables capture ``name`` in their closure so the log
    line and logger channel are specific to the calling shim.
    """
    log = logging.getLogger(f"ncl.persistence.migrations.{name.split('_', 1)[0]}")

    async def migrate() -> None:
        store = await get_store()
        applied = await store.apply_migrations()
        if applied:
            log.info("[migrate %s] applied: %s", name, applied)
        else:
            log.info("[migrate %s] already up to date", name)

    async def status() -> dict:
        store = await get_store()
        return {
            "applied": sorted(await store.applied_migrations()),
            "db_path": str(store.db_path),
        }

    return migrate, status
