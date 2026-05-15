"""
DAG engine for task decomposition in the NCL Agent Swarm.

Provides the TaskGraphBuilder which uses an LLM to decompose high-level
objectives into a directed acyclic graph of subtasks, plus traversal and
lifecycle methods for executing the graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any

from .llm_router import LLMRouter
from .models import SubtaskNode, TaskGraph, TaskStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decomposition prompt template
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = """\
You are a task decomposition engine for an AI agent swarm. Given a high-level \
objective, break it into concrete subtasks that can be executed by specialized agents.

Available agent types:
- scholar: Deep research, knowledge synthesis, literature review
- scout: Web search, data gathering, reconnaissance
- architect: System design, planning, technical architecture
- coder: Code generation, implementation, debugging
- analyst: Data analysis, metrics, evaluation, comparison
- scribe: Writing, documentation, report generation, editing
- sentinel: Security review, validation, quality assurance

Rules:
1. Each subtask must be independently executable by a single agent.
2. Declare dependencies explicitly — a subtask can only depend on subtasks listed before it.
3. Minimize the critical path — parallelize where possible.
4. Keep subtask count between 2 and 12 for a typical task.
5. Every subtask must have a clear, actionable description.

Respond with ONLY valid JSON, no markdown fences or commentary."""

_DECOMPOSE_USER = """\
Objective: {objective}

Context (if any): {context}

