"""
Tests for the units_index SQLite migration + flag-gated search path (W4-14).

Covers:
    * Migration script idempotency (INSERT OR IGNORE on unit_id)
    * Migration script tolerance of malformed JSONL rows
    * `_search_units_via_sqlite_index` returns the expected filtered ids
      when the env flag is ON and the index is populated
    * `_search_units_via_sqlite_index` returns [] when the flag is OFF
      so existing callers safely fall back to the JSONL full-scan
"""

from __future__ import annotations  # noqa: I001

import json
import os
import sys
import uuid  # noqa: F401
from datetime import datetime, timedelta, timezone  # noqa: F401
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "ncl_units_index_test.db"


def _make_unit_dict(
    unit_id: str,
    *,
    source: str = "awarebot",
    memory_type: str = "episodic",
    importance: float = 50.0,
    tags: list[str] | None = None,
    authority_tier: int = 20,
    created_at: datetime | None = None,
) -> dict:
    """Build a JSON-serializable MemUnit-shaped dict."""
    now = created_at or datetime.now(timezone.utc)
    return {
        "unit_id": unit_id,
        "content": f"content for {unit_id}",
        "source": source,
        "importance": importance,
        "decay_rate": 0.95,
        "last_accessed": now.isoformat(),
        "reinforcement_count": 0,
        "tags": tags or [],
        "created_at": now.isoformat(),
        "related_units": [],
        "memory_type": memory_type,
        "memory_tier": "SML",
        "llm_importance_score": None,
        "entities": [],
        "relationships": [],
        "consolidated_from": [],
        "reflection_quality": None,
        "metadata": {"authority_tier": authority_tier},
    }


