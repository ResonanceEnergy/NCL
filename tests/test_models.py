"""Tests for NCL models."""
import pytest
from runtime.ncl_brain.models import (
    PumpPrompt, Mandate, MandateStatus, PillarType,
    CouncilSession, CouncilStatus, ConsensusScore,
)


def test_pump_prompt_creation():
    p = PumpPrompt(prompt_id="P-001", source="grok-iphone", intent="Test intent")
    assert p.prompt_id == "P-001"
    assert p.urgency == "normal"


def test_mandate_creation():
    m = Mandate(
        mandate_id="MND-001",
        pillar=PillarType.BRS,
        priority=7,
        title="Test mandate",
        objective="Test objective",
    )
    assert m.status == MandateStatus.DRAFT
    assert m.pillar == PillarType.BRS


def test_mandate_status_values():
    assert MandateStatus.PENDING_APPROVAL == "pending_approval"
    assert MandateStatus.ACTIVE == "active"
    assert MandateStatus.CANCELLED == "cancelled"


def test_council_session_defaults():
    s = CouncilSession(session_id="CS-001", topic="Test", prompt="Test prompt")
    assert s.status == CouncilStatus.PENDING
    assert len(s.members) == 6
    assert s.chair == "claude"


def test_consensus_score_bounds():
    with pytest.raises(Exception):
        ConsensusScore(agreement_pct=101.0)
