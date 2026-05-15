"""
Abstract base class for all swarm agents.

Every agent in the NCL swarm inherits from SwarmAgent and implements
the execute() method. The base class provides shared utilities for
LLM calls, blackboard I/O, memory queries, and lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from .blackboard import Blackboard
from .llm_router import LLMResponse, LLMRouter
from .models import AgentState, SubtaskNode, TaskResult

logger = logging.getLogger(__name__)


class SwarmAgent(ABC):
    """
    Base class for all NCL swarm agents.

    Subclasses must implement execute() to perform their specialized work.
    The base provides LLM routing, blackboard access, memory queries,
    checkpointing, and cost tracking.
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        config: dict[str, Any],
        llm_router: LLMRouter,
        blackboard: Blackboard,
    ) -> None:
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._config = config
        self._llm_router = llm_router
        self._blackboard = blackboard
        self._state: AgentState = AgentState.IDLE
        self._cost_cents: float = 0.0
        self._current_task_id: str | None = None
        self._lock = asyncio.Lock()

        logger.info(
            "Agent initialized: id=%s type=%s",
            self._agent_id,
            self._agent_type,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_type(self) -> str:
        return self._agent_type

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def cost_spent(self) -> float:
        """Total cost in cents incurred by this agent."""
        return self._cost_cents

    # ------------------------------------------------------------------
    # Abstract method — must be implemented by subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, task: SubtaskNode) -> TaskResult:
        """
        Execute the given subtask and return a result.

        Implementations should:
        - Set self._state to WORKING at the start
        - Call self.checkpoint() for long-running operations
        - Return a TaskResult with output, confidence, cost, duration
        - Handle errors gracefully and set state to ERROR on failure
        """
        ...

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    async def checkpoint(self, data: dict[str, Any]) -> None:
        """
        Write intermediate state to the blackboard for fault recovery.

        Args:
            data: Arbitrary dict of checkpoint data (must be JSON-serializable).
        """
        if not self._current_task_id:
            logger.warning("checkpoint() called without an active task on agent %s", self._agent_id)
            return

        key = f"checkpoint:{self._agent_id}:{self._current_task_id}"
        await self._blackboard.put(
            key=key,
            value={
                "agent_id": self._agent_id,
                "task_id": self._current_task_id,
                "timestamp": time.time(),
                "data": data,
            },
            ttl=3600,  # 1 hour TTL for checkpoints
        )
        logger.debug("Checkpoint saved: %s", key)

    async def query_memory(
        self,
        tags: list[str] | None = None,
        importance_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Query the blackboard memory store for relevant context.

        Args:
            tags: Filter results by these tags. None returns all.
            importance_threshold: Minimum importance score (0.0–1.0).

        Returns:
            List of memory entries matching the criteria.
        """
        prefix = f"memory:{self._current_task_id or 'global'}"
        keys = await self._blackboard.list_keys(prefix=prefix)
        results: list[dict[str, Any]] = []

        for key in keys:
            entry = await self._blackboard.get(key)
            if entry is None:
                continue

            entry_importance = entry.get("importance", 0.0)
            if entry_importance < importance_threshold:
                continue

            if tags:
                entry_tags = set(entry.get("tags", []))
                if not entry_tags.intersection(tags):
                    continue

            results.append(entry)

        results.sort(key=lambda e: e.get("importance", 0.0), reverse=True)
        return results

    async def call_llm(
        self,
        prompt: str,
        model_preference: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Make an LLM call through the router with cost tracking.

        Args:
            prompt: The prompt text to send.
            model_preference: Preferred backend (e.g. "claude", "grok", "ollama").
                              Falls back to agent config default if None.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content, model used, token counts, cost, and latency.
        """
        backend = model_preference or self._config.get("default_llm", "claude")

        response = await self._llm_router.call(
            backend=backend,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        self._cost_cents += response.cost_cents
        logger.debug(
            "LLM call: agent=%s backend=%s tokens_out=%d cost=%.2f¢",
            self._agent_id,
            response.model,
            response.tokens_out,
            response.cost_cents,
        )

        return response

    async def cleanup(self) -> None:
        """
        Release resources and transition to TERMINATED state.

        Called when the agent is being removed from the swarm pool.
        Subclasses may override to add custom teardown logic.
        """
        async with self._lock:
            self._state = AgentState.TERMINATED
            self._current_task_id = None
            logger.info(
                "Agent terminated: id=%s type=%s total_cost=%.2f¢",
                self._agent_id,
                self._agent_type,
                self._cost_cents,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_state(self, new_state: AgentState) -> None:
        """Transition agent state with logging."""
        old = self._state
        self._state = new_state
        if old != new_state:
            logger.debug(
                "Agent %s state: %s → %s",
                self._agent_id,
                old.value,
                new_state.value,
            )

    def _start_task(self, task: SubtaskNode) -> None:
        """Mark a task as the current work item."""
        self._current_task_id = task.subtask_id
        self._set_state(AgentState.WORKING)

    def _finish_task(self) -> None:
        """Clear the current task and return to idle."""
        self._current_task_id = None
        self._set_state(AgentState.IDLE)
