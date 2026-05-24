"""
Tests for the mandates → SQLite migration + double-write hook.

Covers:
    * Migration script idempotency
    * Migration script tolerance of malformed entries
    * Double-write hook DISABLED by default (no env flag)
    * Double-write hook ENABLED persists both to JSON and SQLite
    * Status-transition history is preserved through SQLite round-trip

The double-write hook tests instantiate a minimal NCLBrain-shaped harness
rather than the full NCLBrain (which requires API keys + heavy subsystems).
We exercise the actual `_persist_mandates_unlocked` and
`_sqlite_persist_mandates` methods bound to the harness via descriptor
protocol — same code paths as production.
"""
from __future__ import annotations  # noqa: I001

import asyncio  # noqa: F401
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "ncl_mandates_test.db"


@pytest.fixture
def mandates_json(tmp_path) -> Path:
    """A canonical mandates.json file with three entries."""
    p = tmp_path / "mandates.json"
    p.write_text(json.dumps([
        {
            "mandate_id": "M-001",
            "pillar": "ncc",
            "priority": 5,
            "title": "First mandate",
            "objective": "Do the thing",
            "success_criteria": ["A", "B"],
            "deadline": None,
            "resources": {"budget": 100},
            "status": "active",
            "version": 1,
            "created_at": "2026-05-23T10:00:00+00:00",
            "updated_at": "2026-05-23T11:00:00+00:00",
            "source_pump_id": "pump-1",
            "status_history": [
                {"from": "draft", "to": "active", "reason": "ok",
                 "timestamp": "2026-05-23T11:00:00+00:00", "version": 0}
            ],
        },
        {
            "mandate_id": "M-002",
            "pillar": "ncl",
            "priority": 7,
            "title": "Second mandate",
            "objective": "Other thing",
            "success_criteria": [],
            "deadline": "2026-06-01T00:00:00+00:00",
            "resources": {},
            "status": "draft",
            "version": 0,
            "created_at": "2026-05-23T10:01:00+00:00",
            "updated_at": "2026-05-23T10:01:00+00:00",
            "source_pump_id": None,
            "status_history": [],
        },
    ], indent=2))
    return p


@pytest.fixture
def mandates_json_with_garbage(tmp_path) -> Path:
    """A mandates.json containing two valid + two malformed entries."""
    p = tmp_path / "mandates.json"
    p.write_text(json.dumps([
        # Valid
        {
            "mandate_id": "G-001",
            "pillar": "ncc",
            "priority": 5,
            "title": "Good one",
            "objective": "obj",
            "success_criteria": [],
            "resources": {},
            "status": "active",
            "version": 0,
            "created_at": "2026-05-23T10:00:00+00:00",
            "updated_at": "2026-05-23T10:00:00+00:00",
            "status_history": [],
        },
        # Missing mandate_id (required)
        {
            "pillar": "ncc",
            "status": "active",
            "created_at": "2026-05-23T10:00:00+00:00",
            "updated_at": "2026-05-23T10:00:00+00:00",
        },
        # Missing status (required)
        {
            "mandate_id": "G-002-bad",
            "pillar": "ncc",
            "created_at": "2026-05-23T10:00:00+00:00",
            "updated_at": "2026-05-23T10:00:00+00:00",
        },
        # Valid
        {
            "mandate_id": "G-003",
            "pillar": "ncl",
            "priority": 3,
            "title": "Another good one",
            "objective": "obj",
            "success_criteria": [],
            "resources": {},
            "status": "draft",
            "version": 0,
            "created_at": "2026-05-23T10:00:00+00:00",
            "updated_at": "2026-05-23T10:00:00+00:00",
            "status_history": [],
        },
    ], indent=2))
    return p


async def _fresh_store(tmp_db: Path):
    """Return a clean SqliteStore singleton bound to tmp_db."""
    from runtime.persistence.sqlite_store import (
        SqliteStore,
        _reset_singleton_for_tests,
    )
    await _reset_singleton_for_tests()
    # Also re-point the singleton via NCL_SQLITE_PATH for any code that
    # calls get_store() without an arg.
    os.environ["NCL_SQLITE_PATH"] = str(tmp_db)
    store = SqliteStore(db_path=tmp_db)
    await store.initialize()
    # Re-install as the singleton so get_store() returns it.
    import runtime.persistence.sqlite_store as ss
    ss._store_instance = store
    return store