@pytest.fixture
def units_jsonl(tmp_path) -> Path:
    """A canonical units.jsonl with 5 valid entries."""
    p = tmp_path / "units.jsonl"
    rows = [
        _make_unit_dict("U-001", tags=["natrix", "council"], importance=90.0),
        _make_unit_dict("U-002", tags=["scanner"], importance=30.0),
        _make_unit_dict("U-003", tags=["council"], importance=70.0, memory_type="decision"),
        _make_unit_dict("U-004", tags=["calendar"], importance=50.0, source="calendar"),
        _make_unit_dict("U-005", tags=["natrix"], importance=85.0, authority_tier=100),
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


@pytest.fixture
def units_jsonl_with_garbage(tmp_path) -> Path:
    """Units JSONL with 2 valid + 2 malformed rows."""
    p = tmp_path / "units.jsonl"
    lines = [
        json.dumps(_make_unit_dict("G-001")),
        "{ this is not json",  # malformed
        json.dumps({"unit_id": "G-002-bad"}),  # missing required created_at
        json.dumps(_make_unit_dict("G-003")),
    ]
    p.write_text("\n".join(lines) + "\n")
    return p


async def _fresh_store(tmp_db: Path):
    """Return a clean SqliteStore singleton bound to tmp_db."""
    from runtime.persistence.sqlite_store import (
        SqliteStore,
        _reset_singleton_for_tests,
    )

    await _reset_singleton_for_tests()
    os.environ["NCL_SQLITE_PATH"] = str(tmp_db)
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()
    # Re-install as the singleton so get_store() returns it.
    import runtime.persistence.sqlite_store as ss

    ss._store_instance = store
    return store


# ── 1. Migration idempotency ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_idempotent(tmp_db: Path, units_jsonl: Path):
    import scripts.migrate_units_index_to_sqlite as mig

    store = await _fresh_store(tmp_db)

    first = await mig.migrate(units_jsonl, dry_run=False)
    assert first["scanned"] == 5
    assert first["inserted"] == 5
    assert first["errors"] == 0
    assert first["skipped"] == 0

    # Second run: INSERT OR IGNORE skips every existing row.
    second = await mig.migrate(units_jsonl, dry_run=False)
    assert second["scanned"] == 5
    assert second["inserted"] == 0
    assert second["skipped"] == 5
    assert second["errors"] == 0

    rows = await store.fetch_all("SELECT unit_id FROM units_index ORDER BY unit_id")
    assert {r["unit_id"] for r in rows} == {"U-001", "U-002", "U-003", "U-004", "U-005"}

    await store.close()


# ── 2. Migration tolerates malformed rows ────────────────────────────


@pytest.mark.asyncio
async def test_migration_skips_malformed(tmp_db: Path, units_jsonl_with_garbage: Path):
    import scripts.migrate_units_index_to_sqlite as mig

    store = await _fresh_store(tmp_db)

    result = await mig.migrate(units_jsonl_with_garbage, dry_run=False)
    # 4 non-blank lines scanned (the malformed JSON line is still
    # counted as scanned before parse fails).
    assert result["scanned"] == 4
    assert result["inserted"] == 2
    assert result["errors"] == 2

    rows = await store.fetch_all("SELECT unit_id FROM units_index ORDER BY unit_id")
    assert {r["unit_id"] for r in rows} == {"G-001", "G-003"}

    await store.close()


# ── 3. SQLite-backed search returns filtered ids ─────────────────────


@pytest.mark.asyncio
async def test_search_via_sqlite_index_returns_filtered_ids(
    tmp_db: Path, tmp_path: Path, units_jsonl: Path, monkeypatch
):
    """End-to-end: migrate 10 units, query by tag + threshold via flag-gated method."""
    monkeypatch.setenv("NCL_UNITS_INDEX_SQLITE", "true")

    import scripts.migrate_units_index_to_sqlite as mig

    # Build a larger jsonl with 10 units so we can filter meaningfully.
    p = tmp_path / "units_10.jsonl"
    rows = [
        _make_unit_dict(
            f"X-{i:03d}",
            tags=["alpha"] if i % 2 == 0 else ["beta"],
            importance=10.0 * (i + 1),
            memory_type="episodic" if i < 5 else "decision",
            authority_tier=100 if i == 9 else 20,
            source="awarebot" if i < 7 else "council",
        )
        for i in range(10)
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    store = await _fresh_store(tmp_db)
    result = await mig.migrate(p, dry_run=False)
    assert result["inserted"] == 10

    # Build a MemoryStore bound to a tmp data dir so the method has the
    # right shape — but the SQLite path doesn't touch the memory_file at
    # all, so this is just to instantiate the class.
    from runtime.memory.store import MemoryStore

    ms = MemoryStore(data_dir=tmp_path)

    # Tag filter: alpha (5 units at index 0/2/4/6/8)
    ids = await ms._search_units_via_sqlite_index(tags=["alpha"])
    assert set(ids) == {"X-000", "X-002", "X-004", "X-006", "X-008"}

    # Importance threshold ≥ 50 → indexes 4..9 → 6 units
    ids = await ms._search_units_via_sqlite_index(importance_threshold=50.0)
    assert len(ids) == 6
    # Sort order is importance DESC, so first id should be the highest-importance one.
    assert ids[0] == "X-009"

    # Memory-type filter
    ids = await ms._search_units_via_sqlite_index(memory_type="decision")
    assert set(ids) == {"X-005", "X-006", "X-007", "X-008", "X-009"}

    # Authority tier ≥ 100 → only X-009
    ids = await ms._search_units_via_sqlite_index(min_authority_tier=100)
    assert ids == ["X-009"]

    # Source filter
    ids = await ms._search_units_via_sqlite_index(source="council")
    assert set(ids) == {"X-007", "X-008", "X-009"}

    # Limit
    ids = await ms._search_units_via_sqlite_index(limit=2)
    assert len(ids) == 2

    await store.close()


# ── 4. Flag OFF returns empty list (graceful fallback contract) ──────


@pytest.mark.asyncio
async def test_flag_off_returns_empty_or_falls_back(
    tmp_db: Path, tmp_path: Path, units_jsonl: Path, monkeypatch
):
    """With the flag OFF, the SQLite method MUST return [] without raising,
    so existing callers fall through to the JSONL full-scan path."""
    monkeypatch.delenv("NCL_UNITS_INDEX_SQLITE", raising=False)

    import scripts.migrate_units_index_to_sqlite as mig

    store = await _fresh_store(tmp_db)
    # Populate the index — but the method should still return [] because
    # the flag is off, NOT because there's no data.
    result = await mig.migrate(units_jsonl, dry_run=False)
    assert result["inserted"] == 5

    from runtime.memory.store import MemoryStore

    ms = MemoryStore(data_dir=tmp_path)

    # No filters — would return all 5 if the flag were on.
    ids = await ms._search_units_via_sqlite_index()
    assert ids == []

    # With filters — still empty.
    ids = await ms._search_units_via_sqlite_index(tags=["council"], importance_threshold=10.0)
    assert ids == []

    # Explicit "false" string also returns empty.
    monkeypatch.setenv("NCL_UNITS_INDEX_SQLITE", "false")
    ids = await ms._search_units_via_sqlite_index()
    assert ids == []

    await store.close()
