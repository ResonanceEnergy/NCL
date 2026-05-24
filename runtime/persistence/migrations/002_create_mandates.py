"""
002_create_mandates.py — code-side hook for mandates.sql

Boilerplate lives in ``_base.build_migration``; this file is just the
declaration. ``apply_migrations()`` discovers the schema via the
``runtime/persistence/schema/*.sql`` glob — not via this import. Pairs
with ``scripts/migrate_mandates_to_sqlite.py``.

Usage:
    from runtime.persistence.migrations import _002 as m
    await m.migrate()
"""

from __future__ import annotations

from ._base import build_migration


NAME = "002_create_mandates"
migrate, status = build_migration(NAME)