Decompose this into subtasks. Return JSON in exactly this format:
{{"subtasks": [{{"id": "st_1", "title": "...", "agent_type": "scholar|scout|architect|coder|analyst|scribe|sentinel", "description": "...", "depends_on": []}}]}}"""


# ---------------------------------------------------------------------------
# TaskGraphBuilder
# ---------------------------------------------------------------------------


class TaskGraphBuilder:
    """
    Builds a SubtaskNode DAG from a high-level objective using LLM decomposition.

    Usage:
        builder = TaskGraphBuilder(llm_router)
        graph = await builder.build(task_id="abc123", objective="Build a REST API...")
    """

    def __init__(self, llm_router: LLMRouter, decompose_backend: str = "claude") -> None:
        """
        Args:
            llm_router: Router for LLM calls.
            decompose_backend: Which LLM backend to use for decomposition.
        """
        self._llm_router = llm_router
        self._backend = decompose_backend

    async def build(
        self,
        task_id: str,
        objective: str,
        context: str = "",
        max_retries: int = 2,
    ) -> TaskGraph:
        """
        Decompose an objective into a TaskGraph DAG.

        Args:
            task_id: Parent task identifier for the graph.
            objective: High-level description of what to accomplish.
            context: Additional context or constraints.
            max_retries: Number of LLM call retries on parse failure.

        Returns:
            A validated TaskGraph with no cycles.

        Raises:
            ValueError: If the LLM returns invalid structure after retries or
                        if the resulting graph contains cycles.
            RuntimeError: If LLM calls fail entirely.
        """
        prompt = _DECOMPOSE_USER.format(objective=objective, context=context)
        subtasks_raw: list[dict[str, Any]] | None = None

        for attempt in range(max_retries + 1):
            response = await self._llm_router.call(
                backend=self._backend,
                prompt=prompt,
                system_prompt=_DECOMPOSE_SYSTEM,
                max_tokens=4096,
                temperature=0.3,
            )

            subtasks_raw = self._parse_response(response.content)
            if subtasks_raw is not None:
                break

            logger.warning(
                "TaskGraphBuilder: parse failed on attempt %d/%d for task=%s",
                attempt + 1,
                max_retries + 1,
                task_id,
            )

        if subtasks_raw is None:
            raise ValueError(
                f"Failed to parse LLM decomposition after {max_retries + 1} attempts "
                f"for task '{task_id}'"
            )

        # Build the graph
        graph = self._build_graph(task_id, subtasks_raw)

        # Validate no cycles
        self._validate_acyclic(graph)

        logger.info(
            "TaskGraphBuilder: decomposed task=%s into %d subtasks",
            task_id,
            len(graph.nodes),
        )

        return graph

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_response(self, content: str) -> list[dict[str, Any]] | None:
        """
        Parse the LLM response into a list of subtask dicts.

        Returns None if parsing fails.
        """
        # Strip markdown fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.debug("JSON parse error: %s", exc)
            return None

        if not isinstance(data, dict) or "subtasks" not in data:
            logger.debug("Response missing 'subtasks' key")
            return None

        subtasks = data["subtasks"]
        if not isinstance(subtasks, list) or len(subtasks) == 0:
            logger.debug("Empty or invalid subtasks list")
            return None

        # Validate each subtask has required fields
        required_fields = {"id", "title", "agent_type", "description", "depends_on"}
        for st in subtasks:
            if not isinstance(st, dict):
                return None
            if not required_fields.issubset(st.keys()):
                logger.debug("Subtask missing required fields: %s", st.get("id", "?"))
                return None

        return subtasks

    def _build_graph(self, task_id: str, subtasks_raw: list[dict[str, Any]]) -> TaskGraph:
        """Convert raw subtask dicts into a TaskGraph with SubtaskNode objects."""
        graph = TaskGraph(task_id=task_id)

        for st in subtasks_raw:
            node = SubtaskNode(
                subtask_id=st["id"],
                title=st["title"],
                agent_type=st["agent_type"],
                input_data={"description": st["description"]},
                depends_on=st.get("depends_on", []),
                status=TaskStatus.PENDING,
            )
            graph.nodes[node.subtask_id] = node

        # Build edge list from depends_on; strip unknown dep IDs so they
        # don't permanently block nodes (Gap 6).
        for node in graph.nodes.values():
            valid_deps: list[str] = []
            for dep_id in node.depends_on:
                if dep_id in graph.nodes:
                    graph.edges.append((dep_id, node.subtask_id))
                    valid_deps.append(dep_id)
                else:
                    logger.warning(
                        "TaskGraph %s: node %s depends on unknown node %s — "
                        "treating dependency as satisfied",
                        task_id,
                        node.subtask_id,
                        dep_id,
                    )
            # Keep depends_on in sync with edges (Gap 9)
            node.depends_on = valid_deps

        return graph

    def _validate_acyclic(self, graph: TaskGraph) -> None:
        """
        Validate that the graph has no cycles using Kahn's algorithm.

        Raises:
            ValueError: If a cycle is detected.
        """
        # Build adjacency and in-degree
        in_degree: dict[str, int] = {nid: 0 for nid in graph.nodes}
        adjacency: dict[str, list[str]] = {nid: [] for nid in graph.nodes}

        for src, dst in graph.edges:
            if src in adjacency and dst in in_degree:
                adjacency[src].append(dst)
                in_degree[dst] += 1

        # Kahn's algorithm
        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        visited_count = 0

        while queue:
            current = queue.popleft()
            visited_count += 1
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(graph.nodes):
            raise ValueError(
                f"Cycle detected in task graph '{graph.task_id}': "
                f"only {visited_count}/{len(graph.nodes)} nodes are reachable "
                f"in topological order"
            )


# ---------------------------------------------------------------------------
# TaskGraphEngine — runtime operations on a built graph
# ---------------------------------------------------------------------------


class TaskGraphEngine:
    """
    Runtime engine for traversing and mutating a TaskGraph during execution.

    Provides topological ordering, ready-node queries, completion/failure
    marking, and critical path analysis.
    """

    def __init__(self, graph: TaskGraph) -> None:
        self._graph = graph
        self._mutation_lock = asyncio.Lock()  # Serialises mark_complete/mark_failed (Gap 30)

    @property
    def graph(self) -> TaskGraph:
        """The underlying TaskGraph."""
        return self._graph

    def topological_sort(self) -> list[str]:
        """
        Return subtask IDs in a valid topological execution order.

        Returns:
            List of subtask_id strings in dependency-respecting order.

        Raises:
            ValueError: If the graph contains a cycle.
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self._graph.nodes}
        adjacency: dict[str, list[str]] = {nid: [] for nid in self._graph.nodes}

        for src, dst in self._graph.edges:
            if src in adjacency and dst in in_degree:
                adjacency[src].append(dst)
                in_degree[dst] += 1

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        result: list[str] = []

        while queue:
            current = queue.popleft()
            result.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._graph.nodes):
            raise ValueError("Cycle detected during topological sort")

        return result

    async def get_ready_nodes(self) -> list[SubtaskNode]:
        """
        Return subtask nodes whose dependencies are all COMPLETED and
        which are still in PENDING status (ready to execute).

        Thread-safe: acquires _mutation_lock to ensure consistent reads (Gap 8).

        Returns:
            List of SubtaskNode objects ready for dispatch.
        """
        async with self._mutation_lock:
            completed_ids = {
                nid
                for nid, node in self._graph.nodes.items()
                if node.status == TaskStatus.COMPLETED
            }

            ready = []
            for node in self._graph.nodes.values():
                if node.status != TaskStatus.PENDING:
                    continue
                if all(dep in completed_ids for dep in node.depends_on):
                    ready.append(node)

            return ready

    async def mark_complete(self, subtask_id: str, result: dict[str, Any]) -> list[str]:
        """
        Mark a subtask as COMPLETED and store its output.

        Args:
            subtask_id: The subtask to mark complete.
            result: Output data from the agent.

        Returns:
            List of subtask_ids that are now newly ready to execute.

        Raises:
            KeyError: If subtask_id is not in the graph.
        """
        async with self._mutation_lock:
            node = self._get_node(subtask_id)
            # Reject updates to cancelled nodes (Gap 7)
            if node.status == TaskStatus.CANCELLED:
                logger.warning(
                    "TaskGraph: ignoring mark_complete on CANCELLED node %s",
                    subtask_id,
                )
                return []
            node.status = TaskStatus.COMPLETED
            node.output_data = result

            logger.info("TaskGraph: subtask %s COMPLETED", subtask_id)

            # Check which downstream nodes are now ready
            newly_ready: list[str] = []
            completed_ids = {
                nid
                for nid, n in self._graph.nodes.items()
                if n.status == TaskStatus.COMPLETED
            }

            for nid, n in self._graph.nodes.items():
                if n.status != TaskStatus.PENDING:
                    continue
                if subtask_id in n.depends_on and all(
                    dep in completed_ids for dep in n.depends_on
                ):
                    newly_ready.append(nid)

            return newly_ready

    async def mark_failed(self, subtask_id: str, error: str) -> list[str]:
        """
        Mark a subtask as FAILED and propagate failure to all dependents.

        Args:
            subtask_id: The failed subtask.
            error: Error description.

        Returns:
            List of subtask_ids that were transitively failed.

        Raises:
            KeyError: If subtask_id is not in the graph.
        """
        async with self._mutation_lock:
            node = self._get_node(subtask_id)
            # Reject updates to cancelled nodes (Gap 7)
            if node.status == TaskStatus.CANCELLED:
                logger.warning(
                    "TaskGraph: ignoring mark_failed on CANCELLED node %s",
                    subtask_id,
                )
                return []
            node.status = TaskStatus.FAILED
            node.output_data = {"error": error}

            logger.warning("TaskGraph: subtask %s FAILED: %s", subtask_id, error)

            # Propagate failure to all downstream dependents (BFS)
            failed_downstream: list[str] = []
            queue: deque[str] = deque([subtask_id])

            while queue:
                current = queue.popleft()
                for nid, n in self._graph.nodes.items():
                    if n.status == TaskStatus.PENDING and current in n.depends_on:
                        n.status = TaskStatus.FAILED
                        n.output_data = {
                            "error": f"Upstream dependency '{current}' failed"
                        }
                        failed_downstream.append(nid)
                        queue.append(nid)
                    elif n.status == TaskStatus.IN_PROGRESS and current in n.depends_on:
                        # IN_PROGRESS dependents cannot recover — cancel them
                        n.status = TaskStatus.CANCELLED
                        n.output_data = {
                            "error": f"Upstream dependency '{current}' failed while in progress"
                        }
                        failed_downstream.append(nid)
                        queue.append(nid)

            if failed_downstream:
                logger.warning(
                    "TaskGraph: propagated failure from %s to %d downstream nodes: %s",
                    subtask_id,
                    len(failed_downstream),
                    failed_downstream,
                )

            return failed_downstream

    def is_complete(self) -> bool:
        """
        True when all nodes have reached a terminal state
        (COMPLETED, FAILED, or CANCELLED).
        """
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        return all(
            node.status in terminal for node in self._graph.nodes.values()
        )

    def all_succeeded(self) -> bool:
        """True if every node is in COMPLETED status."""
        return all(
            node.status == TaskStatus.COMPLETED
            for node in self._graph.nodes.values()
        )

    def get_critical_path(self) -> list[str]:
        """
        Identify the longest dependency chain in the graph.

        Uses dynamic programming on topological order to find the
        longest path (by node count, not time estimate).

        Returns:
            Ordered list of subtask_ids forming the critical (longest) path.
        """
        topo_order = self.topological_sort()

        # Build adjacency (forward edges)
        adjacency: dict[str, list[str]] = {nid: [] for nid in self._graph.nodes}
        for src, dst in self._graph.edges:
            if src in adjacency:
                adjacency[src].append(dst)

        # DP: longest path ending at each node
        dist: dict[str, int] = {nid: 1 for nid in self._graph.nodes}
        predecessor: dict[str, str | None] = {nid: None for nid in self._graph.nodes}

        for node_id in topo_order:
            for neighbor in adjacency[node_id]:
                if dist[node_id] + 1 > dist[neighbor]:
                    dist[neighbor] = dist[node_id] + 1
                    predecessor[neighbor] = node_id

        # Find the node with maximum distance
        if not dist:
            return []

        end_node = max(dist, key=lambda nid: dist[nid])

        # Trace back the path
        path: list[str] = []
        current: str | None = end_node
        while current is not None:
            path.append(current)
            current = predecessor[current]

        path.reverse()
        return path

    def get_progress(self) -> dict[str, int]:
        """
        Return a status breakdown of all nodes.

        Returns:
            Dict mapping status name to count.
        """
        counts: dict[str, int] = {}
        for node in self._graph.nodes.values():
            status_name = node.status.value
            counts[status_name] = counts.get(status_name, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_node(self, subtask_id: str) -> SubtaskNode:
        """Retrieve a node or raise KeyError."""
        node = self._graph.nodes.get(subtask_id)
        if node is None:
            raise KeyError(f"Subtask '{subtask_id}' not found in graph")
        return node
