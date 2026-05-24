"""W8-A14 D7: Mandate load-state enum gating.

A03b (2026-05-23) retired ``PillarType.BRS`` + ``PillarType.AAC``. Any
mandate that lands in ``data/mandates.json`` with one of those values
must now fail Pydantic validation on ``Brain._load_state()``. That's why
``scripts/prune_retired_pillar_mandates.py`` exists — we ran it once and
do NOT want a future regression to silently re-accept those values and
leave the cleanup script as a no-op.

Note on field name: the deliverable spec says ``target_pillar`` but the
actual Pydantic field on ``runtime.ncl_brain.models.Mandate`` is
``pillar`` (verified 2026-05-24). Tests use the real field name. If
a future migration renames it to ``target_pillar``, update the param
names below.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from runtime.ncl_brain.models import Mandate, MandateStatus, PillarType


def _mandate_kwargs(**overrides) -> dict:
    base = dict(
        mandate_id="MND-TEST",
        pillar="ncl",
        priority=5,
        title="t",
        objective="o",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("pillar_value", ["ncl", "ncc"])
def test_load_state_accepts_supported_pillars(pillar_value: str):
    """NCL + NCC are the only two pillars still allowed (NCC for legacy)."""
    m = Mandate(**_mandate_kwargs(pillar=pillar_value))
    assert m.pillar == PillarType(pillar_value)
    assert m.status == MandateStatus.DRAFT


@pytest.mark.parametrize("retired_value", ["brs", "aac", "garbage", "BRS", "AAC"])
def test_load_state_rejects_retired_and_unknown_pillars(retired_value: str):
    """A03b: BRS/AAC must hard-fail validation when feeding ``Mandate(**dict)``.

    This is what protects ``Brain._load_state()`` from re-loading the 21
    historical BRS/AAC entries that ``scripts/prune_retired_pillar_mandates.py``
    purged. If this test ever fails because of an enum-value addition,
    NATRIX (CLAUDE.md rule #7) needs to approve resurrection explicitly.
    """
    with pytest.raises(ValidationError):
        Mandate(**_mandate_kwargs(pillar=retired_value))


def test_load_state_rejects_missing_pillar():
    """Pillar is required — no implicit default to NCL."""
    kwargs = _mandate_kwargs()
    kwargs.pop("pillar")
    with pytest.raises(ValidationError):
        Mandate(**kwargs)


def test_load_state_rejects_target_pillar_only():
    """The deliverable spec used ``target_pillar`` (legacy field name) but
    the live model uses ``pillar``. If only ``target_pillar`` is provided,
    Pydantic must complain about the missing required ``pillar`` field —
    this guards against a silent rename slipping through.
    """
    kwargs = _mandate_kwargs()
    kwargs.pop("pillar")
    kwargs["target_pillar"] = "ncl"
    with pytest.raises(ValidationError):
        Mandate(**kwargs)
