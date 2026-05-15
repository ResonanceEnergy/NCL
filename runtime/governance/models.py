"""Action Permission Model v1 — Suggest / Draft / Execute tiers.

Every action in the NCL pipeline declares its tier. Execute-tier actions
require explicit NATRIX consent before proceeding. PolicyKernel enforces
this boundary at runtime.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid as _uuid

from pydantic import BaseModel, Field, field_validator, model_validator


class ActionTier(str, Enum):
    """Action permission tiers — escalating authority levels."""
    SUGGEST = "suggest"   # Informational only — no side effects
    DRAFT = "draft"       # Creates artifacts but doesn't dispatch/execute
    EXECUTE = "execute"   # Side effects: dispatches mandates, triggers pipelines, spends budget


class ConsentStatus(str, Enum):
    """Consent tracking for Execute-tier actions."""
    NOT_REQUIRED = "not_required"  # Suggest/Draft tier
    PENDING = "pending"            # Awaiting NATRIX approval
    GRANTED = "granted"            # NATRIX approved
    DENIED = "denied"              # NATRIX rejected
    EXPIRED = "expired"            # Consent window elapsed (default 1 hour)
    REVOKED = "revoked"            # Previously granted, then revoked


class PolicyVerdict(str, Enum):
    """PolicyKernel enforcement verdict."""
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_CONSENT = "require_consent"
    RATE_LIMITED = "rate_limited"


class Action(BaseModel):
    """An action in the NCL pipeline with declared permission tier."""

    action_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str = Field(..., description="Action name (e.g., 'dispatch_mandate', 'spawn_council')")
    tier: ActionTier = Field(..., description="Permission tier")
    source_agent: str = Field(..., description="Agent requesting the action")
    target: Optional[str] = Field(default=None, description="Target system/pillar")
    description: str = Field(default="", description="Human-readable description")
    payload: dict[str, Any] = Field(default_factory=dict)

    # Consent tracking
    consent_status: ConsentStatus = Field(default=ConsentStatus.NOT_REQUIRED)
    consent_granted_by: Optional[str] = Field(default=None)
    consent_granted_at: Optional[datetime] = Field(default=None)
    consent_expires_at: Optional[datetime] = Field(default=None)

    # Audit
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    executed_at: Optional[datetime] = Field(default=None)
    blocked_reason: Optional[str] = Field(default=None)

    # Provenance
    pump_id: Optional[str] = Field(default=None)
    mandate_id: Optional[str] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Action name must not be empty")
        return v.strip()

    @field_validator("source_agent")
    @classmethod
    def source_agent_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_agent must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def execute_tier_consent_defaults(self) -> "Action":
        """Execute-tier actions default to NOT_REQUIRED only if consent not otherwise set."""
        # Suggest/Draft should always be NOT_REQUIRED
        if self.tier in (ActionTier.SUGGEST, ActionTier.DRAFT):
            self.consent_status = ConsentStatus.NOT_REQUIRED
        return self

    def __repr__(self) -> str:
        return (
            f"Action(action_id={self.action_id!r}, name={self.name!r}, "
            f"tier={self.tier.value!r}, source_agent={self.source_agent!r}, "
            f"consent_status={self.consent_status.value!r})"
        )


class PolicyRule(BaseModel):
    """A rule in the PolicyKernel rule set."""

    rule_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str = Field(..., description="Unique human-readable name for this rule")
    description: str = Field(..., description="What this rule enforces")
    tier: ActionTier = Field(..., description="Which tier this rule governs")
    condition: str = Field(..., description="Condition expression (action name pattern or *)")
    verdict: PolicyVerdict = Field(..., description="Verdict to return when rule matches")
    priority: int = Field(default=50, ge=0, le=100, description="Higher = evaluated first")
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Rule name must not be empty")
        return v.strip()

    @field_validator("condition")
    @classmethod
    def condition_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Rule condition must not be empty")
        return v.strip()

    def __repr__(self) -> str:
        return (
            f"PolicyRule(rule_id={self.rule_id!r}, name={self.name!r}, "
            f"tier={self.tier.value!r}, condition={self.condition!r}, "
            f"verdict={self.verdict.value!r}, priority={self.priority}, "
            f"enabled={self.enabled})"
        )


class AuditEntry(BaseModel):
    """Audit log entry for PolicyKernel decisions."""

    entry_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    action_id: str
    action_name: str
    tier: ActionTier
    verdict: PolicyVerdict
    reason: str
    consent_status: ConsentStatus
    source_agent: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"AuditEntry(entry_id={self.entry_id!r}, action_name={self.action_name!r}, "
            f"tier={self.tier.value!r}, verdict={self.verdict.value!r}, "
            f"timestamp={self.timestamp.isoformat()!r})"
        )
