#!/usr/bin/env python3
"""
migrate_cost_ledger_to_sqlite.py — one-shot, idempotent JSONL→SQLite move.

What it does:
    * Reads data/costs/cost_ledger.jsonl (and any rotated *.jsonl in the
      same dir).
    * Inserts each row into the SQLite cost_ledger table.
    * Idempotent via the unique (ts, source, actual_cost_usd, purpose) index
      created in the schema — re-running just bumps the "skipped" counter.
    * Does NOT delete, truncate, or modify the source JSONL — read-only.
    * Reports rows scanned / inserted / skipped / errors at the end.

Run:
    python3 scripts/migrate_cost_ledger_to_sqlite.py
    python3 scripts/migrate_cost_ledger_to_sqlite.py --dry-run
    python3 scripts/migrate_cost_ledger_to_sqlite.py --source data/costs/cost_ledger.jsonl

Idempotency note:
    SQLite UNIQUE constraint on (ts, source, actual_cost_usd, purpose) is
    enough to dedup the ledger. The JSONL is append-only and not modified
    by any other tool — re-running the migration on a file the live
    cost_tracker is still appending to is safe (new lines will be picked
    up; already-imported lines will be ignored).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Iterable


# Allow `python3 scripts/migrate_cost_ledger_to_sqlite.py` from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.persistence import get_store  # noqa: E402


log = logging.getLogger("ncl.migrate.cost_ledger")

DEFAULT_SOURCE = REPO_ROOT / "data" / "costs" / "cost_ledger.jsonl"


INSERT_SQL = """
INSERT OR IGNORE INTO cost_ledger
    (ts, date_utc, source, model, purpose, est_cost_usd,
     actual_cost_usd, input_tokens, output_tokens, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def iter_jsonl_files(source: Path) -> Iterable[Path]:
    """Yield the primary file plus any rotated siblings (`*.jsonl`, `*.jsonl.N`)."""
    if source.is_dir():
        # Scan an entire directory
        for p in sorted(source.glob("*.jsonl*")):
            if p.is_file():
                yield p
    elif source.is_file():
        yield source
        # Pick up rotated siblings like cost_ledger.jsonl.1, cost_ledger.jsonl.gz, etc.
        for p in sorted(source.parent.glob(source.name + ".*")):
            if p.is_file() and not p.name.endswith(".gz"):
                yield p


def jsonl_row_to_sqlite(entry: dict) -> tuple | None:
    """
    Map a JSONL entry to the cost_ledger column tuple.

    Returns None for malformed entries (caller bumps the error counter).
    """
    try:
        ts = entry.get("timestamp")
        date_utc = entry.get("date")
        source = entry.get("source")
        actual = entry.get("amount_usd")
        if not (ts and date_utc and source and actual is not None):
            return None

        purpose = entry.get("category")
        metadata = entry.get("metadata") or {}
        # Preserve the "detail" string inside metadata so nothing is lost.
        if "detail" in entry and entry["detail"]:
            metadata.setdefault("detail", entry["detail"])

        model = metadata.get("model") if isinstance(metadata, dict) else None
        input_tokens = metadata.get("input_tokens") if isinstance(metadata, dict) else None
        output_tokens = metadata.get("output_tokens") if isinstance(metadata, dict) else None
        est = metadata.get("est_cost_usd") if isinstance(metadata, dict) else None

        return (
            ts,
            date_utc,
            source,
            model,
            purpose,
            est,
            float(actual),
            int(input_tokens) if input_tokens is not None else None,
            int(output_tokens) if output_tokens is not None else None,
            json.dumps(metadata, separators=(",", ":")) if metadata else None,
        )
    except Exception:
        return None


async def migrate(source: Path, *, dry_run: bool = False, batch_size: int = 500) -> dict:
    store = await get_store()
    # apply_migrations is implicit in initialize() but call it again to be loud.
    await store.apply_migrations()

    scanned = 0
    inserted = 0
    skipped = 0
    errors = 0

    files = list(iter_jsonl_files(source))
    if not files:
        log.warning("No JSONL files found under %s", source)
        return {"scanned": 0, "inserted": 0, "skipped": 0, "errors": 0, "files": []}

    log.info("Scanning %d file(s) for cost-ledger migration", len(files))

    batch: list[tuple] = []
    for path in files:
        log.info("→ %s", path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    scanned += 1
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        errors += 1
                        continue

                    row = jsonl_row_to_sqlite(entry)
                    if row is None:
                        errors += 1
                        continue

                    batch.append(row)

                    if len(batch) >= batch_size:
                        if dry_run:
                            inserted += len(batch)  # what would have been inserted
                        else:
                            rc = await _flush(store, batch)
                            inserted += rc
                            skipped += len(batch) - rc
                        batch.clear()
        except FileNotFoundError:
            log.warning("file disappeared: %s", path)
            continue

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
        "files": [str(p) for p in files],
        "dry_run": dry_run,
        "db_path": str(store.db_path),
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
    skipped by INSERT OR IGNORE). SQLite gives us rowcount post-commit
    via the changes() pragma path; we use the executemany cursor rowcount
    which on SQLite reflects the *last* statement, so we fall back to
    counting changes via Connection.total_changes for the delta.
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
        help="Path to cost_ledger.jsonl (or directory of jsonl files)",
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
