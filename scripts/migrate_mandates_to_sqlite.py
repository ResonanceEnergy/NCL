#!/usr/bin/env python3
"""
migrate_mandates_to_sqlite.py — one-shot, idempotent JSON→SQLite move.

What it does:
    * Reads data/mandates.json (a single JSON document — list at root, or
      a dict with a top-level "mandates" key).
    * Inserts each mandate row into the SQLite `mandates` table.
    * Idempotent via INSERT OR IGNORE on the PRIMARY KEY (mandate_id) —
      re-running just bumps the "skipped" counter.
    * Does NOT modify the source mandates.json — strictly read-only.
    * Tolerates malformed entries (counts as errors, continues).
    * Reports rows scanned / inserted / skipped / errors at the end.

Run:
    python3 scripts/migrate_mandates_to_sqlite.py
    python3 scripts/migrate_mandates_to_sqlite.py --dry-run
    python3 scripts/migrate_mandates_to_sqlite.py --source data/mandates.json

Idempotency note:
    The table's PRIMARY KEY is mandate_id, which is unique per mandate.
    INSERT OR IGNORE makes the migration safe to re-run any number of
    times — already-imported mandates are silently skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any


# Allow `python3 scripts/migrate_mandates_to_sqlite.py` from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.persistence import get_store  # noqa: E402


log = logging.getLogger("ncl.migrate.mandates")

DEFAULT_SOURCE = REPO_ROOT / "data" / "mandates.json"


INSERT_SQL = """
INSERT OR IGNORE INTO mandates
    (mandate_id, pillar, priority, title, objective, success_criteria,
     deadline, resources, status, version, created_at, updated_at,
     source_pump_id, status_history, payload)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _coerce_iso(value: Any) -> str | None:
    """Best-effort ISO8601 string extraction from a JSON datetime field."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # datetime serialized via default=str (as the brain's _persist does) — already str
    return str(value)


def _jsondumps(value: Any) -> str:
    """Compact JSON, default=str for any datetime sneak-throughs."""
    return json.dumps(value, default=str, separators=(",", ":"))


def mandate_to_row(entry: dict) -> tuple | None:
    """
    Map a mandates.json entry to the SQLite column tuple.

    Returns None for malformed entries (caller bumps the error counter).
    Validates only the structural minimum — the brain's Pydantic model
    is the actual schema authority; we tolerate historical drift here
    because the JSON file has 12+ months of entries with varying shape.
    """
    try:
        mandate_id = entry.get("mandate_id")
        status = entry.get("status")
        created_at = _coerce_iso(entry.get("created_at"))
        updated_at = _coerce_iso(entry.get("updated_at"))

        # Minimum required fields for a sane row.
        if not mandate_id or not status or not created_at or not updated_at:
            return None

        pillar = entry.get("pillar")
        priority = entry.get("priority")
        title = entry.get("title")
        objective = entry.get("objective")
        success_criteria = entry.get("success_criteria") or []
        deadline = _coerce_iso(entry.get("deadline"))
        resources = entry.get("resources") or {}
        version = entry.get("version", 0)
        source_pump_id = entry.get("source_pump_id")
        status_history = entry.get("status_history") or []

        return (
            str(mandate_id),
            str(pillar) if pillar is not None else None,
            int(priority) if priority is not None else None,
            str(title) if title is not None else None,
            str(objective) if objective is not None else None,
            _jsondumps(success_criteria),
            deadline,
            _jsondumps(resources),
            str(status),
            int(version) if version is not None else 0,
            created_at,
            updated_at,
            str(source_pump_id) if source_pump_id is not None else None,
            _jsondumps(status_history),
            _jsondumps(entry),
        )
    except Exception:
        return None


def _load_mandates(source: Path) -> list[dict]:
    """
    Load the mandates document. Tolerates both shapes:
        * list at root: [{...}, {...}, ...]
        * dict with mandates key: {"mandates": [...]}
    """
    with open(source, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        items = data.get("mandates")
        if isinstance(items, list):
            return [m for m in items if isinstance(m, dict)]
        # last-ditch: maybe it's a single mandate dict
        if "mandate_id" in data:
            return [data]
    return []


async def migrate(source: Path, *, dry_run: bool = False, batch_size: int = 500) -> dict:
    store = await get_store()
    # apply_migrations is implicit in initialize() but call it again to be loud.
    await store.apply_migrations()

    scanned = 0
    inserted = 0
    skipped = 0
    errors = 0

    if not source.exists():
        log.warning("Source not found: %s", source)
        return {
            "scanned": 0,
            "inserted": 0,
            "skipped": 0,
            "errors": 0,
            "source": str(source),
            "db_path": str(store.db_path),
            "dry_run": dry_run,
        }

    try:
        mandates = _load_mandates(source)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Could not parse %s: %s", source, exc)
        return {
            "scanned": 0,
            "inserted": 0,
            "skipped": 0,
            "errors": 1,
            "source": str(source),
            "db_path": str(store.db_path),
            "dry_run": dry_run,
            "parse_error": str(exc),
        }

    log.info("Scanning %d mandates from %s", len(mandates), source)

    batch: list[tuple] = []
    for entry in mandates:
        scanned += 1
        row = mandate_to_row(entry)
        if row is None:
            errors += 1
            continue
        batch.append(row)
        if len(batch) >= batch_size:
            if dry_run:
                inserted += len(batch)
            else:
                rc = await _flush(store, batch)
                inserted += rc
                skipped += len(batch) - rc
            batch.clear()

    if batch:
        if dry_run:
            inserted += len(batch)
        else:
            rc = await _flush(store, batch)
            inserted += rc
            skipped += len(batch) - rc

    result = {
        "scanned": scanned,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "source": str(source),
        "db_path": str(store.db_path),
        "dry_run": dry_run,
    }
    log.info(
        "DONE: scanned=%d inserted=%d skipped=%d errors=%d (db=%s)",
        scanned,
        inserted,
        skipped,
        errors,
        store.db_path,
    )
    return result


async def _flush(store, batch: list[tuple]) -> int:
    """
    Execute the batch insert. Returns # of rows actually inserted (not
    skipped by INSERT OR IGNORE). We use Connection.total_changes for
    the delta — sqlite3 cursor.rowcount under executemany is unreliable.
    """
    async with store.acquire("write") as conn:
        before = conn.total_changes
        try:
            conn.execute("BEGIN")
            conn.executemany(INSERT_SQL, batch)
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        after = conn.total_changes
        return after - before


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Path to mandates.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan + parse but don't write to SQLite",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per INSERT batch (default 500)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.source.exists():
        print(f"ERROR: source path does not exist: {args.source}", file=sys.stderr)
        return 2

    result = asyncio.run(migrate(args.source, dry_run=args.dry_run, batch_size=args.batch_size))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
