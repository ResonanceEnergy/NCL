"""W8-A14 D7: ``OutcomeBody`` schema for /prediction/{id}/outcome.

iOS (``PredictionDetailView.swift:669``) sends
``{"outcome": "correct"|"incorrect"|"partial"}`` — this is the primary
path. Legacy callers send the boolean pair
``{"correct": true|false, "partial": true|false}``. The model has to
keep accepting BOTH shapes or accuracy reporting silently breaks on
either the iOS or curl side.

Note on the deliverable: the spec asked us to verify that
``{"outcome": "garbage"}`` is REJECTED. As of 2026-05-24 the live
``OutcomeBody`` declares ``outcome: Optional[str]`` with no Literal /
enum constraint, so garbage is accepted at the schema layer (the route
handler validates the string downstream). We mark that assertion as
``xfail`` so the regression is visible without breaking CI, and we
include a passing assertion against the documented happy-path values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runtime.api.routers.intel import OutcomeBody


@pytest.mark.parametrize("value", ["correct", "incorrect", "partial"])
def test_outcome_body_accepts_documented_strings(value: str):
    """The three documented iOS values must validate."""
    body = OutcomeBody(outcome=value)
    assert body.outcome == value


def test_outcome_body_accepts_legacy_boolean_shape():
    """Back-compat: ``{"correct": true, "partial": false}`` still validates.

    Curl debugging + older tooling depend on this — don't break it just
    because iOS migrated to the string shape.
    """
    body = OutcomeBody(correct=True, partial=False)
    assert body.correct is True
    assert body.partial is False
    assert body.outcome is None


def test_outcome_body_accepts_empty_payload():
    """Either shape is optional — handler falls back to query params."""
    body = OutcomeBody()
    assert body.outcome is None
    assert body.correct is None
    assert body.partial is None


def test_outcome_body_round_trip():
    """JSON round-trip preserves all three fields."""
    raw = {"outcome": "correct", "correct": None, "partial": None}
    body = OutcomeBody(**raw)
    dumped = body.model_dump()
    assert dumped["outcome"] == "correct"


@pytest.mark.xfail(
    reason=(
        "OutcomeBody.outcome is declared Optional[str] with no Literal / "
        "validator constraint — schema layer accepts arbitrary strings. "
        "Tighten to Literal['correct','incorrect','partial'] or add a "
        "field_validator to reject 'garbage' at the model layer."
    ),
    strict=True,
)
def test_outcome_body_rejects_garbage_outcome_string():
    """If the model is tightened with a Literal/validator, this flips to passing
    and the ``strict=True`` xfail will fail the suite — that's the signal to
    delete the xfail marker.
    """
    with pytest.raises(ValidationError):
        OutcomeBody(outcome="garbage")


def test_outcome_body_partial_flag_via_string():
    """The string ``"partial"`` is the canonical half-credit shape."""
    body = OutcomeBody(outcome="partial")
    assert body.outcome == "partial"
