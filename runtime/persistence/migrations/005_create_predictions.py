"""
005_create_predictions.py — code-side hook for predictions.sql

W8-A12 (2026-05-24): Adds the ``predictions`` table that backs
``GET /predictions``, ``POST /prediction/{id}/outcome`` and the
accuracy roll-ups. Replaces the one-file-per-prediction layout under
``data/predictions/pred-*.json`` (786 files at audit) with a single
indexed SQLite table; the bulk import is handled by the one-shot
``scripts/migrate_predictions_to_sqlite.py``.

Boilerplate lives in ``_base.build_migration``; this file is just the
declaration. ``apply_migrations()`` discovers the schema via the
``runtime/persistence/schema/*.sql`` glob — not via this import.

Usage:
    from runtime.persistence.migrations import _005 as m
    await m.migrate()
"""
from __future__ import annotations

from ._base import build_migration

NAME = "005_create_predictions"
migrate, status = build_migration(NAME)
