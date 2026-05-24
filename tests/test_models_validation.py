"""W8-A14 D7: PumpPrompt + PillarType validation invariants.

These tests lock in two security/governance invariants:

1. ``PumpPrompt.prompt_id`` must reject anything outside the
   ``^[A-Za-z0-9_-]{1,64}$`` charset. The Brain persists pumps to
   ``pump-{prompt_id}.json`` and any path-traversal sequence here lets a
   caller write outside the pump dir.

2. ``PillarType`` has been pruned to ``NCL`` + ``NCC`` (A03b, 2026-05-23).
   Constructing ``BRS`` / ``AAC`` must hard-fail so retired-pillar mandates
   stop slipping back into ``data/mandates.json``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runtime.ncl_brain.models import PillarType, PumpPrompt


# ── PumpPrompt.prompt_id ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../etc/passwd",
        "pump/../",
        "with space",
        "with\nnewline",
        "tab\there",
        "../escape",
        "a/b/c",
        "name;rm -rf /",
        "$(whoami)",
        "name`backtick`",
        "..",
        ".",
        "",  # empty — violates min_length=1
        "x" * 65,  # too long — violates max_length=64
        "unicode-‮sneaky",
    ],
)
def test_prompt_id_rejects_unsafe(bad_id: str):
    with pytest.raises(ValidationError):
        PumpPrompt(prompt_id=bad_id, source="grok-iphone", intent="test")


@pytest.mark.parametrize(
    "good_id",
    [
        "abc_123-def",
        "P-001",
        "a",  # min length 1
        "x" * 64,  # max length 64
        "MixedCase_ID-42",
        "0",
        "_",
        "-",
        "______",
    ],
)
def test_prompt_id_accepts_safe(good_id: str):
    p = PumpPrompt(prompt_id=good_id, source="grok-iphone", intent="test")
    assert p.prompt_id == good_id


# ── PillarType retirement ──────────────────────────────────────────────────


def test_pillar_type_has_only_ncl_and_ncc():
    """A03b (2026-05-23) retired BRS + AAC. Enum must reflect that."""
    values = {member.value for member in PillarType}
    assert values == {"ncl", "ncc"}, (
        f"PillarType enum drifted: got {values}. Expected exactly NCL+NCC. "
        f"If you need BRS/AAC back, that's a separate explicit decision "
        f"(CLAUDE.md rule #7)."
    )


def test_pillar_type_accepts_ncl_and_ncc():
    assert PillarType("ncl") == PillarType.NCL
    assert PillarType("ncc") == PillarType.NCC


@pytest.mark.parametrize("retired", ["brs", "aac", "BRS", "AAC", "garbage", ""])
def test_pillar_type_rejects_retired_and_unknown(retired: str):
    with pytest.raises(ValueError):
        PillarType(retired)


def test_pillar_type_does_not_expose_legacy_attrs():
    """No ``PillarType.BRS`` / ``PillarType.AAC`` class attributes either.

    Catches the case where someone re-adds them as soft aliases without
    updating the value set.
    """
    assert not hasattr(PillarType, "BRS"), "PillarType.BRS resurrected"
    assert not hasattr(PillarType, "AAC"), "PillarType.AAC resurrected"