# ── 1. Migration idempotency ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_idempotent(tmp_db: Path, mandates_json: Path):
    import scripts.migrate_mandates_to_sqlite as mig

    store = await _fresh_store(tmp_db)

    first = await mig.migrate(mandates_json, dry_run=False)
    assert first["scanned"] == 2
    assert first["inserted"] == 2
    assert first["errors"] == 0
    assert first["skipped"] == 0

    # Second run: every row is already in SQLite, so INSERT OR IGNORE
    # skips them all.
    second = await mig.migrate(mandates_json, dry_run=False)
    assert second["scanned"] == 2
    assert second["inserted"] == 0
    assert second["skipped"] == 2
    assert second["errors"] == 0

    rows = await store.fetch_all("SELECT mandate_id FROM mandates ORDER BY mandate_id")
    assert {r["mandate_id"] for r in rows} == {"M-001", "M-002"}

    await store.close()


# ── 2. Migration tolerates malformed entries ─────────────────────────


@pytest.mark.asyncio
async def test_migration_skips_malformed(tmp_db: Path, mandates_json_with_garbage: Path):
    import scripts.migrate_mandates_to_sqlite as mig

    store = await _fresh_store(tmp_db)

    result = await mig.migrate(mandates_json_with_garbage, dry_run=False)
    assert result["scanned"] == 4
    assert result["inserted"] == 2
    assert result["errors"] == 2

    rows = await store.fetch_all("SELECT mandate_id FROM mandates ORDER BY mandate_id")
    assert {r["mandate_id"] for r in rows} == {"G-001", "G-003"}

    await store.close()


# ── 3. Double-write disabled by default ──────────────────────────────


