"""PolicyKernel — runtime enforcement engine for Action Permission Model v1.

The PolicyKernel evaluates actions against rule sets, enforces consent boundaries,
tracks audit logs, and manages pending approvals. All Execute-tier actions require
explicit NATRIX consent before proceeding.
"""
import asyncio
import json
import logging
import os
import tempfile
import threading
from collections import deque
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

logger = logging.getLogger(__name__)

# Audit log rotation thresholds
_AUDIT_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_AUDIT_LOG_MAX_ENTRIES = 10_000

# Required fields every submitted PolicyRule must have
_REQUIRED_RULE_FIELDS = {"name", "description", "tier", "condition", "verdict"}


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

    AUDIT_LOG_MAX = 10_000  # Max in-memory audit entries

    def __init__(self, data_dir: str | Path):
        """Initialize PolicyKernel with rule set and audit log paths."""
        self.data_dir = Path(data_dir)
        self.governance_dir = self.data_dir / "governance"
        self.rules: list[PolicyRule] = []
        self.pending_actions: dict[str, Action] = {}
        # Bounded deque — oldest entries are automatically dropped when full
        self.audit_log: deque[AuditEntry] = deque(maxlen=self.AUDIT_LOG_MAX)
        self._emergency_stop = False
        self._emergency_stop_controller = None  # Optional EmergencyStop instance
        self._pending_actions_file = self.governance_dir / "pending_actions.json"
        # Reentrant lock protecting pending_actions, audit_log, rules, and _emergency_stop
        self._lock = threading.RLock()

    def register_emergency_stop(self, emergency_stop) -> None:
        """Register an EmergencyStop controller for check_action logging."""
        self._emergency_stop_controller = emergency_stop

    async def init(self) -> None:
        """Create directories and load rules asynchronously."""
        self.governance_dir.mkdir(parents=True, exist_ok=True)

        # Load built-in rules
        self.rules = [rule.model_copy() for rule in self.DEFAULT_RULES]

        # Load custom rules if they exist
        rules_file = self.governance_dir / "policy_rules.json"
        if rules_file.exists():
            try:
                rules_data = json.loads(
                    await asyncio.to_thread(rules_file.read_bytes)
                )
                custom_rules = [PolicyRule(**rule) for rule in rules_data]
                self.rules.extend(custom_rules)
                # Sort by priority descending
                self.rules.sort(key=lambda r: r.priority, reverse=True)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load policy rules: %s", e)

        # Load audit log if it exists — only keep last AUDIT_LOG_MAX lines
        audit_file = self.governance_dir / "audit_log.jsonl"
        if audit_file.exists():
            try:
                raw_log = await asyncio.to_thread(audit_file.read_text)
                for line in raw_log.splitlines():
                    if line.strip():
                        entry_data = json.loads(line)
                        self.audit_log.append(AuditEntry(**entry_data))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load audit log: %s", e)

        # Load persisted pending_actions
        if self._pending_actions_file.exists():
            try:
                actions_data = json.loads(
                    await asyncio.to_thread(self._pending_actions_file.read_bytes)
                )
                for action_dict in actions_data:
                    action = Action(**action_dict)
                    self.pending_actions[action.action_id] = action
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load pending actions: %s", e)

        # Check emergency stop flag
        self._emergency_stop = self._check_emergency_stop()

    # ── Policy validation ─────────────────────────────────────────────────

    @staticmethod
    def validate_rule(rule_data: dict) -> tuple[bool, str]:
        """Validate that a rule dict has all required fields.

        Returns (valid: bool, error_message: str).
        """
        missing = _REQUIRED_RULE_FIELDS - set(rule_data.keys())
        if missing:
            return False, f"Missing required fields: {sorted(missing)}"

        valid_tiers = {t.value for t in ActionTier}
        tier_val = rule_data.get("tier")
        if hasattr(tier_val, "value"):
            tier_val = tier_val.value
        if tier_val not in valid_tiers:
            return False, f"Invalid tier '{rule_data.get('tier')}'. Must be one of {sorted(valid_tiers)}"

        valid_verdicts = {v.value for v in PolicyVerdict}
        verdict_val = rule_data.get("verdict")
        if hasattr(verdict_val, "value"):
            verdict_val = verdict_val.value
        if verdict_val not in valid_verdicts:
            return False, f"Invalid verdict '{rule_data.get('verdict')}'. Must be one of {sorted(valid_verdicts)}"

        priority = rule_data.get("priority", 50)
        if not isinstance(priority, int) or not (0 <= priority <= 100):
            return False, f"priority must be an integer in [0, 100], got {priority!r}"

        name = (rule_data.get("name") or "").strip()
        if not name:
            return False, "name must be a non-empty string"

        condition = (rule_data.get("condition") or "").strip()
        if not condition:
            return False, "condition must be a non-empty string"

        return True, ""

    # ── Core evaluation ───────────────────────────────────────────────────

    def evaluate(self, action: Action) -> PolicyVerdict:
        """Evaluate an action against the policy rule set.

        Returns the PolicyVerdict that determines whether the action is allowed,
        blocked, requires consent, or is rate-limited.
        """
        with self._lock:
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
        with self._lock:
            self.pending_actions[action.action_id] = action
        self._persist_pending_actions()
        return action

    def grant_consent(self, action_id: str, granted_by: str = "NATRIX") -> Action:
        """Grant consent for a pending Execute-tier action.

        Sets consent_status to GRANTED and records who granted it and when.
        Raises ValueError if the action's request window has already expired.
        """
        with self._lock:
            if action_id not in self.pending_actions:
                raise ValueError(f"Action {action_id} not found in pending approvals")
            action = self.pending_actions[action_id]
            # Reject grant if the consent request window has already elapsed
            now = datetime.now(timezone.utc)
            if action.consent_expires_at and now >= action.consent_expires_at:
                action.consent_status = ConsentStatus.EXPIRED
                del self.pending_actions[action_id]
                self._persist_pending_actions()
                raise ValueError(
                    f"Action {action_id} consent window has expired "
                    f"(expired at {action.consent_expires_at.isoformat()})"
                )
            action.consent_status = ConsentStatus.GRANTED
            action.consent_granted_by = granted_by
            action.consent_granted_at = now
            # Consent valid for 1 hour after grant
            action.consent_expires_at = action.consent_granted_at + timedelta(hours=1)
        self._persist_pending_actions()
        return action

    def deny_consent(self, action_id: str, reason: str = "") -> Action:
        """Deny consent for a pending Execute-tier action."""
        with self._lock:
            if action_id not in self.pending_actions:
                raise ValueError(f"Action {action_id} not found in pending approvals")
            action = self.pending_actions[action_id]
            action.consent_status = ConsentStatus.DENIED
            action.blocked_reason = reason
            del self.pending_actions[action_id]
        self._persist_pending_actions()
        return action

    def revoke_consent(self, action_id: str) -> Action:
        """Revoke previously granted consent."""
        with self._lock:
            if action_id not in self.pending_actions:
                raise ValueError(f"Action {action_id} not found in pending approvals")
            action = self.pending_actions[action_id]
            if action.consent_status != ConsentStatus.GRANTED:
                raise ValueError(f"Cannot revoke consent for action in {action.consent_status} state")
            action.consent_status = ConsentStatus.REVOKED
            action.consent_expires_at = datetime.now(timezone.utc)
        self._persist_pending_actions()
        return action

    def execute_if_allowed(self, action: Action) -> tuple[bool, str]:
        """Check if an action is allowed and mark it as executed if so.

        Returns (allowed: bool, reason: str).

        ALL actions (regardless of tier) are blocked when emergency stop is active.
        """
        # Emergency stop check FIRST — applies to ALL tiers
        with self._lock:
            if self._emergency_stop:
                self._log_audit(action, PolicyVerdict.BLOCK, "Emergency stop active")
                return False, "Emergency stop active — all actions blocked"

        verdict = self.evaluate(action)

        # Suggest and Draft tier: execute if verdict allows
        if action.tier in (ActionTier.SUGGEST, ActionTier.DRAFT):
            if verdict == PolicyVerdict.BLOCK:
                self._log_audit(action, verdict, "Action blocked by policy")
                return False, "Action blocked by policy"
            action.executed_at = datetime.now(timezone.utc)
            self._log_audit(action, verdict, "Action execution allowed by tier")
            return True, "Action executed"

        # Execute tier: check consent
        if action.tier == ActionTier.EXECUTE:
            if verdict == PolicyVerdict.REQUIRE_CONSENT:
                # Check if consent already granted (thread-safe read)
                with self._lock:
                    pending = self.pending_actions.get(action.action_id)
                if pending is not None:
                    if pending.consent_status == ConsentStatus.GRANTED:
                        # Check if not expired
                        if pending.consent_expires_at and datetime.now(timezone.utc) < pending.consent_expires_at:
                            # Re-check emergency stop AFTER consent validation
                            # to close the consent-then-stop race window
                            with self._lock:
                                if self._emergency_stop:
                                    self._log_audit(
                                        action, PolicyVerdict.BLOCK,
                                        "Emergency stop activated after consent"
                                    )
                                    return False, "Emergency stop active — action blocked despite consent"
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

    async def async_execute_if_allowed(self, action: Action) -> tuple[bool, str]:
        """Async version of execute_if_allowed that also calls EmergencyStop.check_action.

        Preferred over the sync version when an event loop is available, as it
        wires in the EmergencyStop controller's check_action for audit logging.
        """
        # Delegate to EmergencyStop.check_action if controller is registered
        if self._emergency_stop_controller is not None:
            blocked = await self._emergency_stop_controller.check_action(
                action_name=action.name, action_id=action.action_id
            )
            if blocked:
                self._log_audit(action, PolicyVerdict.BLOCK, "Blocked by EmergencyStop controller")
                return False, "Emergency stop active — action blocked"

        return self.execute_if_allowed(action)

    def cleanup_expired_actions(self) -> list[str]:
        """Remove pending_actions whose request window has expired.

        An action is expired when its consent_expires_at has passed while
        still in PENDING status. Sets consent_status to EXPIRED and removes
        the entry from pending_actions.

        Returns:
            List of action_ids that were cleaned up.
        """
        now = datetime.now(timezone.utc)
        expired_ids: list[str] = []

        with self._lock:
            for action_id, action in list(self.pending_actions.items()):
                if action.consent_status != ConsentStatus.PENDING:
                    continue
                if action.consent_expires_at and now >= action.consent_expires_at:
                    action.consent_status = ConsentStatus.EXPIRED
                    expired_ids.append(action_id)
                    del self.pending_actions[action_id]

        if expired_ids:
            logger.info(
                "PolicyKernel: cleaned up %d expired pending actions: %s",
                len(expired_ids),
                expired_ids,
            )
            self._persist_pending_actions()

        return expired_ids

    def get_pending_actions(self) -> list[Action]:
        """Return all actions awaiting consent (unexpired only)."""
        with self._lock:
            return list(self.pending_actions.values())

    def get_audit_log(self, n: int = 100) -> list[AuditEntry]:
        """Return the last n audit log entries."""
        with self._lock:
            entries = list(self.audit_log)
        return entries[-n:]

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
        with self._lock:
            self.audit_log.append(entry)
        self._persist_audit(entry)

    def _sync_persist_audit(self, entry: AuditEntry) -> None:
        """Synchronous helper: append audit entry to audit_log.jsonl with rotation."""
        audit_file = self.governance_dir / "audit_log.jsonl"
        try:
            # Rotate if file exceeds size or entry-count thresholds
            if audit_file.exists():
                file_size = audit_file.stat().st_size
                if file_size >= _AUDIT_LOG_MAX_BYTES:
                    self._rotate_audit_log(audit_file)
                elif file_size > 0:
                    # Approximate entry count check (avoid reading whole file)
                    # Average entry ~500 bytes; if file > 5MB, count lines
                    if file_size > 5 * 1024 * 1024:
                        with open(audit_file, "r") as f:
                            line_count = sum(1 for _ in f)
                        if line_count >= _AUDIT_LOG_MAX_ENTRIES:
                            self._rotate_audit_log(audit_file)

            with open(audit_file, "a") as f:
                f.write(entry.model_dump_json() + "\n")
        except IOError as e:
            logger.warning("Failed to write audit log: %s", e)

    def _rotate_audit_log(self, audit_file: Path) -> None:
        """Rotate audit log: rename current file with timestamp suffix."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        rotated = audit_file.with_suffix(f".{timestamp}.jsonl")
        try:
            audit_file.rename(rotated)
            logger.info("Rotated audit log to %s", rotated)
        except IOError as e:
            logger.warning("Failed to rotate audit log: %s", e)

    def _persist_audit(self, entry: AuditEntry) -> None:
        """Append audit entry to audit_log.jsonl — runs in executor to avoid blocking."""
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._sync_persist_audit, entry)
        except RuntimeError:
            # No running event loop — fall back to sync
            self._sync_persist_audit(entry)

    async def _async_persist_audit(self, entry: AuditEntry) -> None:
        """Async version: runs file I/O off the event loop."""
        await asyncio.to_thread(self._sync_persist_audit, entry)

    def _check_emergency_stop(self) -> bool:
        """Check if emergency stop flag is set.

        Returns True if the flag file exists.
        """
        flag_file = self.governance_dir / "emergency_stop.flag"
        return flag_file.exists()

    def set_emergency_stop(self, enabled: bool = True) -> None:
        """Set or clear the emergency stop flag."""
        flag_file = self.governance_dir / "emergency_stop.flag"
        with self._lock:
            if enabled:
                flag_file.touch()
                self._emergency_stop = True
            else:
                flag_file.unlink(missing_ok=True)
                self._emergency_stop = False

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a custom rule to the rule set after validation."""
        rule_data = {
            "name": rule.name,
            "description": rule.description,
            "tier": rule.tier,
            "condition": rule.condition,
            "verdict": rule.verdict,
            "priority": rule.priority,
        }
        valid, err = self.validate_rule(rule_data)
        if not valid:
            raise ValueError(f"Invalid policy rule: {err}")
        with self._lock:
            self.rules.append(rule)
            self.rules.sort(key=lambda r: r.priority, reverse=True)
        self._persist_rules()

    def remove_rule(self, rule_id: str) -> None:
        """Remove a rule by ID."""
        with self._lock:
            self.rules = [r for r in self.rules if r.rule_id != rule_id]
        self._persist_rules()

    def _sync_persist_pending_actions(self) -> None:
        """Synchronous helper: persist pending_actions to JSON file (atomic)."""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.governance_dir), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(
                        [action.model_dump() for action in self.pending_actions.values()],
                        f,
                        indent=2,
                        default=str,
                    )
                os.rename(tmp_path, str(self._pending_actions_file))
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except IOError as e:
            logger.warning("Failed to persist pending actions: %s", e)

    def _persist_pending_actions(self) -> None:
        """Persist pending_actions — runs in executor to avoid blocking."""
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._sync_persist_pending_actions)
        except RuntimeError:
            self._sync_persist_pending_actions()

    async def _async_persist_pending_actions(self) -> None:
        """Async version: runs file I/O off the event loop."""
        await asyncio.to_thread(self._sync_persist_pending_actions)

    def _sync_persist_rules(self) -> None:
        """Synchronous helper: persist custom rules to policy_rules.json (atomic)."""
        rules_file = self.governance_dir / "policy_rules.json"
        # Only persist non-default rules
        custom_rules = [
            r for r in self.rules
            if r not in self.DEFAULT_RULES
        ]
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.governance_dir), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(
                        [rule.model_dump() for rule in custom_rules],
                        f,
                        indent=2,
                        default=str,
                    )
                os.rename(tmp_path, str(rules_file))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except IOError as e:
            logger.warning("Failed to write policy rules: %s", e)

    def _persist_rules(self) -> None:
        """Persist custom rules — runs in executor to avoid blocking."""
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._sync_persist_rules)
        except RuntimeError:
            self._sync_persist_rules()

    async def _async_persist_rules(self) -> None:
        """Async version: runs file I/O off the event loop."""
        await asyncio.to_thread(self._sync_persist_rules)
