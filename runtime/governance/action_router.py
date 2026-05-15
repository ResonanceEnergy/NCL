"""ActionRouter — convenience layer wrapping PolicyKernel.

Provides simple methods for creating and routing actions through the
permission enforcement pipeline. Handles Suggest/Draft/Execute tiers
with automatic consent tracking for Execute-tier actions.

All dispatched actions are logged for audit trail. Execution calls
are wrapped with a configurable timeout so a stalled handler cannot
block the system indefinitely.
"""
import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from .models import Action, ActionTier, ConsentStatus, PolicyVerdict
from .policy_kernel import PolicyKernel

log = logging.getLogger("ncl.action_router")

# Default timeout (seconds) for async action execution callbacks
DEFAULT_EXECUTION_TIMEOUT = 30.0


class ActionRouter:
    """High-level API for routing actions through PolicyKernel enforcement."""

    def __init__(self, policy_kernel: PolicyKernel, execution_timeout: float = DEFAULT_EXECUTION_TIMEOUT):
        """Initialize ActionRouter with a PolicyKernel instance.

        Args:
            policy_kernel: Enforcement engine to evaluate and log actions.
            execution_timeout: Seconds before an async dispatch callback is
                cancelled.  Defaults to 30 s.
        """
        self.kernel = policy_kernel
        self.execution_timeout = execution_timeout

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
        try:
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
            log.debug("[ROUTER] suggest: %s from %s → %s", name, source_agent, verdict)
            return action
        except Exception as e:
            log.error("[ROUTER] Error creating suggest action '%s': %s", name, e, exc_info=True)
            raise

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
        try:
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
            log.debug("[ROUTER] draft: %s from %s → %s", name, source_agent, verdict)
            return action
        except Exception as e:
            log.error("[ROUTER] Error creating draft action '%s': %s", name, e, exc_info=True)
            raise

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
        try:
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
                action = self.kernel.request_consent(action)
                self.kernel._log_audit(
                    action, verdict, "Execute-tier action created, awaiting NATRIX consent"
                )
                log.info(
                    "[ROUTER] execute: %s from %s → PENDING_CONSENT (action_id=%s)",
                    name, source_agent, action.action_id,
                )
            else:
                self.kernel._log_audit(action, verdict, "Execute-tier action created")
                log.info(
                    "[ROUTER] execute: %s from %s → %s (action_id=%s)",
                    name, source_agent, verdict, action.action_id,
                )

            return action
        except Exception as e:
            log.error("[ROUTER] Error creating execute action '%s': %s", name, e, exc_info=True)
            raise

    def route(self, action: Action) -> PolicyVerdict:
        """Evaluate and audit an action in one call.

        Returns the PolicyVerdict for the action.
        """
        try:
            verdict = self.kernel.evaluate(action)
            self.kernel._log_audit(action, verdict, "Action routed through policy engine")
            log.debug(
                "[ROUTER] route: %s (tier=%s) → %s",
                action.name, action.tier, verdict,
            )
            return verdict
        except Exception as e:
            log.error(
                "[ROUTER] Error routing action '%s': %s", action.name, e, exc_info=True
            )
            raise

    async def dispatch(
        self,
        action: Action,
        handler: Callable[[Action], Coroutine],
        timeout: Optional[float] = None,
    ) -> tuple[bool, str]:
        """Dispatch an action to an async handler if policy allows.

        Wraps the handler with a timeout so a stalled execution cannot block
        the caller indefinitely.

        Args:
            action: The action to dispatch.
            handler: Async callable that receives the action and executes it.
            timeout: Override the router's default execution_timeout.

        Returns:
            (success: bool, message: str)
        """
        allowed, reason = self.kernel.execute_if_allowed(action)
        if not allowed:
            log.warning(
                "[ROUTER] dispatch BLOCKED: %s (action_id=%s) — %s",
                action.name, action.action_id, reason,
            )
            return False, reason

        effective_timeout = timeout if timeout is not None else self.execution_timeout
        log.info(
            "[ROUTER] dispatching: %s (action_id=%s, timeout=%.1fs)",
            action.name, action.action_id, effective_timeout,
        )
        try:
            await asyncio.wait_for(handler(action), timeout=effective_timeout)
            log.info(
                "[ROUTER] dispatch complete: %s (action_id=%s)",
                action.name, action.action_id,
            )
            return True, "Action dispatched successfully"
        except asyncio.TimeoutError:
            msg = (
                f"Action '{action.name}' (id={action.action_id}) timed out "
                f"after {effective_timeout:.1f}s"
            )
            log.error("[ROUTER] %s", msg)
            self.kernel._log_audit(action, PolicyVerdict.BLOCK, f"Dispatch timeout: {msg}")
            return False, msg
        except Exception as e:
            msg = f"Action '{action.name}' dispatch error: {type(e).__name__}: {e}"
            log.error("[ROUTER] %s", msg, exc_info=True)
            self.kernel._log_audit(action, PolicyVerdict.BLOCK, f"Dispatch error: {e}")
            return False, msg

    def get_pending(self) -> list[Action]:
        """Return all actions awaiting approval."""
        return self.kernel.get_pending_actions()

    def approve(self, action_id: str, approver: str = "NATRIX") -> Action:
        """Approve a pending Execute-tier action.

        Grants consent and allows the action to proceed.
        """
        try:
            action = self.kernel.grant_consent(action_id, granted_by=approver)
            self.kernel._log_audit(
                action,
                PolicyVerdict.ALLOW,
                f"Consent granted by {approver}",
            )
            log.info("[ROUTER] approve: action_id=%s by %s", action_id, approver)
            return action
        except Exception as e:
            log.error("[ROUTER] Error approving action %s: %s", action_id, e, exc_info=True)
            raise

    def reject(self, action_id: str, reason: str = "") -> Action:
        """Reject a pending Execute-tier action.

        Denies consent and blocks the action.
        """
        try:
            action = self.kernel.deny_consent(action_id, reason=reason)
            self.kernel._log_audit(
                action,
                PolicyVerdict.BLOCK,
                f"Consent denied: {reason}",
            )
            log.info("[ROUTER] reject: action_id=%s reason=%r", action_id, reason)
            return action
        except Exception as e:
            log.error("[ROUTER] Error rejecting action %s: %s", action_id, e, exc_info=True)
            raise
