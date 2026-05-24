"""NCL Governance Module — Action Permission Model v1.

Provides Suggest/Draft/Execute permission tiers with PolicyKernel enforcement.
Execute-tier actions require explicit NATRIX consent before proceeding.
"""

from .action_router import ActionRouter
from .models import (
    Action,
    ActionTier,
    AuditEntry,
    ConsentStatus,
    PolicyRule,
    PolicyVerdict,
)
from .policy_kernel import PolicyKernel


__all__ = [
    "Action",
    "ActionTier",
    "ActionRouter",
    "AuditEntry",
    "ConsentStatus",
    "PolicyKernel",
    "PolicyRule",
    "PolicyVerdict",
]
