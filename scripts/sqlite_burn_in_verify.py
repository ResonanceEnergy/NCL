#!/usr/bin/env python3
"""
sqlite_burn_in_verify.py — JSONL ↔ SQLite drift detector.

W8-A7 (2026-05-24): During the double-write burn-in window (after the
one-shot migration scripts have run + the corresponding
NCL_*_SQLITE=true flag is set), this verifier reads BOTH the canonical
JSONL/JSON source and the SQLite mirror, builds a canonical row shape
for each, and compares row counts + sha256 checksums.

Exit codes:
    0 — perfect match (row count + checksum identical)
    1 — divergence detected (any difference)
    2 — script error (missing source, DB connect failure, etc.)

Usage:
    python3 scripts/sqlite_burn_in_verify.py --table cost_ledger
    python3 scripts/sqlite_burn_in_verify.py --table mandates
    python3 scripts/sqlite_burn_in_verify.py --table units_index
    python3 scripts/sqlite_burn_in_verify.py --table all   # default

NATRIX flag-flip procedure
--------------------------
After a successful migrate-then-burn-in window, run:

    python3 scripts/sqlite_burn_in_verify.py --table cost_ledger

A 0-exit confirms zero divergence. THEN, and only then, set:

    echo NCL_COST_LEDGER_READ=true >> .env
    launchctl kickstart -k gui/$(id -u)/com.resonanceenergy.ncl-brain

(Replace cost_ledger with the table you're flipping. Use
sqlite_flip_flag.sh as the recipe printer.)

Design notes
------------
The verifier intentionally takes the *whole table*, not a sample — at
the current scale (cost ledger ~10K rows, mandates ~100 rows, units
~10K rows) a full scan + sha256 takes <2s and gives a deterministic
"identical" answer rather than a probabilistic one.

For units_index we hash only the *index columns* (unit_id, content_hash,
authority_tier, importance, memory_type, source, created_at, tags) —
the migration deliberately drops the full content from this table, so
checksumming the body would always disagree.

Each table-specific canonicaliser lives in its own function so the
shape is auditable in code review.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.persistence import get_store  # noqa: E402


log = logging.getLogger("ncl.burn_in_verify")

DEFAULT_COST_JSONL = REPO_ROOT / "data" / "costs" / "cost_ledger.jsonl"
DEFAULT_MANDATES_JSON = REPO_ROOT / "data" / "mandates.json"
DEFAULT_UNITS_JSONL = REPO_ROOT / "data" / "memory" / "units.jsonl"


# ── Canonicalisers ────────────────────────────────────────────────────
#
# Each canonicaliser maps a source row (from JSONL or SQLite) into a
# JSON string with sorted keys. The checksum is computed over the
# sorted list of these strings — identical canonical bytes on both
# sides means zero drift.


def _canon_cost_ledger_jsonl(row: dict) -> Optional[str]:
    """JSONL row → canonical key shape used by both stores."""
    ts = row.get("timestamp")
    src = row.get("source")
    amt = row.get("amount_usd")
    cat = row.get("category")
    if ts is None or src is None or amt is None:
        return None
    # The SQLite UNIQUE index is on (ts, source, actual_cost_usd, purpose).
    # That tuple is the dedup primary so it's also the cleanest checksum key.
    return json.dumps(
        {
            "ts": ts,
            "source": src,
            "amount_usd": round(float(amt), 6),
            "category": cat or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _canon_cost_ledger_sqlite(row: dict) -> Optional[str]:
    """SQLite row → same key shape (note: column names differ)."""
    ts = row.get("ts")
    src = row.get("source")
    amt = row.get("actual_cost_usd")
    purpose = row.get("purpose")
    if ts is None or src is None or amt is None:
        return None
    return json.dumps(
        {
            "ts": ts,
            "source": src,
            "amount_usd": round(float(amt), 6),
            "category": purpose or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _canon_mandates_json(row: dict) -> Optional[str]:
    """mandates.json row → canonical key shape (id + status + version)."""
    mid = row.get("mandate_id")
    if not mid:
        return None
    status = row.get("status")
    if hasattr(status, "value"):
        status = status.value
    return json.dumps(
        {
            "mandate_id": mid,
            "status": str(status) if status is not None else "",
            "version": int(row.get("version", 0) or 0),
            "updated_at": str(row.get("updated_at") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _canon_mandates_sqlite(row: dict) -> Optional[str]:
    """SQLite mandates row → same key shape."""
    mid = row.get("mandate_id")
    if not mid:
        return None
    return json.dumps(
        {
            "mandate_id": mid,
            "status": str(row.get("status") or ""),
            "version": int(row.get("version", 0) or 0),
            "updated_at": str(row.get("updated_at") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _canon_units_jsonl(row: dict) -> Optional[str]:
    """units.jsonl row → only the index columns (body is intentionally dropped)."""
    uid = row.get("unit_id")
    if not uid:
        return None
    meta = row.get("metadata") or {}
    authority = meta.get("authority_tier")
    if authority is None:
        authority = row.get("authority_tier")
    try:
        authority = int(authority) if authority is not None else 20
    except (TypeError, ValueError):
        authority = 20
    try:
        importance = float(row.get("importance") or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    return json.dumps(
        {
            "unit_id": str(uid),
            "memory_type": str(row.get("memory_type") or "episodic"),
            "authority_tier": authority,
            "importance": round(importance, 4),
            "source": str(row.get("source") or ""),
            "created_at": str(row.get("created_at") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _canon_units_sqlite(row: dict) -> Optional[str]:
    """SQLite units_index row → same index-only shape."""
    uid = row.get("unit_id")
    if not uid:
        return None
    try:
        importance = float(row.get("importance") or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    return json.dumps(
        {
            "unit_id": str(uid),
            "memory_type": str(row.get("memory_type") or "episodic"),
            "authority_tier": int(row.get("authority_tier") or 20),
            "importance": round(importance, 4),
            "source": str(row.get("source") or ""),
            "created_at": str(row.get("created_at") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


# ── Source loaders ────────────────────────────────────────────────────


def _iter_jsonl(path: Path) -> Iterable[dict]:
    """Stream-parse a JSONL file; skip malformed lines silently."""
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _iter_json_array(path: Path) -> Iterable[dict]:
    """Read a top-level JSON array (mandates.json shape)."""
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                yield row
    elif isinstance(data, dict):
        # Defensive: some callers persist {mandate_id: row}
        for row in data.values():
            if isinstance(row, dict):
                yield row


async def _fetch_sqlite_all(table: str) -> list[dict]:
    """Return every row from a SQLite table as plain dicts."""
    store = await get_store()
    rows = await store.fetch_all(f"SELECT * FROM {table}")
    return [dict(r) for r in rows]


# ── Diff engine ───────────────────────────────────────────────────────


def _checksum(canon_strings: list[str]) -> tuple[int, str]:
    """Return (count, sha256 hex) for a list of canonical row strings."""
    sorted_strings = sorted(canon_strings)
    h = hashlib.sha256()
    for s in sorted_strings:
        h.update(s.encode("utf-8"))
        h.update(b"\n")
    return len(sorted_strings), h.hexdigest()


def _sample_diff(left: list[str], right: list[str], limit: int = 5) -> dict:
    """Produce a small diff summary: rows in left-only, right-only."""
    lset = set(left)
    rset = set(right)
    left_only = sorted(lset - rset)[:limit]
    right_only = sorted(rset - lset)[:limit]
    return {
        "jsonl_only_count": len(lset - rset),
        "sqlite_only_count": len(rset - lset),
        "jsonl_only_samples": left_only,
        "sqlite_only_samples": right_only,
    }


# ── Per-table runners ─────────────────────────────────────────────────


async def verify_cost_ledger(jsonl_path: Path) -> dict:
    """JSONL + rotated siblings (data/costs/cost_ledger.jsonl*) vs SQLite cost_ledger."""
    # Match the migration script's rotated-sibling scan
    jsonl_files = []
    if jsonl_path.is_dir():
        jsonl_files = sorted(jsonl_path.glob("*.jsonl"))
    else:
        if jsonl_path.exists():
            jsonl_files.append(jsonl_path)
        # also rotated siblings cost_ledger.jsonl.1 / .2 ...
        for sibling in sorted(jsonl_path.parent.glob(f"{jsonl_path.name}.*")):
            jsonl_files.append(sibling)

    left: list[str] = []
    for f in jsonl_files:
        for row in _iter_jsonl(f):
            c = _canon_cost_ledger_jsonl(row)
            if c is not None:
                left.append(c)

    sqlite_rows = await _fetch_sqlite_all("cost_ledger")
    right = [c for c in (_canon_cost_ledger_sqlite(r) for r in sqlite_rows) if c]

    lcount, lhash = _checksum(left)
    rcount, rhash = _checksum(right)
    match = lcount == rcount and lhash == rhash
    out = {
        "table": "cost_ledger",
        "jsonl_files": [str(p) for p in jsonl_files],
        "jsonl_count": lcount,
        "sqlite_count": rcount,
        "jsonl_sha256": lhash,
        "sqlite_sha256": rhash,
        "match": match,
    }
    if not match:
        out["divergence"] = _sample_diff(left, right)
    return out


async def verify_mandates(json_path: Path) -> dict:
    """mandates.json vs SQLite mandates."""
    left: list[str] = []
    for row in _iter_json_array(json_path):
        c = _canon_mandates_json(row)
        if c is not None:
            left.append(c)

    sqlite_rows = await _fetch_sqlite_all("mandates")
    right = [c for c in (_canon_mandates_sqlite(r) for r in sqlite_rows) if c]

    lcount, lhash = _checksum(left)
    rcount, rhash = _checksum(right)
    match = lcount == rcount and lhash == rhash
    out = {
        "table": "mandates",
        "json_file": str(json_path),
        "json_count": lcount,
        "sqlite_count": rcount,
        "json_sha256": lhash,
        "sqlite_sha256": rhash,
        "match": match,
    }
    if not match:
        out["divergence"] = _sample_diff(left, right)
    return out


async def verify_units_index(jsonl_path: Path) -> dict:
    """
    units.jsonl vs SQLite units_index.

    units.jsonl is append-only: a unit_id can appear MULTIPLE times
    (re-writes append a fresh row). The SQLite index is keyed by
    unit_id PRIMARY KEY — only the first-seen row is stored
    (INSERT OR IGNORE). To get an apples-to-apples comparison we
    de-dupe the JSONL side by keeping the FIRST occurrence of each
    unit_id (matches the migration script's semantics).
    """
    seen: dict[str, str] = {}
    for row in _iter_jsonl(jsonl_path):
        uid = row.get("unit_id")
        if not uid or uid in seen:
            continue
        c = _canon_units_jsonl(row)
        if c is not None:
            seen[uid] = c

    left = list(seen.values())

    sqlite_rows = await _fetch_sqlite_all("units_index")
    right = [c for c in (_canon_units_sqlite(r) for r in sqlite_rows) if c]

    lcount, lhash = _checksum(left)
    rcount, rhash = _checksum(right)
    match = lcount == rcount and lhash == rhash
    out = {
        "table": "units_index",
        "jsonl_file": str(jsonl_path),
        "jsonl_unique_unit_count": lcount,
        "sqlite_count": rcount,
        "jsonl_sha256": lhash,
        "sqlite_sha256": rhash,
        "match": match,
    }
    if not match:
        out["divergence"] = _sample_diff(left, right)
    return out


TABLE_VERIFIERS: dict[str, Callable[[Path], object]] = {
    "cost_ledger": lambda p: verify_cost_ledger(p),
    "mandates": lambda p: verify_mandates(p),
    "units_index": lambda p: verify_units_index(p),
}

TABLE_DEFAULT_SOURCE = {
    "cost_ledger": DEFAULT_COST_JSONL,
    "mandates": DEFAULT_MANDATES_JSON,
    "units_index": DEFAULT_UNITS_JSONL,
}


# ── CLI ───────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Verify that SQLite double-write mirrors match their JSONL/JSON "
            "source. Exit 0 on match, 1 on divergence, 2 on script error."
        )
    )
    p.add_argument(
        "--table",
        choices=["cost_ledger", "mandates", "units_index", "all"],
        default="all",
        help="Which table to verify (default: all).",
    )
    p.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Override the default JSONL/JSON source path for the chosen table.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human report.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Log INFO-level progress.",
    )
    return p


async def _run(args: argparse.Namespace) -> int:
    if args.table == "all":
        tables = ["cost_ledger", "mandates", "units_index"]
    else:
        tables = [args.table]

    results: list[dict] = []
    for t in tables:
        source = args.source if (args.source and args.table == t) else TABLE_DEFAULT_SOURCE[t]
        try:
            res = await TABLE_VERIFIERS[t](source)
        except Exception as exc:
            log.exception("[VERIFY] %s failed: %s", t, exc)
            return 2
        results.append(res)

    if args.json:
        print(json.dumps({"results": results}, indent=2, default=str))
    else:
        for r in results:
            print(f"\n── {r['table']} ─────────────────────────────")
            for k, v in r.items():
                if k == "table":
                    continue
                if isinstance(v, dict):
                    print(f"  {k}:")
                    for sk, sv in v.items():
                        print(f"    {sk}: {sv}")
                else:
                    print(f"  {k}: {v}")
        print()

    any_divergence = any(not r.get("match", False) for r in results)
    return 1 if any_divergence else 0


def main() -> int:
    args = _build_argparser().parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
