"""
NCL Agent Swarm System — Supervisor-Worker architecture with shared Blackboard.

A multi-agent orchestration layer that decomposes tasks, assigns them to
specialized worker agents, and aggregates results through a shared blackboard.
"""

from .agent_base import SwarmAgent
from .blackboard import Blackboard
from .llm_adapter import LLMClientAdapter
from .llm_adapter import _LLMResponse as LLMResponse
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


__all__ = [
    "AgentSpec",
    "AgentState",
    "Blackboard",
    "LLMClientAdapter",
    "LLMResponse",
    "SubtaskNode",
    "SwarmAgent",
    "SwarmMessage",
    "SwarmTask",
    "TaskGraph",
    "TaskResult",
    "TaskStatus",
]
