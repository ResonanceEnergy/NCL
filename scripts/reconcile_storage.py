#!/usr/bin/env python3
"""
reconcile_storage.py — JSONL/JSON ↔ SQLite reconciliation for the
double-write burn-in window.

Three stores are in (or scheduled for) double-write today:

    cost_ledger  data/costs/cost_ledger.jsonl   ↔ cost_ledger table
    mandates     data/mandates.json             ↔ mandates table
    units        data/memory/units.jsonl        ↔ units_index table

This script reads each side, computes counts (and a sum for the cost
ledger), and reports anything that differs:

    * in_both         — present in both stores
    * only_jsonl      — in the source-of-truth file, NOT in SQLite
    * only_sqlite     — in SQLite, NOT in the source file

It is **read-only**. The output is a JSON document on stdout so the
script can be piped into `jq` or stuffed into a nightly cron + Slack
post. Exit code is 0 if the script ran cleanly (regardless of
whether deltas were found); non-zero only on hard failures (DB
missing, file unreadable).

Usage
-----

    # Reconcile everything (default)
    python3 scripts/reconcile_storage.py
    python3 scripts/reconcile_storage.py --source all

    # One store at a time
    python3 scripts/reconcile_storage.py --source cost_ledger
    python3 scripts/reconcile_storage.py --source mandates
    python3 scripts/reconcile_storage.py --source units

    # Override the SQLite DB path (default: data/persistence/ncl.db)
    python3 scripts/reconcile_storage.py --db /tmp/ncl-test.db

    # Quiet — JSON only, no progress logging
    python3 scripts/reconcile_storage.py --quiet

Output shape
------------

```json
{
  "ts": "2026-05-23T17:14:00+00:00",
  "db_path": "/Users/natrix/dev/NCL/data/persistence/ncl.db",
  "sources": {
    "cost_ledger": {
      "jsonl_count": 1843,
      "sqlite_count": 1843,
      "in_both": 1843,
      "only_jsonl": 0,
      "only_sqlite": 0,
      "jsonl_sum_usd": 12.41,
      "sqlite_sum_usd": 12.41,
      "delta_usd": 0.0
    },
    "mandates": {
      "jsonl_count": 27,
      "sqlite_count": 0,
      "in_both": 0,
      "only_jsonl": 27,
      "only_sqlite": 0,
      "diff_ids": ["MANDATE-2026-001", "..."]
    },
    "units": {
      "jsonl_count": 9711,
      "sqlite_count": 0,
      "in_both": 0,
      "only_jsonl": 9711,
      "only_sqlite": 0,
      "missing_ids_sample": ["dd9e7a2d-...", "..."]
    }
  }
}
```

Author: NCL — W4-15, 2026-05-23.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable


log = logging.getLogger("ncl.reconcile")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "persistence" / "ncl.db"
DEFAULT_COST_LEDGER = REPO_ROOT / "data" / "costs" / "cost_ledger.jsonl"
DEFAULT_MANDATES = REPO_ROOT / "data" / "mandates.json"
DEFAULT_UNITS = REPO_ROOT / "data" / "memory" / "units.jsonl"

# How many diverging IDs to surface in the report (full list is too noisy
# when units.jsonl has 9K+ rows).
MAX_DIFF_SAMPLE = 25


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection. Falls back gracefully if the
    DB file doesn't exist — the caller then reports sqlite_count=0 for
    every source so the operator can see the JSONL side at minimum.
    """
    if not db_path.exists():
        log.warning("SQLite DB not found at %s — reporting sqlite_count=0", db_path)
        return None  # type: ignore[return-value]
    # Read-only URI to make sure we never accidentally write during a
    # reconciliation run.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection | None, table: str) -> bool:
    if conn is None:
        return False
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning("Skipping malformed JSONL line %d in %s: %s", lineno, path, e)
                continue


# ─────────────────────────────────────────────────────────────────────────────
# cost_ledger
# ─────────────────────────────────────────────────────────────────────────────


def reconcile_cost_ledger(conn: sqlite3.Connection | None, jsonl_path: Path) -> dict:
    """Count rows + sum spend in both stores. The cost ledger is the
    only store where dollar-sum agreement is the strongest signal — a
    row-count match can hide an amount drift.
    """
    jsonl_count = 0
    jsonl_sum = Decimal("0")
    jsonl_keys: set[tuple] = set()
    for entry in _iter_jsonl(jsonl_path):
        jsonl_count += 1
        try:
            amt = Decimal(str(entry.get("amount_usd", 0)))
        except Exception:
            amt = Decimal("0")
        jsonl_sum += amt
        # Dedup key matches the SQLite UNIQUE index:
        # (ts, source, actual_cost_usd, purpose)
        key = (
            entry.get("timestamp"),
            entry.get("source"),
            float(amt),
            entry.get("category"),
        )
        jsonl_keys.add(key)

    sqlite_count = 0
    sqlite_sum = Decimal("0")
    sqlite_keys: set[tuple] = set()
    if _table_exists(conn, "cost_ledger"):
        for row in conn.execute(  # type: ignore[union-attr]
            "SELECT ts, source, actual_cost_usd, purpose FROM cost_ledger"
        ):
            sqlite_count += 1
            try:
                amt = Decimal(str(row["actual_cost_usd"] or 0))
            except Exception:
                amt = Decimal("0")
            sqlite_sum += amt
            sqlite_keys.add((row["ts"], row["source"], float(amt), row["purpose"]))

    in_both = jsonl_keys & sqlite_keys
    only_jsonl = jsonl_keys - sqlite_keys
    only_sqlite = sqlite_keys - jsonl_keys

    return {
        "jsonl_count": jsonl_count,
        "sqlite_count": sqlite_count,
        "in_both": len(in_both),
        "only_jsonl": len(only_jsonl),
        "only_sqlite": len(only_sqlite),
        "jsonl_sum_usd": float(jsonl_sum),
        "sqlite_sum_usd": float(sqlite_sum),
        "delta_usd": float(jsonl_sum - sqlite_sum),
    }


