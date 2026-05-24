"""council_pack.models — relocated from council_runner (W5-06, 2026-05-23).

Persistence models for the Council Runner v1 surface. The v1
Planner/Skeptic/Risk agents themselves were retired (see
``council_pack.legacy.run_parallel_council`` for a deprecation-shim
copy); but their record format is still used by ``/council-runner/run``
to project pack-routed sessions into a uniform shape for storage and
replay.

Originally lived at ``runtime/council_runner/models.py``. Moved here
because the surrounding directory was archived to
``archive/strike-point-pre-merge/council_runner/``. The pack now owns
council session storage + replay.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class AgentRole(str, Enum):
    """Three specialized roles in the legacy Council Runner."""

    PLANNER = "planner"
    SKEPTIC = "skeptic"
    RISK = "risk"


# ─────────────────────────────────────────────────────────────────────────────
# Agent Configuration
# ─────────────────────────────────────────────────────────────────────────────


class AgentConfig(BaseModel):
    """Configuration for a council agent."""

    role: AgentRole
    system_prompt: str
    model_preference: str = "claude"  # "claude", "grok", "ollama"
    temperature: float = 0.4
    max_tokens: int = 4096


# ─────────────────────────────────────────────────────────────────────────────
# Agent Output
# ─────────────────────────────────────────────────────────────────────────────


class AgentOutput(BaseModel):
    """Output from a single agent's deliberation."""

    role: AgentRole
    response_text: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    key_points: list[str] = Field(default_factory=list)
    dissent_notes: list[str] = Field(default_factory=list)
    risks_identified: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    model_used: str = "unknown"
    token_count: int = 0
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Consensus
# ─────────────────────────────────────────────────────────────────────────────


class ConsensusResult(BaseModel):
    """Synthesized consensus from all three agents."""

    consensus_text: str
    consensus_score: int = Field(default=50, ge=0, le=100)
    agreement_areas: list[str] = Field(default_factory=list)
    dissent_areas: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Replay Configuration
# ─────────────────────────────────────────────────────────────────────────────


class ReplayConfig(BaseModel):
    """Configuration for deterministic replay of a council run."""

    run_id: str
    replay_seed: str
    force_models: dict[str, str] = Field(
        default_factory=dict
    )  # role → model override
    temperature_override: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Full Council Run Record
# ─────────────────────────────────────────────────────────────────────────────


class CouncilRunRecord(BaseModel):
    """Complete record of a council runner execution with full provenance."""

    run_id: str
    topic: str
    prompt: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    agent_outputs: list[AgentOutput] = Field(default_factory=list)
    consensus: Optional[ConsensusResult] = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    replay_seed: str = ""
    snapshot: dict[str, Any] = Field(
        default_factory=dict
    )  # State for deterministic replay
    total_duration_ms: int = 0
