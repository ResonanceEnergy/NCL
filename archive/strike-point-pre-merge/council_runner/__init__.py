"""Council Runner v1 — Planner/Skeptic/Risk parallel agents.

Three specialized agents run in parallel on the same prompt.
Their outputs merge into consensus + dissent notes with full provenance.
Supports deterministic replay via recorded seeds and snapshots.

RESONANCE ENERGY / NARTIX ecosystem component for the NCL brain pipeline.
"""

from .models import (
    AgentRole,
    AgentConfig,
    AgentOutput,
    ConsensusResult,
    CouncilRunRecord,
    ReplayConfig,
)
from .agents import (
    get_agent_configs,
    run_agent,
    run_parallel_council,
)
from .replay import ReplayEngine
from .store import CouncilRunStore

__all__ = [
    # Models
    "AgentRole",
    "AgentConfig",
    "AgentOutput",
    "ConsensusResult",
    "CouncilRunRecord",
    "ReplayConfig",
    # Agents
    "get_agent_configs",
    "run_agent",
    "run_parallel_council",
    # Engines
    "ReplayEngine",
    "CouncilRunStore",
]
