"""Tests for the PillarRouter — NCL → NCC dispatch.

BRS and AAC were retired on 2026-05-23 per NATRIX directive
("no orphan them we dont use them"). The router now only accepts NCC;
any pillar in {BRS, AAC, INVALID} raises UnknownPillarError. The Mandate
model rejects BRS/AAC at construction (PillarType enum no longer carries
those members).

Tests drive the router with fake env (intake dirs in tmp_path) and a
monkeypatched file write. No real filesystem outside ``tmp_path``, no real
HTTP. Mandate model transitions are exercised against the in-memory model
directly — no live API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# Make ``runtime`` importable from the repo root when tests run via pytest.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.dispatch.pillar_router import (  # noqa: E402
    VALID_PILLARS,
    PillarRouter,
    UnknownPillarError,
    reset_default_router,
)
from runtime.ncl_brain.models import (  # noqa: E402
    Mandate,
    MandateStatus,
    PillarType,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_router_singletons():
    """Drop the process-wide router/breaker registry between tests."""
    reset_default_router()
    yield
    reset_default_router()


@pytest.fixture
def intake_dirs(tmp_path):
    """Create per-pillar intake dirs in tmp_path and return their paths."""
    d = {p: tmp_path / f"{p.lower()}-intake" for p in VALID_PILLARS}
    for p in d.values():
        p.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def router(intake_dirs):
    """A PillarRouter with intake dirs in tmp_path and no webhooks."""
    cfg = {p: {"intake_dir": intake_dirs[p], "webhook_url": None} for p in VALID_PILLARS}
    return PillarRouter(config=cfg)


def _make_mandate_dict(pillar: str, mandate_id: str = "MANDATE-2026-TEST") -> dict:
    return {
        "mandate_id": mandate_id,
        "pillar": pillar,
        "priority_level": "P2",
        "title": f"Test mandate for {pillar}",
        "objective": f"Verify dispatch to {pillar}",
        "created_at": "2026-05-23T00:00:00Z",
    }


# ── Tests ─────────────────────────────────────────────────────────────────


def test_valid_pillars_is_ncc_only():
    """After 2026-05-23 retire, the router only accepts NCC."""
    assert VALID_PILLARS == ("NCC",)


@pytest.mark.parametrize("pillar", ["NCC"])
@pytest.mark.asyncio
async def test_dispatches_to_correct_intake_dir_per_pillar(router, intake_dirs, pillar):
    """The (single) valid pillar's mandate lands in its own intake dir."""
    mandate = _make_mandate_dict(pillar)
    result = await router.dispatch(mandate)

    assert result.success, f"dispatch failed: {result.errors}"
    assert result.pillar == pillar
    assert result.intake_written is True
    assert result.already_written is False
    # File landed in the right pillar's dir.
    target = intake_dirs[pillar] / f"{mandate['mandate_id']}.json"
    assert target.exists(), f"expected file at {target}, missing"
    # File content is well-formed JSON with the right pillar tag.
    payload = json.loads(target.read_text())
    assert payload["mandate_id"] == mandate["mandate_id"]
    assert payload["pillar"] == pillar
    assert "_dispatched_at" in payload


@pytest.mark.asyncio
async def test_idempotent_redispatch(router, intake_dirs):
    """Calling dispatch twice on the same mandate_id leaves one file, no error."""
    mandate = _make_mandate_dict("NCC", mandate_id="MANDATE-2026-IDEMP-001")
    r1 = await router.dispatch(mandate)
    r2 = await router.dispatch(mandate)

    assert r1.success and r2.success
    assert r1.intake_written is True
    assert r1.already_written is False
    assert r2.intake_written is False
    assert r2.already_written is True
    # Still exactly one file on disk.
    files = list(intake_dirs["NCC"].glob("MANDATE-2026-IDEMP-001*.json"))
    assert len(files) == 1, f"expected 1 intake file, got {files}"
    # Stats reflect both attempts (idempotent re-dispatch counts as success).
    stats = router.get_stats()["NCC"]
    assert stats["dispatched_total"] == 2
    assert stats["failed_total"] == 0


@pytest.mark.asyncio
async def test_circuit_breaker_skips_after_3_failures(router, intake_dirs, monkeypatch):
    """3 consecutive write failures open the breaker; further calls short-circuit."""

    # Monkey-patch the file write to always blow up.
    def _boom(self, intake_dir, mandate_id, mandate_dict):
        raise OSError("simulated disk full")

    monkeypatch.setattr(PillarRouter, "_write_intake_file", _boom)

    failures = []
    for i in range(3):
        r = await router.dispatch(_make_mandate_dict("NCC", f"MANDATE-FAIL-{i}"))
        assert r.success is False
        assert r.circuit_open is False  # First 3 fail through, then breaker opens
        failures.append(r)

    # 4th attempt should short-circuit — breaker is OPEN, no write attempted.
    r4 = await router.dispatch(_make_mandate_dict("NCC", "MANDATE-FAIL-4"))
    assert r4.success is False
    assert r4.circuit_open is True
    assert any("circuit_open" in e for e in r4.errors)

    stats = router.get_stats()["NCC"]
    assert stats["circuit_open"] is True
    assert stats["consecutive_failures"] >= 3
    assert stats["failed_total"] == 4
    assert stats["dispatched_total"] == 0


