"""PolicyKernel — runtime enforcement engine for Action Permission Model v1.

The PolicyKernel evaluates actions against rule sets, enforces consent boundaries,
tracks audit logs, and manages pending approvals. All Execute-tier actions require
explicit NATRIX consent before proceeding.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

from .models import (
    Action,
    ActionTier,
    AuditEntry,
    ConsentStatus,
    PolicyRule,
    PolicyVerdict,
)


class PolicyKernel:
    """Runtime enforcement engine for action permission tiers."""

    DEFAULT_RULES = [
        PolicyRule(
            name="suggest_always_allow",
            description="Suggest-tier actions always allowed (informational)",
            tier=ActionTier.SUGGEST,
            condition="*",
            verdict=PolicyVerdict.ALLOW,
            priority=90,
        ),
        PolicyRule(
            name="draft_allow_internal",
            description="Draft-tier actions allowed (no side effects)",
            tier=ActionTier.DRAFT,
            condition="*",
            verdict=PolicyVerdict.ALLOW,
            priority=90,
        ),
        PolicyRule(
            name="execute_requires_consent",
            description="Execute-tier actions require NATRIX consent",
            tier=ActionTier.EXECUTE,
            condition="*",
            verdict=PolicyVerdict.REQUIRE_CONSENT,
            priority=90,
        ),
    ]

    def __init__(self, data_dir: str | Path):
        """Initialize PolicyKernel with rule set and audit log paths."""
        self.data_dir = Path(data_dir)
        self.governance_dir = self.data_dir / "governance"
        self.rules: list[PolicyRule] = []
        self.pending_actions: dict[str, Action] = {}
        self.audit_log: list[AuditEntry] = []
        self._emergency_stop = False

    async def init(self) -> None:
        """Create directories and load rules asynchronously."""
        self.governance_dir.mkdir(parents=True, exist_ok=True)

        # Load built-in rules
        self.rules = [rule.model_copy() for rule in self.DEFAULT_RULES]

        # Load custom rules if they exist
        rules_file = self.governance_dir / "policy_rules.json"
        if rules_file.exists():
            try:
                with open(rules_file) as f:
                    rules_data = json.load(f)
                    custom_rules = [PolicyRule(**rule) for rule in rules_data]
                    self.rules.extend(custom_rules)
                    # Sort by priority descending
                    self.rules.sort(key=lambda r: r.priority, reverse=True)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Warning: Failed to load policy rules: {e}")

        # Load audit log if it exists
        audit_file = self.governance_dir / "audit_log.jsonl"
        if audit_file.exists():
            try:
                with open(audit_file) as f:
                    for line in f:
                        if line.strip():
                            entry_data = json.loads(line)
                            self.audit_log.append(AuditEntry(**entry_data))
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Warning: Failed to load audit log: {e}")

        # Check emergency stop flag
        self._emergency_stop = self._check_emergency_stop()

    def evaluate(self, action: Action) -> PolicyVerdict:
        """Evaluate an action against the policy rule set.

        Returns the PolicyVerdict that determines whether the action is allowed,
        blocked, requires consent, or is rate-limited.
        """
        if self._emergency_stop:
            return PolicyVerdict.BLOCK

        # Match against rules in priority order
        for rule in self.rules:
            if not rule.enabled:
                continue

            # Rule must match the action's tier
            if rule.tier != action.tier:
                continue

            # Pattern match the action name
            if fnmatch(action.name, rule.condition):
                return rule.verdict

        # Default fallback
        return PolicyVerdict.BLOCK

    def request_consent(self, action: Action) -> Action:
        """Mark an Execute-tier action as pending consent.

        Stores the action in pending_actions and updates its consent_status to PENDING.
        """
        action.consent_status = ConsentStatus.PENDING
        action.consent_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.pending_actions[action.action_id] = action
        return action

    def grant_consent(self, action_id: str, granted_by: str = "NATRIX") -> Action:
        """Grant consent for a pending Execute-tier action.

        Sets consent_status to GRANTED and records who granted it and when.
        """
        if action_id not in self.pending_actions:
            raise ValueError(f"Action {action_id} not found in pending approvals")

        action = self.pending_actions[action_id]
        action.consent_status = ConsentStatus.GRANTED
        action.consent_granted_by = granted_by
        action.consent_granted_at = datetime.now(timezone.utc)
        # Consent expires 1 hour after grant
        action.consent_expires_at = action.consent_granted_at + timedelta(hours=1)

        return action

    def deny_consent(self, action_id: str, reason: str = "") -> Action:
        """Deny consent for a pending Execute-tier action."""
        if action_id not in self.pending_actions:
            raise ValueError(f"Action {action_id} not found in pending approvals")

        action = self.pending_actions[action_id]
        action.consent_status = ConsentStatus.DENIED
        action.blocked_reason = reason
        del self.pending_actions[action_id]

        return action

    def revoke_consent(self, action_id: str) -> Action:
        """Revoke previously granted consent."""
        if action_id not in self.pending_actions:
            raise ValueError(f"Action {action_id} not found in pending approvals")

        action = self.pending_actions[action_id]
        if action.consent_status != ConsentStatus.GRANTED:
            raise ValueError(f"Cannot revoke consent for action in {action.consent_status} state")

        action.consent_status = ConsentStatus.REVOKED
        action.consent_expires_at = datetime.now(timezone.utc)

        return action

    def execute_if_allowed(self, action: Action) -> tuple[bool, str]:
        """Check if an action is allowed and mark it as executed if so.

        Returns (allowed: bool, reason: str).
        """
        verdict = self.evaluate(action)

        # Suggest and Draft tier: always execute
        if action.tier in (ActionTier.SUGGEST, ActionTier.DRAFT):
            action.executed_at = datetime.now(timezone.utc)
            self._log_audit(action, verdict, "Action execution allowed by tier")
            return True, "Action executed"

        # Execute tier: check consent
        if action.tier == ActionTier.EXECUTE:
            if verdict == PolicyVerdict.REQUIRE_CONSENT:
                # Check if consent already granted
                if action.action_id in self.pending_actions:
                    pending = self.pending_actions[action.action_id]
                    if pending.consent_status == ConsentStatus.GRANTED:
                        # Check if not expired
                        if pending.consent_expires_at and datetime.now(timezone.utc) < pending.consent_expires_at:
                            action.executed_at = datetime.now(timezone.utc)
                            self._log_audit(action, PolicyVerdict.ALLOW, "Consent granted, executing")
                            return True, "Action executed with consent"
                        else:
                            self._log_audit(
                                action, PolicyVerdict.BLOCK, "Consent expired"
                            )
                            return False, "Consent has expired"

                # No consent granted
                self._log_audit(action, verdict, "Awaiting NATRIX consent")
                return False, "Requires NATRIX consent"

            if verdict == PolicyVerdict.BLOCK:
                self._log_audit(action, verdict, "Action blocked by policy")
                return False, "Action blocked by policy"

            if verdict == PolicyVerdict.RATE_LIMITED:
                self._log_audit(action, verdict, "Rate limit exceeded")
                return False, "Rate limit exceeded"

        return False, "Unknown verdict or tier"

    def get_pending_actions(self) -> list[Action]:
        """Return all actions awaiting consent."""
        return list(self.pending_actions.values())

    def get_audit_log(self, n: int = 100) -> list[AuditEntry]:
        """Return the last n audit log entries."""
        return self.audit_log[-n:]

    def _log_audit(self, action: Action, verdict: PolicyVerdict, reason: str) -> None:
        """Create and persist an audit log entry."""
        entry = AuditEntry(
            action_id=action.action_id,
            action_name=action.name,
            tier=action.tier,
            verdict=verdict,
            reason=reason,
            consent_status=action.consent_status,
            source_agent=action.source_agent,
            metadata={
                "target": action.target,
                "pump_id": action.pump_id,
                "mandate_id": action.mandate_id,
            },
        )
        self.audit_log.append(entry)
        self._persist_audit(entry)

    def _persist_audit(self, entry: AuditEntry) -> None:
        """Append audit entry to audit_log.jsonl."""
        audit_file = self.governance_dir / "audit_log.jsonl"
        try:
            with open(audit_file, "a") as f:
                f.write(entry.model_dump_json() + "\n")
        except IOError as e:
            print(f"Warning: Failed to write audit log: {e}")

    def _check_emergency_stop(self) -> bool:
        """Check if emergency stop flag is set.

        Returns True if the flag file exists.
        """
        flag_file = self.governance_dir / "emergency_stop.flag"
        return flag_file.exists()

    def set_emergency_stop(self, enabled: bool = True) -> None:
        """Set or clear the emergency stop flag."""
        flag_file = self.governance_dir / "emergency_stop.flag"
        if enabled:
            flag_file.touch()
            self._emergency_stop = True
        else:
            flag_file.unlink(missing_ok=True)
            self._emergency_stop = False

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a custom rule to the rule set."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        self._persist_rules()

    def remove_rule(self, rule_id: str) -> None:
        """Remove a rule by ID."""
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        self._persist_rules()

    def _persist_rules(self) -> None:
        """Persist custom rules to policy_rules.json."""
        rules_file = self.governance_dir / "policy_rules.json"
        # Only persist non-default rules
        custom_rules = [
            r for r in self.rules
            if r not in self.DEFAULT_RULES
        ]
        try:
            with open(rules_file, "w") as f:
                json.dump(
                    [rule.model_dump() for rule in custom_rules],
                    f,
                    indent=2,
                    default=str,
                )
        except IOError as e:
            print(f"Warning: Failed to write policy rules: {e}")
