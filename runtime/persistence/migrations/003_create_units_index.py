"""
003_create_units_index.py — code-side hook for units_index.sql

Boilerplate lives in ``_base.build_migration``; this file is just the
declaration. ``apply_migrations()`` discovers the schema via the
``runtime/persistence/schema/*.sql`` glob — not via this import. Pairs
with ``scripts/migrate_units_index_to_sqlite.py``.

units_index is a *lightweight index* — the canonical MemUnit body stays
in data/memory/units.jsonl + ChromaDB. The point of this index is to
let 18+ callers stop full-scanning a ~200MB JSONL on every filtered
read; the body is still hydrated from the JSONL by unit_id batch reads.

Usage:
    from runtime.persistence.migrations import _003 as m
    await m.migrate()
"""
from __future__ import annotations

from ._base import build_migration

NAME = "003_create_units_index"
migrate, status = build_migration(NAME)
