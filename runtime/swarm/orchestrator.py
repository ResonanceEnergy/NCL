"""
SwarmOrchestrator — the Foreman of the NCL Agent Swarm.

Accepts high-level tasks, decomposes them into subtask DAGs via the
TaskGraphBuilder, dispatches work to specialized agents, enforces budgets
and policy gates, and synthesizes final results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .agents import get_agent_class, list_agent_types
from .blackboard import Blackboard
from .cost_gate import CostGate
from .llm_router import LLMRouter
from .models import AgentState, SwarmTask, TaskResult, TaskStatus
from .task_graph import TaskGraphBuilder, TaskGraphEngine

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Agent pool entry
# ---------------------------------------------------------------------------


class _PooledAgent:
    """Wrapper tracking a pooled agent instance."""

    __slots__ = ("agent", "agent_type", "last_used")

    def __init__(self, agent: Any, agent_type: str) -> None:
        self.agent = agent
        self.agent_type = agent_type
        self.last_used = time.time()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


_SYNTHESIS_SYSTEM = """\
You are a result synthesizer for an AI agent swarm. Given the outputs of \
multiple subtasks that together accomplish a high-level objective, produce a \
coherent final deliverable that directly addresses the original objective.

Be concise, well-structured, and actionable. Combine the subtask results \
into a unified response — do not simply list them."""

_SYNTHESIS_USER = """\
Original Objective: {objective}

Subtask Results:
{results_text}

