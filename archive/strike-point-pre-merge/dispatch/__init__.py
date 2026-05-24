"""Pillar dispatch — clean abstraction for routing mandates to NCC.

NCC is the only live dispatch target. BRS and AAC were retired on
2026-05-23 per NATRIX directive. See
:mod:`runtime.dispatch.pillar_router` for the public ``PillarRouter`` API.
"""

from .pillar_router import (
    DispatchError,
    DispatchResult,
    PillarRouter,
    UnknownPillarError,
    VALID_PILLARS,
    get_default_router,
    reset_default_router,
)

__all__ = [
    "DispatchError",
    "DispatchResult",
    "PillarRouter",
    "UnknownPillarError",
    "VALID_PILLARS",
    "get_default_router",
    "reset_default_router",
]
