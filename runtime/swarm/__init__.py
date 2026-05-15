"""
NCL Agent Swarm System — Supervisor-Worker architecture with shared Blackboard.

A multi-agent orchestration layer that decomposes tasks, assigns them to
specialized worker agents, and aggregates results through a shared blackboard.
"""

from .models import (
    AgentSpec,
    AgentState,
    SubtaskNode,
    SwarmMessage,
    SwarmTask,
    TaskGraph,
    TaskResult,
    TaskStatus,
)
from .agent_base import SwarmAgent
from .blackboard import Blackboard
from .llm_router import LLMRouter, LLMResponse

__all__ = [
    "AgentSpec",
    "AgentState",
    "Blackboard",
    "LLMResponse",
    "LLMRouter",
    "SubtaskNode",
    "SwarmAgent",
    "SwarmMessage",
    "SwarmTask",
    "TaskGraph",
    "TaskResult",
    "TaskStatus",
]