Synthesize these into a single coherent deliverable that fulfills the objective."""


class SwarmOrchestrator:
    """
    The Foreman: manages the full lifecycle of swarm tasks from submission
    through decomposition, execution, and result synthesis.

    Features:
    - LLM-powered task decomposition into subtask DAGs
    - Agent pool with reuse and concurrency limits
    - Per-task budget enforcement via CostGate
    - Optional PolicyKernel gate for Execute-tier actions
    - Emergency stop support
    - Stalled task detection and recovery
    - Per-agent execution timeouts (TIMED_OUT state on breach)
    - AWAITING_APPROVAL expiration (EXPIRED state after approval_timeout_seconds)
    - Automatic cleanup of completed tasks older than 24 h
    """

    MAX_CONCURRENT_AGENTS = 4
    STALL_TIMEOUT_SECONDS = 300        # 5 minutes — deadlock / no-progress detection
    AGENT_TIMEOUT_SECONDS = 300        # 5 minutes — max wall-clock for a single agent run
    APPROVAL_TIMEOUT_SECONDS = 3600    # 1 hour   — max wait in AWAITING_APPROVAL
    COMPLETED_TASK_TTL_SECONDS = 86400 # 24 hours — cleanup_completed_tasks() threshold
    MAX_TASKS = 5000  # Hard cap on _tasks dict size
    TASK_TTL_HOURS = 24  # Completed/failed tasks older than this are evicted

    def __init__(
        self,
        config: dict[str, Any],
        llm_router: LLMRouter,
        blackboard: Blackboard,
        policy_kernel: Any | None = None,
        emergency_stop: asyncio.Event | None = None,
    ) -> None:
        """
        Args:
            config: Swarm configuration dict.
            llm_router: Shared LLM router for all calls.
            blackboard: Shared state store.
            policy_kernel: Optional policy gate; must expose
                           ``async approve(action_desc: str) -> bool``.
            emergency_stop: If set, all agent spawning halts immediately.
        """
        self._config = config
        self._llm_router = llm_router
        self._blackboard = blackboard
        self._policy_kernel = policy_kernel
        self._emergency_stop = emergency_stop or asyncio.Event()

        # Cost enforcement
        self._cost_gate = CostGate(
            paperclip_client=config.get("paperclip_client"),
        )

        # Task storage — all three dicts must be modified together under _tasks_guard
        self._tasks: dict[str, SwarmTask] = {}
        self._task_graphs: dict[str, TaskGraphEngine] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        self._tasks_guard = asyncio.Lock()  # Serialises insertions and deletions across all three dicts
        self._background_workers: dict[str, asyncio.Task[None]] = {}

        # Agent pool
        self._agent_pool: list[_PooledAgent] = []
        self._active_agents: int = 0
        self._agent_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_AGENTS)
        self._pool_lock = asyncio.Lock()

        # Stats — guarded by _stats_lock so concurrent coroutines can safely
        # increment them via += without risking a read-modify-write race.
        self._stats_lock = asyncio.Lock()
        self._total_submitted: int = 0
        self._total_completed: int = 0
        self._total_failed: int = 0
        self._total_cost_cents: float = 0.0

        # Maintenance
        self._maintenance_task: asyncio.Task[None] | None = None
        self._tasks_since_last_cleanup: int = 0

        # Graph builder
        self._graph_builder = TaskGraphBuilder(
            llm_router=llm_router,
            decompose_backend=config.get("decompose_backend", "claude"),
        )

        logger.info("SwarmOrchestrator initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        title: str,
        objective: str,
        priority: int = 5,
        budget_cents: int = 500,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SwarmTask:
        """
        Submit a new task to the swarm for background execution.

        The task is decomposed into subtasks and execution begins
        immediately in the background. Returns the task object with
        its ID for tracking.

        Args:
            title: Short human-readable title.
            objective: Full description of what to accomplish.
            priority: 1 (lowest) to 10 (highest).
            budget_cents: Maximum spend allowed for this task.
            tags: Optional classification tags.
            metadata: Optional extra metadata.

        Returns:
            The created SwarmTask (status will be PENDING or DECOMPOSING).
        """
        task = SwarmTask(
            title=title,
            objective=objective,
            priority=priority,
            budget_cents=budget_cents,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Enforce max task cap — evict old finished tasks if needed
        self._tasks_since_last_cleanup += 1
        if self._tasks_since_last_cleanup >= 100:
            await self._cleanup_old_tasks()
            self._tasks_since_last_cleanup = 0
        elif len(self._tasks) >= self.MAX_TASKS:
            await self._cleanup_old_tasks()

        async with self._tasks_guard:
            self._tasks[task.task_id] = task
            self._task_locks[task.task_id] = asyncio.Lock()
        async with self._stats_lock:
            self._total_submitted += 1

        # Allocate budget
        await self._cost_gate.allocate(task.task_id, budget_cents)

        # Start background execution
        worker = asyncio.create_task(
            self._execute_task(task),
            name=f"swarm-task-{task.task_id}",
        )
        async with self._tasks_guard:
            self._background_workers[task.task_id] = worker

        # Start maintenance if not running
        await self._ensure_maintenance_running()

        logger.info(
            "Task submitted: id=%s title='%s' priority=%d budget=%d¢",
            task.task_id,
            title,
            priority,
            budget_cents,
        )

        return task

    def get_task(self, task_id: str) -> SwarmTask | None:
        """
        Retrieve a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            The SwarmTask or None if not found.
        """
        return self._tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task and all its active agents.

        Args:
            task_id: The task to cancel.

        Returns:
            True if the task was found and cancelled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False

        async with self._task_locks[task_id]:
            if task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                return False

            task.status = TaskStatus.CANCELLED
            task.completed_at = _utcnow()

        # Cancel background worker
        async with self._tasks_guard:
            worker = self._background_workers.pop(task_id, None)
        if worker and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

        # Mark all pending and running subtasks as cancelled
        engine = self._task_graphs.get(task_id)
        if engine:
            for node in engine.graph.nodes.values():
                if node.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.ASSIGNED):
                    node.status = TaskStatus.CANCELLED

        await self._cost_gate.deallocate(task_id)

        logger.info("Task cancelled: id=%s title='%s'", task_id, task.title)
        return True

    def list_tasks(
        self,
        status_filter: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[SwarmTask]:
        """
        List tasks with optional status filter.

        Args:
            status_filter: If set, only return tasks with this status.
            limit: Maximum number of tasks to return.

        Returns:
            List of SwarmTask objects, most recent first.
        """
        tasks = list(self._tasks.values())

        if status_filter is not None:
            tasks = [t for t in tasks if t.status == status_filter]

        # Sort by creation time descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def get_stats(self) -> dict[str, Any]:
        """
        Return aggregate statistics for the orchestrator.

        Returns:
            Dict with total, active, completed, failed counts and cost.
        """
        active = sum(
            1
            for t in self._tasks.values()
            if t.status
            in (
                TaskStatus.PENDING,
                TaskStatus.DECOMPOSING,
                TaskStatus.IN_PROGRESS,
                TaskStatus.ASSIGNED,
                TaskStatus.AWAITING_APPROVAL,
            )
        )

        return {
            "total_submitted": self._total_submitted,
            "active_tasks": active,
            "completed_tasks": self._total_completed,
            "failed_tasks": self._total_failed,
            "total_cost_cents": round(self._total_cost_cents, 4),
            "active_agents": self._active_agents,
            "pool_size": len(self._agent_pool),
            "llm_calls": self._llm_router.call_count,
            "llm_total_cost": round(self._llm_router.total_cost_cents, 4),
        }

    def cleanup_completed_tasks(self, max_age_seconds: float | None = None) -> int:
        """
        Remove finished tasks (COMPLETED, FAILED, CANCELLED, TIMED_OUT, EXPIRED)
        that completed more than ``max_age_seconds`` ago.

        This is a synchronous, on-demand companion to the automatic maintenance
        loop. Callers can invoke it at any time without waiting for the next
        60-second tick.

        Args:
            max_age_seconds: Maximum age in seconds for a finished task to be
                retained. Defaults to ``COMPLETED_TASK_TTL_SECONDS`` (24 h).

        Returns:
            Number of tasks removed.
        """
        if max_age_seconds is None:
            max_age_seconds = float(self.COMPLETED_TASK_TTL_SECONDS)

        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMED_OUT,
            TaskStatus.EXPIRED,
        }
        cutoff = _utcnow() - timedelta(seconds=max_age_seconds)

        # Snapshot under _tasks_guard so insertions/deletions from the async
        # maintenance loop cannot race with this synchronous caller.
        # NOTE: _tasks_guard is an asyncio.Lock, so we cannot await it here.
        # This method must only be called from coroutine context via
        # asyncio.run_coroutine_threadsafe or equivalent, or the caller must
        # ensure no concurrent async maintenance loop is running.  The async
        # _cleanup_old_tasks() companion properly acquires _tasks_guard.
        to_remove = [
            task_id
            for task_id, task in self._tasks.items()
            if task.status in terminal
            and task.completed_at is not None
            and task.completed_at < cutoff
        ]

        for task_id in to_remove:
            self._tasks.pop(task_id, None)
            self._task_graphs.pop(task_id, None)
            self._task_locks.pop(task_id, None)

        if to_remove:
            logger.info(
                "cleanup_completed_tasks: removed %d tasks older than %.0fs",
                len(to_remove),
                max_age_seconds,
            )

        return len(to_remove)

    async def shutdown(self) -> None:
        """
        Gracefully shut down the orchestrator.

        Cancels all background workers, cleans up agents, stops maintenance.
        """
        logger.info("SwarmOrchestrator shutting down...")

        # Stop maintenance
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        # Cancel all workers
        async with self._tasks_guard:
            workers_snapshot = list(self._background_workers.items())
        for task_id, worker in workers_snapshot:
            if not worker.done():
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass

        # Clean up pooled agents
        async with self._pool_lock:
            for pooled in self._agent_pool:
                await pooled.agent.cleanup()
            self._agent_pool.clear()

        logger.info("SwarmOrchestrator shutdown complete")

    # ------------------------------------------------------------------
    # Background task execution
    # ------------------------------------------------------------------

    async def _execute_task(self, task: SwarmTask) -> None:
        """
        Main execution loop for a single task.

        Decomposes the objective into subtasks, then iteratively dispatches
        ready subtasks to agents until the graph is complete.
        """
        try:
            # Phase 1: Decomposition
            async with self._task_locks[task.task_id]:
                task.status = TaskStatus.DECOMPOSING
                task.started_at = _utcnow()

            graph = await self._graph_builder.build(
                task_id=task.task_id,
                objective=task.objective,
                context=json.dumps(task.metadata) if task.metadata else "",
            )

            engine = TaskGraphEngine(graph)
            self._task_graphs[task.task_id] = engine

            async with self._task_locks[task.task_id]:
                task.status = TaskStatus.IN_PROGRESS
                task.subtasks = list(graph.nodes.keys())

            # Publish decomposition to blackboard
            await self._blackboard.put(
                key=f"task:{task.task_id}:graph",
                value={
                    "subtasks": [
                        {
                            "id": n.subtask_id,
                            "title": n.title,
                            "agent_type": n.agent_type,
                            "depends_on": n.depends_on,
                        }
                        for n in graph.nodes.values()
                    ]
                },
                ttl=7200,
            )

            logger.info(
                "Task %s decomposed into %d subtasks. Critical path: %s",
                task.task_id,
                len(graph.nodes),
                engine.get_critical_path(),
            )

            # Phase 2: Execution loop
            last_progress_time = time.time()

            while not engine.is_complete():
                # Check emergency stop
                if self._emergency_stop.is_set():
                    logger.warning(
                        "Emergency stop triggered, halting task %s",
                        task.task_id,
                    )
                    async with self._task_locks[task.task_id]:
                        task.status = TaskStatus.CANCELLED
                        task.completed_at = _utcnow()
                    return

                # Check budget
                if await self._cost_gate.exceeded(task.task_id):
                    logger.warning(
                        "Budget exceeded for task %s, marking failed",
                        task.task_id,
                    )
                    async with self._task_locks[task.task_id]:
                        task.status = TaskStatus.FAILED
                        task.results = {"error": "Budget exceeded"}
                        task.completed_at = _utcnow()
                    async with self._stats_lock:
                        self._total_failed += 1
                    return

                ready_nodes = await engine.get_ready_nodes()
                if not ready_nodes:
                    # Nothing ready — either waiting for agents or deadlocked
                    await asyncio.sleep(0.5)
                    continue

                last_progress_time = time.time()

                # Dispatch ready nodes concurrently — hold the pool lock while
                # checking + setting status so two coroutines cannot both see
                # PENDING and both dispatch the same node (Gap 25).
                dispatch_tasks = []
                async with self._pool_lock:
                    for node in ready_nodes:
                        # Re-check status inside the lock: another coroutine may
                        # have already claimed this node since get_ready_nodes().
                        if node.status != TaskStatus.PENDING:
                            continue
                        node.status = TaskStatus.ASSIGNED
                        dispatch_tasks.append(
                            self._dispatch_subtask(task, engine, node)
                        )

                # Run dispatches concurrently (semaphore limits parallelism)
                await asyncio.gather(*dispatch_tasks, return_exceptions=True)

            # Phase 3: Synthesis
            if engine.all_succeeded():
                final_result = await self._synthesize_results(task, engine)
                async with self._task_locks[task.task_id]:
                    task.status = TaskStatus.COMPLETED
                    task.results = {"output": final_result}
                    task.completed_at = _utcnow()
                async with self._stats_lock:
                    self._total_completed += 1

                logger.info("Task %s COMPLETED successfully", task.task_id)
            else:
                # Some subtasks failed
                progress = engine.get_progress()
                async with self._task_locks[task.task_id]:
                    task.status = TaskStatus.FAILED
                    task.results = {
                        "error": "One or more subtasks failed",
                        "progress": progress,
                    }
                    task.completed_at = _utcnow()
                async with self._stats_lock:
                    self._total_failed += 1

                logger.warning(
                    "Task %s FAILED (progress: %s)", task.task_id, progress
                )

        except asyncio.CancelledError:
            logger.info("Task %s execution cancelled", task.task_id)
            raise
        except Exception as exc:
            logger.exception("Task %s execution error: %s", task.task_id, exc)
            async with self._task_locks[task.task_id]:
                task.status = TaskStatus.FAILED
                task.results = {"error": str(exc)}
                task.completed_at = _utcnow()
            async with self._stats_lock:
                self._total_failed += 1
        finally:
            async with self._tasks_guard:
                self._background_workers.pop(task.task_id, None)

    async def _dispatch_subtask(
        self,
        task: SwarmTask,
        engine: TaskGraphEngine,
        node: Any,
    ) -> None:
        """
        Dispatch a single subtask to an agent, handling policy checks and budget.
        """
        subtask_id = node.subtask_id

        try:
            # Policy gate for execute-tier actions
            if self._policy_kernel and node.agent_type in ("coder", "architect"):
                description = (
                    f"Execute subtask '{node.title}' via {node.agent_type} agent"
                )
                approved = await self._policy_kernel.approve(description)
                if not approved:
                    logger.info(
                        "Policy denied subtask %s, task %s awaiting approval",
                        subtask_id,
                        task.task_id,
                    )
                    async with self._task_locks[task.task_id]:
                        task.status = TaskStatus.AWAITING_APPROVAL
                    node.status = TaskStatus.AWAITING_APPROVAL
                    return

            # Budget check (estimate 50 cents per subtask as baseline)
            estimated_cost = self._config.get("estimated_subtask_cost_cents", 50)
            if not await self._cost_gate.can_afford(task.task_id, estimated_cost):
                logger.warning(
                    "Insufficient budget for subtask %s in task %s",
                    subtask_id,
                    task.task_id,
                )
                await engine.mark_failed(subtask_id, "Insufficient budget remaining")
                return

            # Spawn and execute
            async with self._agent_semaphore:
                node.status = TaskStatus.IN_PROGRESS
                result = await self._spawn_agent(
                    agent_type=node.agent_type,
                    subtask=node,
                    task=task,
                )

            # Record cost (budget may have been deallocated if task was cancelled)
            if result:
                try:
                    await self._cost_gate.spend(
                        task.task_id,
                        result.cost_cents,
                        f"Subtask {subtask_id}: {node.title}",
                    )
                except KeyError:
                    logger.warning(
                        "Budget already deallocated for task %s; skipping spend record",
                        task.task_id,
                    )
                async with self._stats_lock:
                    self._total_cost_cents += result.cost_cents

                # Mark complete or failed based on result status
                if result.status == TaskStatus.FAILED:
                    await engine.mark_failed(
                        subtask_id,
                        result.output[:200],
                    )
                else:
                    await engine.mark_complete(
                        subtask_id,
                        {
                            "output": result.output,
                            "confidence": result.confidence,
                            "artifacts": result.artifacts,
                        },
                    )

                # Publish result to blackboard
                await self._blackboard.put(
                    key=f"result:{task.task_id}:{subtask_id}",
                    value={
                        "output": result.output,
                        "confidence": result.confidence,
                        "cost_cents": result.cost_cents,
                    },
                    ttl=7200,
                )
            else:
                await engine.mark_failed(subtask_id, "Agent returned no result")

        except Exception as exc:
            logger.exception(
                "Error dispatching subtask %s: %s", subtask_id, exc
            )
            await engine.mark_failed(subtask_id, str(exc))

    async def _spawn_agent(
        self,
        agent_type: str,
        subtask: Any,
        task: SwarmTask,
    ) -> TaskResult | None:
        """
        Instantiate (or reuse) an agent and execute the subtask.

        Attempts to reuse an idle agent of the same type from the pool.
        If none available, creates a new one.

        Args:
            agent_type: Type of agent to spawn (e.g. "scholar", "coder").
            subtask: The SubtaskNode to execute.
            task: Parent task (for context).

        Returns:
            TaskResult on success, None on failure.
        """
        agent = await self._acquire_agent(agent_type)
        agent_timeout = self._config.get("agent_timeout_seconds", self.AGENT_TIMEOUT_SECONDS)

        try:
            async with self._pool_lock:
                self._active_agents += 1

            # Provide context on blackboard
            await self._blackboard.put(
                key=f"context:{task.task_id}:{subtask.subtask_id}",
                value={
                    "task_title": task.title,
                    "task_objective": task.objective,
                    "subtask_title": subtask.title,
                    "subtask_description": subtask.input_data.get("description", ""),
                },
                ttl=3600,
            )

            try:
                result = await asyncio.wait_for(
                    agent.execute(subtask),
                    timeout=agent_timeout,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Agent %s timed out after %.0fs on subtask %s (task %s)",
                    agent.agent_id,
                    agent_timeout,
                    subtask.subtask_id,
                    task.task_id,
                )
                subtask.status = TaskStatus.TIMED_OUT
                return None

            return result

        except Exception as exc:
            logger.error(
                "Agent %s failed on subtask %s: %s",
                agent.agent_id,
                subtask.subtask_id,
                exc,
            )
            return None
        finally:
            async with self._pool_lock:
                self._active_agents -= 1

            # Return agent to pool
            await self._release_agent(agent, agent_type)

    async def _acquire_agent(self, agent_type: str) -> Any:
        """
        Get an agent from the pool or create a new one.

        Args:
            agent_type: Type of agent needed.

        Returns:
            A SwarmAgent instance ready for work.
        """
        # Try to reuse from pool
        async with self._pool_lock:
            for i, pooled in enumerate(self._agent_pool):
                if (
                    pooled.agent_type == agent_type
                    and pooled.agent.state == AgentState.IDLE
                ):
                    self._agent_pool.pop(i)
                    logger.debug(
                        "Reusing pooled agent %s (type=%s)",
                        pooled.agent.agent_id,
                        agent_type,
                    )
                    return pooled.agent

        # Create new agent
        try:
            agent_cls = get_agent_class(agent_type)
        except KeyError:
            # Fallback: if the specific type isn't registered, log warning
            logger.warning(
                "Agent type '%s' not registered. Available: %s",
                agent_type,
                list_agent_types(),
            )
            raise

        agent_id = f"{agent_type}_{uuid.uuid4().hex[:8]}"
        agent = agent_cls(
            agent_id=agent_id,
            agent_type=agent_type,
            config=self._config,
            llm_router=self._llm_router,
            blackboard=self._blackboard,
        )

        logger.info("Spawned new agent: id=%s type=%s", agent_id, agent_type)
        return agent

    async def _release_agent(self, agent: Any, agent_type: str) -> None:
        """Return an agent to the pool for reuse."""
        if agent.state == AgentState.TERMINATED:
            return

        async with self._pool_lock:
            # Cap pool size to avoid unbounded growth
            max_pool = self._config.get("max_pool_size", 8)
            if len(self._agent_pool) < max_pool:
                self._agent_pool.append(_PooledAgent(agent, agent_type))
                logger.debug(
                    "Returned agent %s to pool (pool_size=%d)",
                    agent.agent_id,
                    len(self._agent_pool),
                )
            else:
                # Pool full, terminate
                await agent.cleanup()

    async def _synthesize_results(
        self,
        task: SwarmTask,
        engine: TaskGraphEngine,
    ) -> str:
        """
        Assemble subtask outputs into a final coherent deliverable using Claude.

        Args:
            task: The parent task.
            engine: The task graph engine with completed nodes.

        Returns:
            Synthesized result string.
        """
        # Gather all subtask outputs in topological order
        topo_order = engine.topological_sort()
        results_parts: list[str] = []

        for subtask_id in topo_order:
            node = engine.graph.nodes[subtask_id]
            output = node.output_data.get("output", "")
            if output:
                results_parts.append(
                    f"[{node.title} ({node.agent_type})]\n{output}"
                )

        results_text = "\n\n---\n\n".join(results_parts)

        prompt = _SYNTHESIS_USER.format(
            objective=task.objective,
            results_text=results_text,
        )

        response = await self._llm_router.call(
            backend="claude",
            prompt=prompt,
            system_prompt=_SYNTHESIS_SYSTEM,
            max_tokens=4096,
            temperature=0.4,
        )

        # Track synthesis cost
        await self._cost_gate.spend(
            task.task_id,
            response.cost_cents,
            "Result synthesis",
        )
        async with self._stats_lock:
            self._total_cost_cents += response.cost_cents

        return response.content

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def _ensure_maintenance_running(self) -> None:
        """Start the maintenance loop if not already running."""
        if self._maintenance_task is None or self._maintenance_task.done():
            self._maintenance_task = asyncio.create_task(
                self._maintenance_loop(),
                name="swarm-maintenance",
            )

    async def _maintenance_loop(self) -> None:
        """
        Periodic maintenance: detect stalled tasks, prune dead agents,
        and clean up old completed/failed tasks.
        Runs every 60 seconds.
        """
        try:
            while True:
                await asyncio.sleep(60)
                await self._check_stalled_tasks()
                await self._check_approval_timeouts()
                await self._prune_idle_agents()
                await self._cleanup_old_tasks()
        except asyncio.CancelledError:
            pass

    async def _cleanup_old_tasks(self) -> None:
        """
        Remove completed, failed, and cancelled tasks older than TASK_TTL_HOURS.

        Also enforces the MAX_TASKS hard cap: if the dict is still over the
        limit after TTL eviction, removes the oldest finished tasks until we
        are back under the cap.

        All three storage dicts (_tasks, _task_graphs, _task_locks) are modified
        together under _tasks_guard to keep them in sync.
        """
        cutoff = _utcnow() - timedelta(hours=self.TASK_TTL_HOURS)
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

        async with self._tasks_guard:
            to_remove = [
                task_id
                for task_id, task in self._tasks.items()
                if task.status in terminal and task.completed_at is not None and task.completed_at < cutoff
            ]

            for task_id in to_remove:
                self._tasks.pop(task_id, None)
                self._task_graphs.pop(task_id, None)
                self._task_locks.pop(task_id, None)

            if to_remove:
                logger.debug(
                    "Task cleanup: removed %d expired tasks (cutoff=%s)",
                    len(to_remove),
                    cutoff.isoformat(),
                )

            # If still over cap, evict oldest finished tasks regardless of age
            if len(self._tasks) >= self.MAX_TASKS:
                finished = sorted(
                    [t for t in self._tasks.values() if t.status in terminal and t.completed_at],
                    key=lambda t: t.completed_at,
                )
                overflow = len(self._tasks) - self.MAX_TASKS + 1
                for task in finished[:overflow]:
                    self._tasks.pop(task.task_id, None)
                    self._task_graphs.pop(task.task_id, None)
                    self._task_locks.pop(task.task_id, None)
                if overflow > 0:
                    logger.warning(
                        "Task dict at MAX_TASKS cap (%d); force-evicted %d finished tasks",
                        self.MAX_TASKS,
                        min(overflow, len(finished)),
                    )

    async def _check_stalled_tasks(self) -> None:
        """
        Detect tasks that have made no progress in STALL_TIMEOUT_SECONDS.
        Mark them as failed with a stall error.
        """
        now = time.time()

        for task_id, task in self._tasks.items():
            if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.ASSIGNED):
                continue

            engine = self._task_graphs.get(task_id)
            if engine is None:
                continue

            # Check if any subtask is actively in progress
            any_active = any(
                node.status in (TaskStatus.IN_PROGRESS, TaskStatus.ASSIGNED)
                for node in engine.graph.nodes.values()
            )

            if not any_active:
                # All subtasks are either done or pending — check if stuck
                ready = await engine.get_ready_nodes()
                if not ready and not engine.is_complete():
                    # Deadlocked — no ready nodes but not complete
                    elapsed = now - (
                        task.started_at.timestamp() if task.started_at else now
                    )
                    if elapsed > self.STALL_TIMEOUT_SECONDS:
                        logger.warning(
                            "Task %s appears stalled (no progress for %.0fs), marking failed",
                            task_id,
                            elapsed,
                        )
                        async with self._task_locks[task_id]:
                            task.status = TaskStatus.FAILED
                            task.results = {
                                "error": f"Task stalled — no progress for {elapsed:.0f}s"
                            }
                            task.completed_at = _utcnow()
                        async with self._stats_lock:
                            self._total_failed += 1

    async def _check_approval_timeouts(self) -> None:
        """
        Expire tasks stuck in AWAITING_APPROVAL longer than APPROVAL_TIMEOUT_SECONDS.

        After the timeout the task transitions to EXPIRED so the caller knows
        the approval window has closed. The budget allocation is released.
        """
        approval_timeout = self._config.get(
            "approval_timeout_seconds", self.APPROVAL_TIMEOUT_SECONDS
        )
        now = _utcnow()

        for task_id, task in list(self._tasks.items()):
            if task.status != TaskStatus.AWAITING_APPROVAL:
                continue

            # Use started_at as the proxy for when approval was requested
            reference_time = task.started_at or task.created_at
            elapsed = (now - reference_time).total_seconds()

            if elapsed > approval_timeout:
                logger.warning(
                    "Task %s has been AWAITING_APPROVAL for %.0fs (limit %.0fs) — expiring",
                    task_id,
                    elapsed,
                    approval_timeout,
                )
                async with self._task_locks[task_id]:
                    task.status = TaskStatus.EXPIRED
                    task.completed_at = now
                    task.results = {
                        "error": (
                            f"Approval not received within {approval_timeout:.0f}s — task expired"
                        )
                    }
                await self._cost_gate.deallocate(task_id)
                async with self._stats_lock:
                    self._total_failed += 1

    async def _prune_idle_agents(self) -> None:
        """Remove agents that have been idle in the pool for too long."""
        max_idle_seconds = self._config.get("agent_idle_timeout", 300)
        now = time.time()

        async with self._pool_lock:
            to_keep: list[_PooledAgent] = []
            for pooled in self._agent_pool:
                if now - pooled.last_used > max_idle_seconds:
                    await pooled.agent.cleanup()
                    logger.debug(
                        "Pruned idle agent %s from pool",
                        pooled.agent.agent_id,
                    )
                else:
                    to_keep.append(pooled)
            self._agent_pool = to_keep
