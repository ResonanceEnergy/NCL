"""ActionRouter — convenience layer wrapping PolicyKernel.

Provides simple methods for creating and routing actions through the
permission enforcement pipeline. Handles Suggest/Draft/Execute tiers
with automatic consent tracking for Execute-tier actions.
"""
from typing import Any, Optional

from .models import Action, ActionTier, ConsentStatus, PolicyVerdict
from .policy_kernel import PolicyKernel


class ActionRouter:
    """High-level API for routing actions through PolicyKernel enforcement."""

    def __init__(self, policy_kernel: PolicyKernel):
        """Initialize ActionRouter with a PolicyKernel instance."""
        self.kernel = policy_kernel

    def suggest(
        self,
        name: str,
        source_agent: str,
        description: str = "",
        payload: Optional[dict[str, Any]] = None,
        target: Optional[str] = None,
    ) -> Action:
        """Create and auto-evaluate a Suggest-tier action.

        Suggest-tier actions are informational only and always allowed.
        No side effects, no consent required.
        """
        action = Action(
            name=name,
            tier=ActionTier.SUGGEST,
            source_agent=source_agent,
            description=description,
            payload=payload or {},
            target=target,
        )
        verdict = self.kernel.evaluate(action)
        self.kernel._log_audit(action, verdict, "Suggest-tier action created")
        return action

    def draft(
        self,
        name: str,
        source_agent: str,
        description: str = "",
        payload: Optional[dict[str, Any]] = None,
        target: Optional[str] = None,
    ) -> Action:
        """Create and auto-evaluate a Draft-tier action.

        Draft-tier actions create artifacts but don't dispatch/execute.
        No side effects on external systems, no consent required.
        """
        action = Action(
            name=name,
            tier=ActionTier.DRAFT,
            source_agent=source_agent,
            description=description,
            payload=payload or {},
            target=target,
        )
        verdict = self.kernel.evaluate(action)
        self.kernel._log_audit(action, verdict, "Draft-tier action created")
        return action

    def execute(
        self,
        name: str,
        source_agent: str,
        description: str = "",
        payload: Optional[dict[str, Any]] = None,
        target: Optional[str] = None,
        pump_id: Optional[str] = None,
        mandate_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Action:
        """Create and evaluate an Execute-tier action.

        Execute-tier actions have side effects (dispatch mandates, trigger pipelines,
        spend budget). Requires explicit NATRIX consent before proceeding.

        Returns the action with consent_status = PENDING if consent is needed.
        """
        action = Action(
            name=name,
            tier=ActionTier.EXECUTE,
            source_agent=source_agent,
            description=description,
            payload=payload or {},
            target=target,
            pump_id=pump_id,
            mandate_id=mandate_id,
            correlation_id=correlation_id,
        )

        verdict = self.kernel.evaluate(action)

        if verdict == PolicyVerdict.REQUIRE_CONSENT:
            # Mark as pending and store for approval
            action = self.kernel.request_consent(action)
            self.kernel._log_audit(
                action, verdict, "Execute-tier action created, awaiting NATRIX consent"
            )
        else:
            self.kernel._log_audit(action, verdict, "Execute-tier action created")

        return action

    def route(self, action: Action) -> PolicyVerdict:
        """Evaluate and audit an action in one call.

        Returns the PolicyVerdict for the action.
        """
        verdict = self.kernel.evaluate(action)
        self.kernel._log_audit(action, verdict, "Action routed through policy engine")
        return verdict

    def get_pending(self) -> list[Action]:
        """Return all actions awaiting approval."""
        return self.kernel.get_pending_actions()

    def approve(self, action_id: str, approver: str = "NATRIX") -> Action:
        """Approve a pending Execute-tier action.

        Grants consent and allows the action to proceed.
        """
        action = self.kernel.grant_consent(action_id, granted_by=approver)
        self.kernel._log_audit(
            action,
            PolicyVerdict.ALLOW,
            f"Consent granted by {approver}",
        )
        return action

    def reject(self, action_id: str, reason: str = "") -> Action:
        """Reject a pending Execute-tier action.

        Denies consent and blocks the action.
        """
        action = self.kernel.deny_consent(action_id, reason=reason)
        self.kernel._log_audit(
            action,
            PolicyVerdict.BLOCK,
            f"Consent denied: {reason}",
        )
        return action
