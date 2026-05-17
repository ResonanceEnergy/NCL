"""NCL Brain package."""

__version__ = "1.0.0"
__author__ = "NATRIX / NCL"
__description__ = "RESONANCE ENERGY NCL Brain Service - Think, Research, Plan, Decide"

__all__ = [
    "NCLBrain",
    "CouncilEngine",
    "NCLEvent",
    "EventType",
    "ProvenanceEnvelope",
    "PumpPrompt",
    "Mandate",
    "MandateStatus",
    "PillarType",
    "CouncilSession",
    "CouncilMember",
    "CouncilRole",
    "CouncilStatus",
    "InsightSignal",
    "MemUnit",
    "FeedbackReport",
    "CouncilOutput",
    "ConsensusScore",
    "DebateRound",
]


def __getattr__(name: str):
    """Lazy imports to avoid triggering brain.py's env validation at import time."""
    if name == "NCLBrain":
        from .brain import NCLBrain
        return NCLBrain
    if name == "CouncilEngine":
        from .council import CouncilEngine
        return CouncilEngine
    # Models are safe to import eagerly but we use getattr for consistency
    from . import models as _models
    if hasattr(_models, name):
        return getattr(_models, name)
    raise AttributeError(f"module 'runtime.ncl_brain' has no attribute {name!r}")
