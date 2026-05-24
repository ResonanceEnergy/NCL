"""
Pydantic v2 models for the NCL Agent Swarm system.

Defines all data structures used for task management, inter-agent messaging,
agent lifecycle, task decomposition graphs, and result reporting.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Lifecycle states for a swarm task."""

    PENDING = "pending"
    DECOMPOSING = "decomposing"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    CHECKPOINT = "checkpoint"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"  # Agent execution exceeded timeout
    EXPIRED = "expired"  # AWAITING_APPROVAL exceeded approval timeout


class AgentState(str, Enum):
    """Runtime states for a swarm agent."""

    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"
    ERROR = "error"
    TERMINATED = "terminated"


# ---------------------------------------------------------------------------
# Core Task Model
# ---------------------------------------------------------------------------


class SwarmTask(BaseModel):
    """Top-level task submitted to the swarm for execution."""

    task_id: str = Field(default_factory=_new_id)
    title: str
    objective: str
    parent_task_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = Field(default=5, ge=1, le=10)
    budget_cents: int = Field(default=500, ge=0)
    assigned_agent: str | None = None
    subtasks: list[str] = Field(default_factory=list)
    results: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


class SwarmMessage(BaseModel):
    """Inter-agent communication envelope."""

    message_id: str = Field(default_factory=_new_id)
    task_id: str
    from_agent: str
    to_agent: str
    message_type: Literal[
        "assign",
        "status_update",
        "result",
        "checkpoint",
        "error",
        "query",
        "response",
        "cancel",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)
    created_at: datetime = Field(default_factory=_utcnow)
    acknowledged_at: datetime | None = None


# ---------------------------------------------------------------------------
# Agent Specification
# ---------------------------------------------------------------------------


class AgentSpec(BaseModel):
    """Describes a running agent instance in the swarm."""

    agent_id: str = Field(default_factory=_new_id)
    agent_type: str
    llm_backend: str = "claude"
    status: AgentState = AgentState.IDLE
    current_task_id: str | None = None
    tasks_completed: int = 0
    total_cost_cents: float = 0.0
    spawned_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Task Decomposition Graph
# ---------------------------------------------------------------------------


class SubtaskNode(BaseModel):
    """A single node in a task decomposition graph."""

    subtask_id: str = Field(default_factory=_new_id)
    title: str
    agent_type: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)


class TaskGraph(BaseModel):
    """Directed acyclic graph of subtask dependencies for a parent task."""

    task_id: str
    nodes: dict[str, SubtaskNode] = Field(default_factory=dict)
    edges: list[tuple[str, str]] = Field(default_factory=list)

    def ready_nodes(self) -> list[SubtaskNode]:
        """Return nodes whose dependencies are all completed."""
        completed_ids = {
            nid for nid, node in self.nodes.items() if node.status == TaskStatus.COMPLETED
        }
        return [
            node
            for node in self.nodes.values()
            if node.status == TaskStatus.PENDING
            and all(dep in completed_ids for dep in node.depends_on)
        ]

    def is_complete(self) -> bool:
        """True if every node has reached a terminal state."""
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        return all(node.status in terminal for node in self.nodes.values())


# ---------------------------------------------------------------------------
# Task Result
# ---------------------------------------------------------------------------


class TaskResult(BaseModel):
    """Result produced by an agent after completing a subtask."""

    task_id: str
    subtask_id: str
    agent_id: str
    output: str
    status: TaskStatus = TaskStatus.COMPLETED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    cost_cents: float = 0.0
    duration_ms: int = 0
    artifacts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