@pytest.mark.asyncio
async def test_double_write_disabled_default(tmp_db: Path, tmp_path, monkeypatch):
    """Without NCL_MANDATES_SQLITE=true, SQLite is NEVER touched on persist."""
    # W10A-6 (2026-05-24): brain.py:_validate_config() runs at module import
    # and `os.environ.setdefault`s every key in .env — including
    # NCL_MANDATES_SQLITE=true on this host. monkeypatch.delenv leaves
    # setdefault free to put "true" right back. Set "false" explicitly so
    # setdefault is a no-op and the module-level constant evaluates to
    # the disabled-by-default behavior we're testing.
    monkeypatch.setenv("NCL_MANDATES_SQLITE", "false")

    # Force-fresh-import brain module so the module-level SQLITE_DOUBLE_WRITE
    # constant is re-evaluated with the env in this test's state.
    if "runtime.ncl_brain.brain" in sys.modules:
        del sys.modules["runtime.ncl_brain.brain"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    import runtime.ncl_brain.brain as brain_mod
    importlib.reload(brain_mod)

    assert brain_mod.SQLITE_DOUBLE_WRITE is False

    store = await _fresh_store(tmp_db)

    harness = _make_harness(tmp_path, brain_mod)
    harness.mandates = {"D-001": _build_mandate("D-001")}

    await brain_mod.NCLBrain._persist_mandates_unlocked(harness)

    # JSON file written
    assert harness.mandates_file.exists()
    payload = json.loads(harness.mandates_file.read_text())
    assert payload[0]["mandate_id"] == "D-001"

    # SQLite table empty — flag was off
    rows = await store.fetch_all("SELECT mandate_id FROM mandates")
    assert rows == []

    await store.close()


# ── 4. Double-write enabled persists both ────────────────────────────


@pytest.mark.asyncio
async def test_double_write_enabled_persists_both(tmp_db: Path, tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_MANDATES_SQLITE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    if "runtime.ncl_brain.brain" in sys.modules:
        del sys.modules["runtime.ncl_brain.brain"]
    import runtime.ncl_brain.brain as brain_mod
    importlib.reload(brain_mod)

    assert brain_mod.SQLITE_DOUBLE_WRITE is True

    store = await _fresh_store(tmp_db)

    harness = _make_harness(tmp_path, brain_mod)
    m1 = _build_mandate("DW-001", title="Double-write target one")
    m2 = _build_mandate("DW-002", title="Double-write target two")
    harness.mandates = {m1.mandate_id: m1, m2.mandate_id: m2}

    await brain_mod.NCLBrain._persist_mandates_unlocked(harness)

    # JSON has both
    payload = json.loads(harness.mandates_file.read_text())
    assert {p["mandate_id"] for p in payload} == {"DW-001", "DW-002"}

    # SQLite has both
    rows = await store.fetch_all("SELECT mandate_id, title, status, version FROM mandates")
    by_id = {r["mandate_id"]: r for r in rows}
    assert set(by_id) == {"DW-001", "DW-002"}
    assert by_id["DW-001"]["title"] == "Double-write target one"
    assert by_id["DW-001"]["status"] == "draft"

    await store.close()


# ── 5. Status transition history preserved through SQLite ───────────


@pytest.mark.asyncio
async def test_status_transition_preserves_history(tmp_db: Path, tmp_path, monkeypatch):
    monkeypatch.setenv("NCL_MANDATES_SQLITE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    if "runtime.ncl_brain.brain" in sys.modules:
        del sys.modules["runtime.ncl_brain.brain"]
    import runtime.ncl_brain.brain as brain_mod
    importlib.reload(brain_mod)

    store = await _fresh_store(tmp_db)

    harness = _make_harness(tmp_path, brain_mod)
    m = _build_mandate("ST-001")
    harness.mandates = {m.mandate_id: m}

    # First persist — draft, no transitions
    await brain_mod.NCLBrain._persist_mandates_unlocked(harness)
    row = await store.fetch_one(
        "SELECT status, version, status_history FROM mandates WHERE mandate_id = ?",
        ("ST-001",),
    )
    assert row["status"] == "draft"
    assert row["version"] == 0
    assert json.loads(row["status_history"]) == []

    # Transition: draft → pending_approval (per MandateStatus.valid_transitions)
    from runtime.ncl_brain.models import MandateStatus
    m.transition_to(MandateStatus.PENDING_APPROVAL, reason="testing")

    # Second persist — INSERT OR REPLACE refreshes the row
    await brain_mod.NCLBrain._persist_mandates_unlocked(harness)
    row = await store.fetch_one(
        "SELECT status, version, status_history FROM mandates WHERE mandate_id = ?",
        ("ST-001",),
    )
    assert row["status"] == "pending_approval"
    assert row["version"] == 1
    history = json.loads(row["status_history"])
    assert len(history) == 1
    assert history[0]["from"] == "draft"
    assert history[0]["to"] == "pending_approval"
    assert history[0]["reason"] == "testing"

    await store.close()


# ── Helpers ──────────────────────────────────────────────────────────


def _build_mandate(mandate_id: str, *, title: str = "T", status: str = "draft"):
    """Build a real Mandate Pydantic model."""
    from runtime.ncl_brain.models import Mandate, MandateStatus, PillarType
    now = datetime.now(timezone.utc)
    return Mandate(
        mandate_id=mandate_id,
        pillar=PillarType.NCC,
        priority=5,
        title=title,
        objective="objective",
        success_criteria=["a", "b"],
        deadline=None,
        resources={},
        status=MandateStatus(status),
        version=0,
        created_at=now,
        updated_at=now,
        source_pump_id=None,
        status_history=[],
    )


class _PersistHarness:
    """
    Minimal stand-in for the bits of NCLBrain that _persist_mandates_unlocked
    actually touches. The real persist method is invoked via
    NCLBrain._persist_mandates_unlocked(harness) — we expose every attribute
    + method that method dereferences. `_sqlite_persist_mandates` is bound
    from the NCLBrain class itself so we exercise production code, not a
    re-implementation.
    """
    def __init__(self, mandates_file: Path):
        self.mandates_file = mandates_file
        self.mandates: dict = {}
        self._mandates_sqlite = None
        self._sqlite_warned = False

    @staticmethod
    def _atomic_write_json(tmp_path: Path, dest_path: Path, payload: str) -> None:
        tmp_path.write_text(payload)
        tmp_path.replace(dest_path)


def _make_harness(tmp_path: Path, brain_mod) -> _PersistHarness:
    mandates_file = tmp_path / "mandates.json"
    h = _PersistHarness(mandates_file)
    # Bind the real _sqlite_persist_mandates method onto the harness so
    # _persist_mandates_unlocked(self) can call self._sqlite_persist_mandates(...)
    # against production code.
    h._sqlite_persist_mandates = brain_mod.NCLBrain._sqlite_persist_mandates.__get__(h)
    # W10B-1: also bind the DoubleWriteHook plumbing — production code
    # now routes the SQLite write through `self._mandates_hook()` which
    # in turn uses `NCLBrain._build_mandate_row`. Both must be present
    # on the descriptor target so the harness exercises the real path.
    h._mandates_hook = brain_mod.NCLBrain._mandates_hook.__get__(h)
    return h
