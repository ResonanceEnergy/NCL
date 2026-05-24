"""
001_create_cost_ledger.py — code-side hook for cost_ledger.sql

Boilerplate lives in ``_base.build_migration``; this file is just the
declaration. ``apply_migrations()`` discovers the schema via the
``runtime/persistence/schema/*.sql`` glob — not via this import.

Usage:
    from runtime.persistence.migrations import _001 as m
    await m.migrate()
"""
from __future__ import annotations

from ._base import build_migration

NAME = "001_create_cost_ledger"
migrate, status = build_migration(NAME)
