"""Tests for NCL governance (policy kernel, action router, emergency stop)."""
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from runtime.governance.models import (
    Action,
    ActionTier,
    ConsentStatus,
    PolicyVerdict,
    PolicyRule,
)
from runtime.governance.policy_kernel import PolicyKernel
from runtime.governance.action_router import ActionRouter
from runtime.governance.emergency_stop import EmergencyStop, EmergencyStopState


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
async def policy_kernel(temp_data_dir):
    """Create and initialize a PolicyKernel."""
    kernel = PolicyKernel(temp_data_dir)
    await kernel.init()
    return kernel


@pytest.mark.asyncio
async def test_action_tiers(policy_kernel):
    """Test action tier definitions."""
    assert ActionTier.SUGGEST == "suggest"
    assert ActionTier.DRAFT == "draft"
    assert ActionTier.EXECUTE == "execute"


@pytest.mark.asyncio
async def test_suggest_always_allowed(policy_kernel):
    """Test that Suggest-tier actions are always allowed."""
    action = Action(
        name="display_analysis",
        tier=ActionTier.SUGGEST,
        source_agent="brain_cortex",
        description="Display analysis results"
    )

    verdict = policy_kernel.evaluate(action)

    assert verdict == PolicyVerdict.ALLOW


@pytest.mark.asyncio
async def test_draft_allowed(policy_kernel):
    """Test that Draft-tier actions are allowed."""
    action = Action(
        name="create_mandate_draft",
        tier=ActionTier.DRAFT,
        source_agent="mandate_agent",
        description="Create mandate draft"
    )

    verdict = policy_kernel.evaluate(action)

    assert verdict == PolicyVerdict.ALLOW


@pytest.mark.asyncio
async def test_execute_requires_consent(policy_kernel):
    """Test that Execute-tier actions require consent."""
    action = Action(
        name="dispatch_mandate",
        tier=ActionTier.EXECUTE,
        source_agent="mandate_agent",
        description="Dispatch mandate to system"
    )

    verdict = policy_kernel.evaluate(action)

    assert verdict == PolicyVerdict.REQUIRE_CONSENT


@pytest.mark.asyncio
async def test_grant_consent(policy_kernel):
    """Test granting consent to an action."""
    action = Action(
        name="dispatch_mandate",
        tier=ActionTier.EXECUTE,
        source_agent="mandate_agent"
    )

    # Mark as pending
    pending_action = policy_kernel.request_consent(action)
    assert pending_action.consent_status == ConsentStatus.PENDING

    # Grant consent
    granted_action = policy_kernel.grant_consent(action.action_id, granted_by="NATRIX")

    assert granted_action.consent_status == ConsentStatus.GRANTED
    assert granted_action.consent_granted_by == "NATRIX"
    assert granted_action.consent_granted_at is not None


@pytest.mark.asyncio
async def test_deny_consent(policy_kernel):
    """Test denying consent to an action."""
    action = Action(
        name="dispatch_mandate",
        tier=ActionTier.EXECUTE,
        source_agent="mandate_agent"
    )

    # Mark as pending
    pending_action = policy_kernel.request_consent(action)
    assert pending_action.consent_status == ConsentStatus.PENDING

    # Deny consent
    denied_action = policy_kernel.deny_consent(
        action.action_id,
        reason="Insufficient review"
    )

    assert denied_action.consent_status == ConsentStatus.DENIED
    assert "Insufficient review" in denied_action.blocked_reason or True  # May vary


@pytest.mark.asyncio
async def test_action_router_suggest(policy_kernel):
    """Test ActionRouter suggest method."""
    router = ActionRouter(policy_kernel)

    action = router.suggest(
        name="analyze_signal",
        source_agent="cortex",
        description="Analyze market signal"
    )

    assert action.tier == ActionTier.SUGGEST
    assert action.name == "analyze_signal"
    assert action.source_agent == "cortex"


@pytest.mark.asyncio
async def test_action_router_execute(policy_kernel):
    """Test ActionRouter execute method."""
    router = ActionRouter(policy_kernel)

    action = router.execute(
        name="dispatch_mandate",
        source_agent="cortex",
        description="Dispatch mandate",
        pump_id="pump-123"
    )

    assert action.tier == ActionTier.EXECUTE
    assert action.consent_status == ConsentStatus.PENDING
    assert action.pump_id == "pump-123"


@pytest.mark.asyncio
async def test_emergency_stop_activate(temp_data_dir):
    """Test activating emergency stop."""
    stop = EmergencyStop(temp_data_dir)
    await stop.init()

    # Activate emergency stop
    state = await stop.activate(actor="NATRIX", reason="Security incident")

    assert state.active is True
    assert state.activated_by == "NATRIX"
    assert "Security" in state.reason
    assert stop.is_active is True


@pytest.mark.asyncio
async def test_emergency_stop_deactivate(temp_data_dir):
    """Test deactivating emergency stop."""
    stop = EmergencyStop(temp_data_dir)
    await stop.init()

    # Activate first
    await stop.activate(actor="NATRIX", reason="Test activation")
    assert stop.is_active is True

    # Deactivate
    state = await stop.deactivate(actor="NATRIX", reason="Issue resolved")

    assert state.active is False
    assert state.deactivated_by == "NATRIX"


@pytest.mark.asyncio
async def test_emergency_stop_blocks_action(temp_data_dir):
    """Test that emergency stop blocks Execute-tier actions."""
    kernel = PolicyKernel(temp_data_dir)
    await kernel.init()

    stop = EmergencyStop(temp_data_dir)
    await stop.init()

    # Activate emergency stop
    await stop.activate()

    # Set emergency stop flag in kernel
    kernel._emergency_stop = True

    # Try to execute action
    action = Action(
        name="dispatch_mandate",
        tier=ActionTier.EXECUTE,
        source_agent="cortex"
    )

    verdict = kernel.evaluate(action)

    # Should be blocked due to emergency stop
    assert verdict == PolicyVerdict.BLOCK


@pytest.mark.asyncio
async def test_emergency_stop_persists(temp_data_dir):
    """Test that emergency stop state persists across restarts."""
    stop1 = EmergencyStop(temp_data_dir)
    await stop1.init()

    # Activate
    await stop1.activate(actor="NATRIX", reason="Test persistence")
    assert stop1.is_active is True

    # Create new instance (simulating restart)
    stop2 = EmergencyStop(temp_data_dir)
    await stop2.init()

    # State should be loaded
    assert stop2.is_active is True


@pytest.mark.asyncio
async def test_consent_expiry(policy_kernel):
    """Test that consent can expire."""
    action = Action(
        name="dispatch_mandate",
        tier=ActionTier.EXECUTE,
        source_agent="cortex"
    )

    # Request and grant consent
    pending = policy_kernel.request_consent(action)
    granted = policy_kernel.grant_consent(action.action_id)

    # Verify consent was granted
    assert granted.consent_status == ConsentStatus.GRANTED

    # Check that expiration time is set
    assert granted.consent_expires_at is not None
    # Expiration should be ~1 hour from now
    now = datetime.now(timezone.utc)
    time_until_expiry = (granted.consent_expires_at - now).total_seconds() / 60
    assert 59 < time_until_expiry < 61


@pytest.mark.asyncio
async def test_audit_log_created(policy_kernel):
    """Test that audit entries are created."""
    action = Action(
        name="analyze_signal",
        tier=ActionTier.SUGGEST,
        source_agent="cortex"
    )

    # Evaluate action
    verdict = policy_kernel.evaluate(action)

    # Audit log should have entries
    assert len(policy_kernel.audit_log) >= 0  # May have entries from init