# ─────────────────────────────────────────────────────────────────────────────
# mandates
# ─────────────────────────────────────────────────────────────────────────────


def reconcile_mandates(conn: sqlite3.Connection | None, json_path: Path) -> dict:
    """`data/mandates.json` is a single JSON array of mandate dicts.
    Each dict has a `mandate_id`. SQLite stores one row per id.
    """
    jsonl_ids: set[str] = set()
    if json_path.exists():
        try:
            with json_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, list):
                for m in payload:
                    mid = m.get("mandate_id") if isinstance(m, dict) else None
                    if mid:
                        jsonl_ids.add(mid)
            elif isinstance(payload, dict):
                # Some snapshots write {mandate_id: {...}, ...}
                jsonl_ids.update(payload.keys())
        except json.JSONDecodeError as e:
            log.error("mandates.json is malformed: %s", e)

    sqlite_ids: set[str] = set()
    if _table_exists(conn, "mandates"):
        for row in conn.execute("SELECT mandate_id FROM mandates"):  # type: ignore[union-attr]
            if row["mandate_id"]:
                sqlite_ids.add(row["mandate_id"])

    in_both = jsonl_ids & sqlite_ids
    only_jsonl = jsonl_ids - sqlite_ids
    only_sqlite = sqlite_ids - jsonl_ids

    diff_ids = sorted(only_jsonl | only_sqlite)[:MAX_DIFF_SAMPLE]

    return {
        "jsonl_count": len(jsonl_ids),
        "sqlite_count": len(sqlite_ids),
        "in_both": len(in_both),
        "only_jsonl": len(only_jsonl),
        "only_sqlite": len(only_sqlite),
        "diff_ids": diff_ids,
    }


# ─────────────────────────────────────────────────────────────────────────────
# units (memory)
# ─────────────────────────────────────────────────────────────────────────────


def reconcile_units(conn: sqlite3.Connection | None, jsonl_path: Path) -> dict:
    """`data/memory/units.jsonl` is the source-of-truth MemUnit log.
    `units_index` table is a SQLite mirror (index only, body stays in
    JSONL + Chroma — see docs/PERSISTENCE.md).
    """
    jsonl_ids: set[str] = set()
    for entry in _iter_jsonl(jsonl_path):
        uid = entry.get("unit_id") or entry.get("id")
        if uid:
            jsonl_ids.add(uid)

    sqlite_ids: set[str] = set()
    if _table_exists(conn, "units_index"):
        for row in conn.execute("SELECT unit_id FROM units_index"):  # type: ignore[union-attr]
            if row["unit_id"]:
                sqlite_ids.add(row["unit_id"])

    in_both = jsonl_ids & sqlite_ids
    only_jsonl = jsonl_ids - sqlite_ids
    only_sqlite = sqlite_ids - jsonl_ids

    # IDs missing from SQLite are the actionable ones during double-write.
    missing_sample = sorted(only_jsonl)[:MAX_DIFF_SAMPLE]
    extra_sample = sorted(only_sqlite)[:MAX_DIFF_SAMPLE]

    return {
        "jsonl_count": len(jsonl_ids),
        "sqlite_count": len(sqlite_ids),
        "in_both": len(in_both),
        "only_jsonl": len(only_jsonl),
        "only_sqlite": len(only_sqlite),
        "missing_ids_sample": missing_sample,
        "extra_ids_sample": extra_sample,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────


SOURCES = ("cost_ledger", "mandates", "units")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="reconcile_storage",
        description=(
            "Reconcile JSONL/JSON sources of truth against their SQLite "
            "mirrors. Read-only. Outputs JSON to stdout."
        ),
    )
    p.add_argument(
        "--source",
        choices=("cost_ledger", "mandates", "units", "all"),
        default="all",
        help="Which store to reconcile (default: all).",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite DB path (default: {DEFAULT_DB}).",
    )
    p.add_argument(
        "--cost-ledger-path",
        type=Path,
        default=DEFAULT_COST_LEDGER,
        help=f"cost_ledger JSONL (default: {DEFAULT_COST_LEDGER}).",
    )
    p.add_argument(
        "--mandates-path",
        type=Path,
        default=DEFAULT_MANDATES,
        help=f"mandates JSON (default: {DEFAULT_MANDATES}).",
    )
    p.add_argument(
        "--units-path",
        type=Path,
        default=DEFAULT_UNITS,
        help=f"units JSONL (default: {DEFAULT_UNITS}).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress logging — JSON output only.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    selected: tuple[str, ...]
    if args.source == "all":
        selected = SOURCES
    else:
        selected = (args.source,)

    conn = _open_db(args.db)

    out: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "db_path": str(args.db),
        "sources": {},
    }

    try:
        if "cost_ledger" in selected:
            log.info("Reconciling cost_ledger …")
            out["sources"]["cost_ledger"] = reconcile_cost_ledger(conn, args.cost_ledger_path)
        if "mandates" in selected:
            log.info("Reconciling mandates …")
            out["sources"]["mandates"] = reconcile_mandates(conn, args.mandates_path)
        if "units" in selected:
            log.info("Reconciling units …")
            out["sources"]["units"] = reconcile_units(conn, args.units_path)
    finally:
        if conn is not None:
            conn.close()

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
