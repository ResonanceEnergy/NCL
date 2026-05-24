#!/usr/bin/env python3
"""
migrate_units_index_to_sqlite.py — one-shot, idempotent JSONL→SQLite move.

What it does:
    * Reads data/memory/units.jsonl (the MemoryStore append-only NDJSON).
    * Extracts the *index fields* from each MemUnit row (NOT the full
      content — that stays in JSONL + Chroma) and inserts into the
      SQLite `units_index` table.
    * When a unit_id appears multiple times in JSONL (append-only updates),
      the migration is *idempotent* via INSERT OR IGNORE on the PRIMARY
      KEY (unit_id) — the first-seen row wins (subsequent appends are
      skipped, exactly matching how _load_all_units uses last-wins via a
      dict but stable for the index-only case where we only need scan-
      free filter columns).
    * Does NOT modify the source units.jsonl — strictly read-only.
    * Tolerates malformed entries (counts as errors, continues).
    * Reports rows scanned / inserted / skipped / errors at the end.

Run:
    python3 scripts/migrate_units_index_to_sqlite.py
    python3 scripts/migrate_units_index_to_sqlite.py --dry-run
    python3 scripts/migrate_units_index_to_sqlite.py --source data/memory/units.jsonl
    python3 scripts/migrate_units_index_to_sqlite.py --batch-size 1000 --verbose

Idempotency note:
    The table's PRIMARY KEY is unit_id, which is unique per memory unit.
    INSERT OR IGNORE makes the migration safe to re-run any number of
    times — already-imported units are silently skipped.

NATRIX activation procedure (after running this script):
    1. python3 scripts/migrate_units_index_to_sqlite.py
    2. echo NCL_UNITS_INDEX_SQLITE=true >> .env
    3. launchctl kickstart -k gui/$(id -u)/com.resonanceenergy.ncl-brain
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

# Allow `python3 scripts/migrate_units_index_to_sqlite.py` from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.persistence import get_store  # noqa: E402

log = logging.getLogger("ncl.migrate.units_index")

DEFAULT_SOURCE = REPO_ROOT / "data" / "memory" / "units.jsonl"


INSERT_SQL = """
INSERT OR IGNORE INTO units_index
    (unit_id, content_hash, source, memory_type, authority_tier,
     importance, created_at, last_accessed, tags,
     reinforcement_count, decay_rate,
     decay_score, tier, chroma_collection, signal_id, fingerprint)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── Helpers ──────────────────────────────────────────────────────────


def _coerce_iso(value: Any) -> Optional[str]:
    """Best-effort ISO8601 string extraction from a JSON datetime field."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _content_hash(content: Any) -> Optional[str]:
    """sha256 of the first 1KB of content — used as a dedup fingerprint."""
    if content is None:
        return None
    try:
        text = str(content)[:1000]
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    except Exception:
        return None


def _resolve_authority_tier(entry: dict) -> Optional[int]:
    """
    Pull the authority_tier int (10..100) from MemUnit.metadata, with a
    legacy fallback to a top-level field if a caller stashed it there.
    """
    meta = entry.get("metadata") or {}
    val = meta.get("authority_tier")
    if val is None:
        val = entry.get("authority_tier")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _resolve_route_level(entry: dict) -> Optional[str]:
    """Awarebot route_level (focused/micro/macro), stashed in metadata or unit.tier."""
    meta = entry.get("metadata") or {}
    return entry.get("tier") or meta.get("route_level") or meta.get("tier")


def _resolve_signal_id(entry: dict) -> Optional[str]:
    meta = entry.get("metadata") or {}
    sid = entry.get("signal_id") or meta.get("signal_id")
    return str(sid) if sid is not None else None


def _resolve_chroma_collection(entry: dict) -> Optional[str]:
    meta = entry.get("metadata") or {}
    return meta.get("chroma_collection") or entry.get("chroma_collection")


def unit_to_row(entry: dict) -> Optional[tuple]:
    """
    Map a units.jsonl entry to the SQLite column tuple.

    Returns None for malformed entries (caller bumps the error counter).
    Validates only the structural minimum — anything we cannot project
    cleanly falls back to None / defaults.
    """
    try:
        unit_id = entry.get("unit_id")
        created_at = _coerce_iso(entry.get("created_at"))
        if not unit_id or not created_at:
            return None

        memory_type = entry.get("memory_type") or "episodic"
        importance = entry.get("importance")
        try:
            importance = float(importance) if importance is not None else 0.0
        except (TypeError, ValueError):
            importance = 0.0

        decay_rate = entry.get("decay_rate")
        try:
            decay_rate = float(decay_rate) if decay_rate is not None else 0.95
        except (TypeError, ValueError):
            decay_rate = 0.95

        reinforcement_count = entry.get("reinforcement_count") or 0
        try:
            reinforcement_count = int(reinforcement_count)
        except (TypeError, ValueError):
            reinforcement_count = 0

        authority_tier = _resolve_authority_tier(entry)
        # SCANNER tier (20) is the safest fallback for unstamped legacy units —
        # matches the brain's default for ingest sources without explicit
        # provenance. NULLing it out would break the NOT NULL constraint.
        if authority_tier is None:
            authority_tier = 20

        tags = entry.get("tags") or []
        try:
            tags_str = json.dumps(tags, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            tags_str = "[]"

        return (
            str(unit_id),
            _content_hash(entry.get("content")),
            str(entry.get("source")) if entry.get("source") is not None else None,
            str(memory_type),
            int(authority_tier),
            float(importance),
            created_at,
            _coerce_iso(entry.get("last_accessed")),
            tags_str,
            reinforcement_count,
            decay_rate,
            None,  # decay_score — recomputed live by MemoryStore, not migrated
            _resolve_route_level(entry),
            _resolve_chroma_collection(entry),
            _resolve_signal_id(entry),
            None,  # fingerprint — populated by future reflection-pass migration
        )
    except Exception:
        return None


# ── Core migration ───────────────────────────────────────────────────


async def migrate(
    source: Path,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
) -> dict:
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
            "scanned": 0, "inserted": 0, "skipped": 0, "errors": 0,
            "source": str(source), "db_path": str(store.db_path),
            "dry_run": dry_run,
        }

    log.info("Streaming units from %s (batch_size=%d, dry_run=%s)",
             source, batch_size, dry_run)

    batch: list[tuple] = []
    try:
        with open(source, "r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                scanned += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    errors += 1
                    log.debug("Skipping malformed JSON at line %d", line_no)
                    continue
                if not isinstance(entry, dict):
                    errors += 1
                    continue
                row = unit_to_row(entry)
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
    except OSError as exc:
        log.error("Could not read %s: %s", source, exc)
        return {
            "scanned": scanned, "inserted": inserted,
            "skipped": skipped, "errors": errors + 1,
            "source": str(source), "db_path": str(store.db_path),
            "dry_run": dry_run, "read_error": str(exc),
        }

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
        scanned, inserted, skipped, errors, store.db_path,
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
        help="Path to units.jsonl (default: data/memory/units.jsonl)",
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

    result = asyncio.run(
        migrate(args.source, dry_run=args.dry_run, batch_size=args.batch_size)
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
