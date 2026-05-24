"""
004_add_composite_indexes_w8.py — code-side hook for zz_indexes_w8.sql

W8-A7 (2026-05-24): Adds three composite indexes
(idx_units_authority_importance, idx_units_created_importance,
idx_council_sessions_pump) that accelerate the working-context salience
scan, the memory timeline pagination, and the /pump/review/{id} hot
path. The schema file is prefixed ``zz_`` so it sorts AFTER every
table-create — indexes cannot be created before their tables.

Boilerplate lives in ``_base.build_migration``; this file is just the
declaration. ``apply_migrations()`` discovers the schema via the
``runtime/persistence/schema/*.sql`` glob — not via this import.

Usage:
    from runtime.persistence.migrations import _004 as m
    await m.migrate()
"""

from __future__ import annotations

from ._base import build_migration


NAME = "004_add_composite_indexes_w8"
migrate, status = build_migration(NAME)
