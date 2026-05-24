"""
Tests for scripts/migrate_cost_ledger_to_sqlite.py
"""
from __future__ import annotations  # noqa: I001

import json
from pathlib import Path

import pytest

# Ensure the scripts/ dir is on sys.path so we can import the migration.
import sys
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import importlib  # noqa: E402, I001

migrate_module = importlib.import_module("migrate_cost_ledger_to_sqlite")

from runtime.persistence.sqlite_store import SqliteStore  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────

SAMPLE_ROWS = [
    {
        "timestamp": "2026-05-20T06:36:38.424557+00:00",
        "date": "2026-05-20",
        "source": "anthropic",
        "amount_usd": 0.04551,
        "category": "ytc_analysis",
        "detail": "model=claude-sonnet-4-20250514 in=4575 out=2119",
        "metadata": {
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 4575,
            "output_tokens": 2119,
        },
    },
    {
        "timestamp": "2026-05-20T06:36:47.383468+00:00",
        "date": "2026-05-20",
        "source": "anthropic",
        "amount_usd": 0.006015,
        "category": "ytc_analysis",
        "detail": "model=claude-sonnet-4-20250514 in=455 out=310",
        "metadata": {
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 455,
            "output_tokens": 310,
        },
    },
    {
        "timestamp": "2026-05-20T07:00:00.000000+00:00",
        "date": "2026-05-20",
        "source": "xai",
        "amount_usd": 0.10,
        "category": "council_member",
        "detail": "grok-2",
    },
]


def _write_jsonl(path: Path, rows: list[dict], *, malformed: bool = False) -> None:
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        if malformed:
            f.write("{this is not valid json\n")
            f.write("\n")  # blank line


@pytest.fixture
def fresh_store(tmp_path, monkeypatch) -> Path:
    """
    Force the persistence layer to use a tmp DB by:
    1. Pointing NCL_SQLITE_PATH at a tmp file
    2. Resetting the singleton
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("NCL_SQLITE_PATH", str(db_path))

    # Reset the persistence-layer singleton so it picks up the env override
    from runtime.persistence import sqlite_store as ss
    ss._store_instance = None

    return db_path


# ── 1. Migration is idempotent ───────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_idempotent(tmp_path, fresh_store):
    source = tmp_path / "cost_ledger.jsonl"
    _write_jsonl(source, SAMPLE_ROWS)

    r1 = await migrate_module.migrate(source)
    r2 = await migrate_module.migrate(source)

    assert r1["scanned"] == 3
    assert r1["inserted"] == 3
    assert r1["skipped"] == 0

    assert r2["scanned"] == 3
    assert r2["inserted"] == 0, "second run should insert nothing"
    assert r2["skipped"] == 3, "second run should skip all rows as duplicates"

    # Verify final row count is still 3
    store = SqliteStore(db_path=fresh_store)
    await store.initialize()
    rows = await store.fetch_all("SELECT * FROM cost_ledger")
    assert len(rows) == 3
    await store.close()


# ── 2. Malformed lines are tolerated ─────────────────────────────────

@pytest.mark.asyncio
async def test_migration_skips_malformed_lines(tmp_path, fresh_store):
    source = tmp_path / "cost_ledger.jsonl"
    _write_jsonl(source, SAMPLE_ROWS, malformed=True)

    # Also append a row with missing required fields
    with open(source, "a") as f:
        f.write(json.dumps({"timestamp": "2026-05-20T08:00:00Z"}) + "\n")  # missing source/amount

    r = await migrate_module.migrate(source)
    # 3 good + 1 bad-json + 1 missing-fields = 5 scanned (blank line is skipped before counting)
    assert r["scanned"] >= 4  # at minimum the 3 good + 1 missing-fields row
    assert r["inserted"] == 3
    assert r["errors"] >= 1, "malformed JSON line should be counted as error"


# ── 3. Round-trip integrity: row count + sums match the JSONL ────────

@pytest.mark.asyncio
async def test_migrated_rows_match_jsonl_count(tmp_path, fresh_store):
    source = tmp_path / "cost_ledger.jsonl"
    _write_jsonl(source, SAMPLE_ROWS)

    await migrate_module.migrate(source)

    store = SqliteStore(db_path=fresh_store)
    await store.initialize()

    rows = await store.fetch_all("SELECT * FROM cost_ledger ORDER BY ts")
    assert len(rows) == 3, "all 3 sample rows should round-trip into SQLite"

    # Field-by-field check on one row
    r0 = rows[0]
    assert r0["source"] == "anthropic"
    assert r0["date_utc"] == "2026-05-20"
    assert r0["purpose"] == "ytc_analysis"
    assert r0["model"] == "claude-sonnet-4-20250514"
    assert r0["input_tokens"] == 4575
    assert r0["output_tokens"] == 2119
    assert abs(r0["actual_cost_usd"] - 0.04551) < 1e-9

    # Sum matches the JSONL sum
    total_jsonl = sum(r["amount_usd"] for r in SAMPLE_ROWS)
    row = await store.fetch_one("SELECT SUM(actual_cost_usd) AS s FROM cost_ledger")
    assert abs(row["s"] - total_jsonl) < 1e-9

    await store.close()


# ── 4. Dry-run does not modify the DB ────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_does_not_write(tmp_path, fresh_store):
    source = tmp_path / "cost_ledger.jsonl"
    _write_jsonl(source, SAMPLE_ROWS)

    r = await migrate_module.migrate(source, dry_run=True)
    assert r["dry_run"] is True
    assert r["inserted"] == 3  # reports what *would* have been written

    store = SqliteStore(db_path=fresh_store)
    await store.initialize()
    rows = await store.fetch_all("SELECT * FROM cost_ledger")
    assert len(rows) == 0, "dry-run must not write anything"
    await store.close()
