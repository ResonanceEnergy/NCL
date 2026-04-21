"""Action Permission Model v1 — Suggest / Draft / Execute tiers.

Every action in the NCL pipeline declares its tier. Execute-tier actions
require explicit NATRIX consent before proceeding. PolicyKernel enforces
this boundary at runtime.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid as _uuid

from pydantic import BaseModel, Field


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


class PolicyRule(BaseModel):
    """A rule in the PolicyKernel rule set."""

    rule_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    description: str
    tier: ActionTier = Field(..., description="Which tier this rule governs")
    condition: str = Field(..., description="Condition expression (action name pattern or *)")
    verdict: PolicyVerdict
    priority: int = Field(default=50, ge=0, le=100, description="Higher = evaluated first")
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