@pytest.mark.asyncio
async def test_unknown_pillar_raises(router):
    """A mandate with an invalid pillar name is rejected with UnknownPillarError."""
    bad = _make_mandate_dict("INVALID", "MANDATE-BAD")
    with pytest.raises(UnknownPillarError):
        await router.dispatch(bad)

    # Empty pillar field also rejected.
    bad2 = _make_mandate_dict("", "MANDATE-EMPTY")
    with pytest.raises(UnknownPillarError):
        await router.dispatch(bad2)


@pytest.mark.parametrize("retired", ["BRS", "AAC", "brs", "aac"])
@pytest.mark.asyncio
async def test_brs_aac_rejected_with_unknown_pillar_error(router, retired):
    """Retired pillars (BRS/AAC) are rejected with a clear UnknownPillarError."""
    mandate = _make_mandate_dict(retired, f"MANDATE-RETIRED-{retired.upper()}")
    with pytest.raises(UnknownPillarError) as exc_info:
        await router.dispatch(mandate)
    msg = str(exc_info.value)
    assert "retired" in msg.lower()
    assert retired.upper() in msg


@pytest.mark.parametrize("retired", ["BRS", "AAC", "brs", "aac"])
def test_brs_aac_rejected_at_pillartype_enum(retired):
    """PillarType no longer carries BRS / AAC members."""
    with pytest.raises(ValueError):
        PillarType(retired)
    # And constructing a Mandate with the retired pillar string blows up.
    with pytest.raises(ValueError):
        Mandate(
            mandate_id=f"MANDATE-2026-{retired.upper()}-001",
            pillar=retired,
            priority=2,
            title="Should not construct",
            objective="Should fail at validation",
        )


def test_requeue_failed_mandate_transitions_to_draft():
    """Mandate model: FAILED → DRAFT is now a legal one-way escape valve."""
    m = Mandate(
        mandate_id="MANDATE-2026-REQ-001",
        pillar=PillarType.NCC,
        priority=2,
        title="Test mandate",
        objective="Confirm requeue model transition works",
    )
    # Walk a normal lifecycle: DRAFT → PENDING_APPROVAL → ACTIVE → IN_PROGRESS → FAILED.
    m.transition_to(MandateStatus.PENDING_APPROVAL, reason="ready for review")
    m.transition_to(MandateStatus.ACTIVE, reason="approved")
    m.transition_to(MandateStatus.IN_PROGRESS, reason="dispatched")
    m.transition_to(MandateStatus.FAILED, reason="pillar webhook unreachable")
    assert m.status == MandateStatus.FAILED
    pre_version = m.version

    # The one-way escape valve.
    m.transition_to(MandateStatus.DRAFT, reason="manual requeue")
    assert m.status == MandateStatus.DRAFT
    assert m.version == pre_version + 1
    # Status history records the requeue.
    last = m.status_history[-1]
    assert last["from"] == "failed"
    assert last["to"] == "draft"
    assert "requeue" in (last["reason"] or "").lower()


def test_failed_cannot_jump_straight_to_active():
    """Sanity check: requeue is the ONLY exit from FAILED — not ACTIVE/IN_PROGRESS."""
    m = Mandate(
        mandate_id="MANDATE-2026-REQ-002",
        pillar=PillarType.NCC,
        priority=3,
        title="Test mandate",
        objective="Confirm requeue is narrow",
    )
    m.transition_to(MandateStatus.PENDING_APPROVAL)
    m.transition_to(MandateStatus.ACTIVE)
    m.transition_to(MandateStatus.FAILED, reason="boom")

    for target in (
        MandateStatus.ACTIVE,
        MandateStatus.IN_PROGRESS,
        MandateStatus.COMPLETED,
        MandateStatus.PENDING_APPROVAL,
    ):
        with pytest.raises(ValueError, match="Invalid mandate transition"):
            m.transition_to(target)
    # But DRAFT works.
    m.transition_to(MandateStatus.DRAFT, reason="requeue")
    assert m.status == MandateStatus.DRAFT


@pytest.mark.asyncio
async def test_dispatch_accepts_pydantic_model(router, intake_dirs):
    """The router should accept either a dict or a Pydantic Mandate."""
    m = Mandate(
        mandate_id="MANDATE-2026-PYD-001",
        pillar=PillarType.NCC,
        priority=2,
        title="Pydantic mandate",
        objective="Confirm coercion path",
    )
    result = await router.dispatch(m)
    assert result.success
    target = intake_dirs["NCC"] / "MANDATE-2026-PYD-001.json"
    assert target.exists()
    payload = json.loads(target.read_text())
    # PillarType.NCC serializes to "ncc" via model_dump — normalized to "NCC"
    # for routing but the file contents preserve the original lowercased
    # value (since we pass the model_dump payload through verbatim).
    assert payload["pillar"].upper() == "NCC"


@pytest.mark.asyncio
async def test_health_check_reports_intake_writable(router, intake_dirs):
    """health_check returns a stable shape for each pillar."""
    info = await router.health_check("NCC")
    assert info["pillar"] == "NCC"
    assert info["intake_dir"] == str(intake_dirs["NCC"])
    assert info["intake_writable"] is True
    assert info["webhook_url"] is None
    assert info["circuit_open"] is False


@pytest.mark.asyncio
async def test_health_check_rejects_unknown_pillar(router):
    with pytest.raises(UnknownPillarError):
        await router.health_check("BOGUS")


@pytest.mark.parametrize("retired", ["BRS", "AAC"])
@pytest.mark.asyncio
async def test_health_check_rejects_retired_pillars(router, retired):
    """BRS/AAC health checks raise UnknownPillarError with a retirement note."""
    with pytest.raises(UnknownPillarError, match="retired"):
        await router.health_check(retired)
