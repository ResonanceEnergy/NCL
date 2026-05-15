"""
Comprehensive tests for the NCL Agent Swarm system.

Covers models, blackboard, task graph, cost gate, LLM router,
agent base, orchestrator, and all specialist agent instantiation.
All external LLM/HTTP calls are mocked.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from runtime.swarm.models import (
    AgentSpec,
    AgentState,
    SubtaskNode,
    SwarmMessage,
    SwarmTask,
    TaskGraph,
    TaskResult,
    TaskStatus,
)
from runtime.swarm.blackboard import Blackboard
from runtime.swarm.cost_gate import CostGate
from runtime.swarm.llm_router import LLMResponse, LLMRouter, _estimate_cost
from runtime.swarm.agent_base import SwarmAgent
from runtime.swarm.task_graph import TaskGraphBuilder, TaskGraphEngine
from runtime.swarm.orchestrator import SwarmOrchestrator


# ===================================================================
# Helpers
# ===================================================================


def _make_llm_response(
    content: str = "mock response",
    model: str = "claude-sonnet-4-20250514",
    tokens_in: int = 100,
    tokens_out: int = 200,
    cost_cents: float = 0.33,
    latency_ms: int = 500,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_cents=cost_cents,
        latency_ms=latency_ms,
    )


def _make_router(config: dict[str, Any] | None = None) -> LLMRouter:
    return LLMRouter(config or {"anthropic_api_key": "test-key"})


def _make_blackboard() -> Blackboard:
    return Blackboard()


def _make_subtask_node(
    subtask_id: str = "st_1",
    title: str = "Test subtask",
    agent_type: str = "scholar",
    depends_on: list[str] | None = None,
    status: TaskStatus = TaskStatus.PENDING,
    input_data: dict[str, Any] | None = None,
) -> SubtaskNode:
    return SubtaskNode(
        subtask_id=subtask_id,
        title=title,
        agent_type=agent_type,
        depends_on=depends_on or [],
        status=status,
        input_data=input_data or {"description": "test description"},
    )


# ===================================================================
# 1. Model creation and validation
# ===================================================================


class TestModels:
    """Tests for Pydantic data models in models.py."""

    def test_swarm_task_defaults(self):
        task = SwarmTask(title="Test", objective="Do the thing")
        assert task.title == "Test"
        assert task.objective == "Do the thing"
        assert task.status == TaskStatus.PENDING
        assert task.priority == 5
        assert task.budget_cents == 500
        assert task.assigned_agent is None
        assert task.subtasks == []
        assert task.results == {}
        assert isinstance(task.task_id, str)
        assert len(task.task_id) == 16
        assert isinstance(task.created_at, datetime)

    def test_swarm_task_custom_values(self):
        task = SwarmTask(
            title="Custom",
            objective="Custom objective",
            priority=9,
            budget_cents=1000,
            tags=["urgent", "research"],
            metadata={"source": "council"},
        )
        assert task.priority == 9
        assert task.budget_cents == 1000
        assert task.tags == ["urgent", "research"]
        assert task.metadata == {"source": "council"}

    def test_swarm_task_priority_bounds(self):
        with pytest.raises(Exception):
            SwarmTask(title="T", objective="O", priority=0)
        with pytest.raises(Exception):
            SwarmTask(title="T", objective="O", priority=11)

    def test_swarm_message_creation(self):
        msg = SwarmMessage(
            task_id="task_abc",
            from_agent="orchestrator",
            to_agent="scholar_1",
            message_type="assign",
            payload={"data": "value"},
        )
        assert msg.task_id == "task_abc"
        assert msg.from_agent == "orchestrator"
        assert msg.to_agent == "scholar_1"
        assert msg.message_type == "assign"
        assert msg.payload == {"data": "value"}
        assert msg.priority == 5
        assert msg.acknowledged_at is None
        assert len(msg.message_id) == 16

    def test_swarm_message_types(self):
        valid_types = [
            "assign", "status_update", "result", "checkpoint",
            "error", "query", "response", "cancel",
        ]
        for mt in valid_types:
            msg = SwarmMessage(
                task_id="t", from_agent="a", to_agent="b", message_type=mt
            )
            assert msg.message_type == mt

    def test_agent_spec_defaults(self):
        spec = AgentSpec(agent_type="scholar")
        assert spec.agent_type == "scholar"
        assert spec.llm_backend == "claude"
        assert spec.status == AgentState.IDLE
        assert spec.current_task_id is None
        assert spec.tasks_completed == 0
        assert spec.total_cost_cents == 0.0
        assert len(spec.agent_id) == 16

    def test_subtask_node_creation(self):
        node = SubtaskNode(
            subtask_id="st_1",
            title="Research competitors",
            agent_type="scholar",
            depends_on=["st_0"],
        )
        assert node.subtask_id == "st_1"
        assert node.agent_type == "scholar"
        assert node.depends_on == ["st_0"]
        assert node.status == TaskStatus.PENDING
        assert node.input_data == {}
        assert node.output_data == {}

    def test_task_graph_ready_nodes(self):
        node_a = _make_subtask_node("a", status=TaskStatus.COMPLETED)
        node_b = _make_subtask_node("b", depends_on=["a"])
        node_c = _make_subtask_node("c", depends_on=["b"])

        graph = TaskGraph(
            task_id="t1",
            nodes={"a": node_a, "b": node_b, "c": node_c},
            edges=[("a", "b"), ("b", "c")],
        )

        ready = graph.ready_nodes()
        assert len(ready) == 1
        assert ready[0].subtask_id == "b"

    def test_task_graph_is_complete(self):
        node_a = _make_subtask_node("a", status=TaskStatus.COMPLETED)
        node_b = _make_subtask_node("b", status=TaskStatus.FAILED)
        graph = TaskGraph(task_id="t1", nodes={"a": node_a, "b": node_b})
        assert graph.is_complete() is True

    def test_task_graph_is_not_complete(self):
        node_a = _make_subtask_node("a", status=TaskStatus.COMPLETED)
        node_b = _make_subtask_node("b", status=TaskStatus.PENDING)
        graph = TaskGraph(task_id="t1", nodes={"a": node_a, "b": node_b})
        assert graph.is_complete() is False

    def test_task_result_creation(self):
        result = TaskResult(
            task_id="t1",
            subtask_id="st_1",
            agent_id="scholar_abc",
            output="Research findings here",
            confidence=0.9,
            cost_cents=1.5,
            duration_ms=3000,
            artifacts=["report.md"],
        )
        assert result.output == "Research findings here"
        assert result.confidence == 0.9
        assert result.cost_cents == 1.5
        assert result.artifacts == ["report.md"]

    def test_task_result_confidence_bounds(self):
        with pytest.raises(Exception):
            TaskResult(
                task_id="t", subtask_id="s", agent_id="a",
                output="x", confidence=1.5,
            )
        with pytest.raises(Exception):
            TaskResult(
                task_id="t", subtask_id="s", agent_id="a",
                output="x", confidence=-0.1,
            )

    def test_task_status_enum_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"

    def test_agent_state_enum_values(self):
        assert AgentState.IDLE.value == "idle"
        assert AgentState.WORKING.value == "working"
        assert AgentState.TERMINATED.value == "terminated"


# ===================================================================
# 2. Blackboard read/write operations
# ===================================================================


class TestBlackboard:
    """Tests for the Blackboard shared state store."""

    @pytest.mark.asyncio
    async def test_put_and_get(self):
        bb = _make_blackboard()
        await bb.put("key1", {"data": "value"})
        result = await bb.get("key1")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_missing_key(self):
        bb = _make_blackboard()
        result = await bb.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        bb = _make_blackboard()
        # Use ttl=1 and then patch time.time to simulate expiration
        await bb.put("expiring", "temp_value", ttl=1)
        # Value should exist before expiration
        result = await bb.get("expiring")
        assert result == "temp_value"

        # Fast-forward time to after expiration
        future = time.time() + 2
        with patch("runtime.swarm.blackboard.time.time", return_value=future):
            result = await bb.get("expiring")
            assert result is None

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix(self):
        bb = _make_blackboard()
        await bb.put("task:abc:status", "running")
        await bb.put("task:abc:result", "done")
        await bb.put("task:def:status", "pending")
        await bb.put("other:key", "value")

        keys = await bb.list_keys("task:abc:")
        assert sorted(keys) == ["task:abc:result", "task:abc:status"]

    @pytest.mark.asyncio
    async def test_list_keys_all(self):
        bb = _make_blackboard()
        await bb.put("a", 1)
        await bb.put("b", 2)
        keys = await bb.list_keys()
        assert sorted(keys) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_delete_existing_key(self):
        bb = _make_blackboard()
        await bb.put("to_delete", "value")
        deleted = await bb.delete("to_delete")
        assert deleted is True
        result = await bb.get("to_delete")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_missing_key(self):
        bb = _make_blackboard()
        deleted = await bb.delete("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_clear_namespace(self):
        bb = _make_blackboard()
        await bb.put("ns:a", 1)
        await bb.put("ns:b", 2)
        await bb.put("other:c", 3)

        count = await bb.clear_namespace("ns:")
        assert count == 2
        assert await bb.get("ns:a") is None
        assert await bb.get("ns:b") is None
        assert await bb.get("other:c") == 3

    @pytest.mark.asyncio
    async def test_subscribe_fires_on_match(self):
        bb = _make_blackboard()
        received = []

        async def callback(key, value):
            received.append((key, value))

        await bb.subscribe("task:*", callback)
        await bb.put("task:abc", "hello")
        await bb.put("other:xyz", "world")

        assert len(received) == 1
        assert received[0] == ("task:abc", "hello")

    @pytest.mark.asyncio
    async def test_subscribe_glob_pattern(self):
        bb = _make_blackboard()
        received = []

        async def callback(key, value):
            received.append(key)

        await bb.subscribe("result:*:*", callback)
        await bb.put("result:t1:st1", "data1")
        await bb.put("result:t1:st2", "data2")
        await bb.put("checkpoint:t1:st1", "data3")

        assert received == ["result:t1:st1", "result:t1:st2"]

    @pytest.mark.asyncio
    async def test_put_overwrites(self):
        bb = _make_blackboard()
        await bb.put("key", "original")
        await bb.put("key", "updated")
        assert await bb.get("key") == "updated"

    @pytest.mark.asyncio
    async def test_stop_is_safe(self):
        bb = _make_blackboard()
        await bb.put("key", "val")
        await bb.stop()
        # Should not raise


# ===================================================================
# 3. Task graph construction and ordering
# ===================================================================


class TestTaskGraphEngine:
    """Tests for TaskGraphBuilder and TaskGraphEngine."""

    def _make_linear_graph(self) -> TaskGraph:
        """A -> B -> C linear chain."""
        nodes = {
            "a": _make_subtask_node("a"),
            "b": _make_subtask_node("b", depends_on=["a"]),
            "c": _make_subtask_node("c", depends_on=["b"]),
        }
        return TaskGraph(
            task_id="t1",
            nodes=nodes,
            edges=[("a", "b"), ("b", "c")],
        )

    def _make_diamond_graph(self) -> TaskGraph:
        """
        A -> B, A -> C, B -> D, C -> D (diamond).
        """
        nodes = {
            "a": _make_subtask_node("a"),
            "b": _make_subtask_node("b", depends_on=["a"]),
            "c": _make_subtask_node("c", depends_on=["a"]),
            "d": _make_subtask_node("d", depends_on=["b", "c"]),
        }
        return TaskGraph(
            task_id="t2",
            nodes=nodes,
            edges=[("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
        )

    def test_topological_sort_linear(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        order = engine.topological_sort()
        assert order == ["a", "b", "c"]

    def test_topological_sort_diamond(self):
        graph = self._make_diamond_graph()
        engine = TaskGraphEngine(graph)
        order = engine.topological_sort()
        assert order[0] == "a"
        assert order[-1] == "d"
        # b and c can be in either order
        assert set(order[1:3]) == {"b", "c"}

    def test_get_ready_nodes_initial(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        ready = engine.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].subtask_id == "a"

    def test_get_ready_nodes_diamond_parallel(self):
        graph = self._make_diamond_graph()
        engine = TaskGraphEngine(graph)

        # Complete A
        engine.mark_complete("a", {"output": "done"})
        ready = engine.get_ready_nodes()
        ready_ids = {n.subtask_id for n in ready}
        assert ready_ids == {"b", "c"}

    def test_mark_complete_returns_newly_ready(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)

        newly_ready = engine.mark_complete("a", {"output": "done"})
        assert "b" in newly_ready

    def test_mark_complete_stores_output(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)

        engine.mark_complete("a", {"output": "result_a"})
        node_a = graph.nodes["a"]
        assert node_a.status == TaskStatus.COMPLETED
        assert node_a.output_data == {"output": "result_a"}

    def test_mark_failed_propagates(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)

        failed_downstream = engine.mark_failed("a", "some error")
        # b depends on a, c depends on b -- both should fail
        assert "b" in failed_downstream
        assert "c" in failed_downstream
        assert graph.nodes["a"].status == TaskStatus.FAILED
        assert graph.nodes["b"].status == TaskStatus.FAILED
        assert graph.nodes["c"].status == TaskStatus.FAILED

    def test_mark_failed_partial(self):
        graph = self._make_diamond_graph()
        engine = TaskGraphEngine(graph)
        engine.mark_complete("a", {})

        # Fail only b
        failed_downstream = engine.mark_failed("b", "error in b")
        # d depends on b AND c, so d should be failed since b failed
        assert "d" in failed_downstream
        assert graph.nodes["c"].status == TaskStatus.PENDING  # c is unaffected

    def test_is_complete_all_terminal(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        engine.mark_complete("a", {})
        engine.mark_complete("b", {})
        engine.mark_complete("c", {})
        assert engine.is_complete() is True

    def test_all_succeeded(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        engine.mark_complete("a", {})
        engine.mark_complete("b", {})
        engine.mark_complete("c", {})
        assert engine.all_succeeded() is True

    def test_all_succeeded_false_on_failure(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        engine.mark_complete("a", {})
        engine.mark_failed("b", "err")
        assert engine.all_succeeded() is False

    def test_get_critical_path_linear(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        path = engine.get_critical_path()
        assert path == ["a", "b", "c"]

    def test_get_critical_path_diamond(self):
        graph = self._make_diamond_graph()
        engine = TaskGraphEngine(graph)
        path = engine.get_critical_path()
        assert len(path) == 3
        assert path[0] == "a"
        assert path[-1] == "d"

    def test_get_progress(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        engine.mark_complete("a", {})
        progress = engine.get_progress()
        assert progress["completed"] == 1
        assert progress["pending"] == 2

    def test_unknown_subtask_raises(self):
        graph = self._make_linear_graph()
        engine = TaskGraphEngine(graph)
        with pytest.raises(KeyError):
            engine.mark_complete("nonexistent", {})

    def test_cycle_detection(self):
        """Topological sort should raise on a cycle."""
        nodes = {
            "a": _make_subtask_node("a", depends_on=["c"]),
            "b": _make_subtask_node("b", depends_on=["a"]),
            "c": _make_subtask_node("c", depends_on=["b"]),
        }
        graph = TaskGraph(
            task_id="cycle",
            nodes=nodes,
            edges=[("c", "a"), ("a", "b"), ("b", "c")],
        )
        engine = TaskGraphEngine(graph)
        with pytest.raises(ValueError, match="[Cc]ycle"):
            engine.topological_sort()


class TestTaskGraphBuilder:
    """Tests for the LLM-based TaskGraphBuilder."""

    @pytest.mark.asyncio
    async def test_build_parses_valid_response(self):
        mock_router = AsyncMock(spec=LLMRouter)
        llm_response_content = json.dumps({
            "subtasks": [
                {
                    "id": "st_1",
                    "title": "Research topic",
                    "agent_type": "scholar",
                    "description": "Deep research",
                    "depends_on": [],
                },
                {
                    "id": "st_2",
                    "title": "Write report",
                    "agent_type": "scribe",
                    "description": "Write findings",
                    "depends_on": ["st_1"],
                },
            ]
        })
        mock_router.call.return_value = _make_llm_response(content=llm_response_content)

        builder = TaskGraphBuilder(llm_router=mock_router)
        graph = await builder.build(task_id="t1", objective="Research and report")

        assert len(graph.nodes) == 2
        assert "st_1" in graph.nodes
        assert "st_2" in graph.nodes
        assert graph.nodes["st_2"].depends_on == ["st_1"]
        assert ("st_1", "st_2") in graph.edges

    @pytest.mark.asyncio
    async def test_build_retries_on_bad_json(self):
        mock_router = AsyncMock(spec=LLMRouter)
        bad_response = _make_llm_response(content="not json at all")
        good_response = _make_llm_response(content=json.dumps({
            "subtasks": [{
                "id": "st_1", "title": "T", "agent_type": "scholar",
                "description": "D", "depends_on": [],
            }]
        }))
        mock_router.call.side_effect = [bad_response, good_response]

        builder = TaskGraphBuilder(llm_router=mock_router)
        graph = await builder.build(task_id="t1", objective="test")
        assert len(graph.nodes) == 1
        assert mock_router.call.call_count == 2

    @pytest.mark.asyncio
    async def test_build_raises_after_max_retries(self):
        mock_router = AsyncMock(spec=LLMRouter)
        mock_router.call.return_value = _make_llm_response(content="bad json")

        builder = TaskGraphBuilder(llm_router=mock_router)
        with pytest.raises(ValueError, match="Failed to parse"):
            await builder.build(task_id="t1", objective="test", max_retries=1)

    @pytest.mark.asyncio
    async def test_build_detects_cycle(self):
        mock_router = AsyncMock(spec=LLMRouter)
        cyclic_response = json.dumps({
            "subtasks": [
                {"id": "a", "title": "A", "agent_type": "scholar",
                 "description": "D", "depends_on": ["b"]},
                {"id": "b", "title": "B", "agent_type": "coder",
                 "description": "D", "depends_on": ["a"]},
            ]
        })
        mock_router.call.return_value = _make_llm_response(content=cyclic_response)

        builder = TaskGraphBuilder(llm_router=mock_router)
        with pytest.raises(ValueError, match="[Cc]ycle"):
            await builder.build(task_id="t1", objective="test")

    @pytest.mark.asyncio
    async def test_build_strips_markdown_fences(self):
        mock_router = AsyncMock(spec=LLMRouter)
        fenced = '```json\n' + json.dumps({
            "subtasks": [{
                "id": "st_1", "title": "T", "agent_type": "scout",
                "description": "D", "depends_on": [],
            }]
        }) + '\n```'
        mock_router.call.return_value = _make_llm_response(content=fenced)

        builder = TaskGraphBuilder(llm_router=mock_router)
        graph = await builder.build(task_id="t1", objective="test")
        assert len(graph.nodes) == 1


# ===================================================================
# 4. Cost gate budget checks
# ===================================================================


class TestCostGate:
    """Tests for the CostGate budget enforcement."""

    @pytest.mark.asyncio
    async def test_allocate_and_remaining(self):
        gate = CostGate()
        await gate.allocate("task1", 1000)
        remaining = await gate.remaining("task1")
        assert remaining == 1000

    @pytest.mark.asyncio
    async def test_spend_decreases_remaining(self):
        gate = CostGate()
        await gate.allocate("task1", 1000)
        await gate.spend("task1", 300, "LLM call")
        remaining = await gate.remaining("task1")
        assert remaining == 700

    @pytest.mark.asyncio
    async def test_can_afford_true(self):
        gate = CostGate()
        await gate.allocate("task1", 1000)
        assert await gate.can_afford("task1", 500) is True

    @pytest.mark.asyncio
    async def test_can_afford_false(self):
        gate = CostGate()
        await gate.allocate("task1", 100)
        assert await gate.can_afford("task1", 200) is False

    @pytest.mark.asyncio
    async def test_exceeded_false_when_under_budget(self):
        gate = CostGate()
        await gate.allocate("task1", 1000)
        await gate.spend("task1", 500, "call")
        assert await gate.exceeded("task1") is False

    @pytest.mark.asyncio
    async def test_exceeded_true_when_over_budget(self):
        gate = CostGate()
        await gate.allocate("task1", 100)
        await gate.spend("task1", 150, "expensive call")
        assert await gate.exceeded("task1") is True

    @pytest.mark.asyncio
    async def test_spend_without_allocation_raises(self):
        gate = CostGate()
        with pytest.raises(KeyError):
            await gate.spend("unknown", 10, "test")

    @pytest.mark.asyncio
    async def test_remaining_without_allocation_raises(self):
        gate = CostGate()
        with pytest.raises(KeyError):
            await gate.remaining("unknown")

    @pytest.mark.asyncio
    async def test_deallocate(self):
        gate = CostGate()
        await gate.allocate("task1", 1000)
        await gate.deallocate("task1")
        with pytest.raises(KeyError):
            await gate.remaining("task1")

    @pytest.mark.asyncio
    async def test_get_spend_log(self):
        gate = CostGate()
        await gate.allocate("task1", 1000)
        await gate.spend("task1", 100, "first call")
        await gate.spend("task1", 200, "second call")

        log = await gate.get_spend_log("task1")
        assert len(log) == 2
        assert log[0]["amount_cents"] == 100
        assert log[0]["description"] == "first call"
        assert log[1]["amount_cents"] == 200

    @pytest.mark.asyncio
    async def test_get_summary(self):
        gate = CostGate()
        await gate.allocate("t1", 500)
        await gate.allocate("t2", 300)
        await gate.spend("t1", 100, "c1")
        await gate.spend("t2", 50, "c2")

        summary = await gate.get_summary()
        assert summary["active_tasks"] == 2
        assert summary["total_allocated_cents"] == 800
        assert summary["total_spent_cents"] == 150
        assert summary["total_remaining_cents"] == 650

    @pytest.mark.asyncio
    async def test_reallocate_preserves_spend(self):
        gate = CostGate()
        await gate.allocate("task1", 500)
        await gate.spend("task1", 100, "first")
        await gate.allocate("task1", 1000)  # reallocate

        remaining = await gate.remaining("task1")
        assert remaining == 900  # 1000 - 100

    @pytest.mark.asyncio
    async def test_paperclip_failure_is_silent(self):
        mock_paperclip = AsyncMock()
        mock_paperclip.record_spend.side_effect = ConnectionError("offline")

        gate = CostGate(paperclip_client=mock_paperclip)
        await gate.allocate("task1", 1000)
        # Should not raise despite paperclip failure
        await gate.spend("task1", 50, "test")
        assert await gate.remaining("task1") == 950


# ===================================================================
# 5. LLM router provider selection
# ===================================================================


class TestLLMRouter:
    """Tests for the LLMRouter."""

    def test_cost_estimation(self):
        cost = _estimate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
        # input: 300 cents/1M, output: 1500 cents/1M -> 1800 cents
        assert cost == 1800.0

    def test_cost_estimation_unknown_model(self):
        cost = _estimate_cost("unknown-model", 1000, 1000)
        assert cost == 0.0

    def test_router_init(self):
        router = _make_router()
        assert router.total_cost_cents == 0.0
        assert router.call_count == 0

    @pytest.mark.asyncio
    async def test_call_dispatches_to_anthropic(self):
        router = _make_router({"anthropic_api_key": "test"})
        mock_response = _make_llm_response()

        with patch.object(router, "_call_anthropic", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_response
            result = await router.call(backend="claude", prompt="Hello")

            assert result.content == "mock response"
            assert router.total_cost_cents == mock_response.cost_cents
            assert router.call_count == 1

    @pytest.mark.asyncio
    async def test_call_fallback_chain(self):
        router = _make_router({"anthropic_api_key": "test"})

        with patch.object(router, "_dispatch", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.side_effect = [
                RuntimeError("first fails"),
                _make_llm_response(model="ollama:qwen3:32b"),
            ]
            result = await router.call(backend="claude", prompt="test")
            assert result.model == "ollama:qwen3:32b"
            assert mock_dispatch.call_count == 2

    @pytest.mark.asyncio
    async def test_call_all_fail_raises(self):
        router = _make_router({"anthropic_api_key": "test"})

        with patch.object(router, "_dispatch", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.side_effect = RuntimeError("all fail")
            with pytest.raises(RuntimeError, match="All backends in chain"):
                await router.call(backend="claude", prompt="test")

    @pytest.mark.asyncio
    async def test_dispatch_routing(self):
        router = _make_router()
        mock_resp = _make_llm_response()

        for prefix, method_name in [
            ("claude-sonnet-4-20250514", "_call_anthropic"),
            ("grok-3", "_call_xai"),
            ("gemini-2.5-pro", "_call_google"),
            ("gpt-4o", "_call_openai"),
            ("sonar-pro", "_call_perplexity"),
        ]:
            with patch.object(router, method_name, new_callable=AsyncMock) as mock_method:
                mock_method.return_value = mock_resp
                result = await router._dispatch(
                    model_id=prefix, prompt="test",
                    max_tokens=100, temperature=0.7, system_prompt=None,
                )
                mock_method.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_ollama(self):
        router = _make_router({"ollama_host": "http://localhost:11434"})
        mock_resp = _make_llm_response()

        with patch.object(router, "_call_ollama", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = mock_resp
            await router._dispatch(
                model_id="ollama:qwen3:32b", prompt="test",
                max_tokens=100, temperature=0.7, system_prompt=None,
            )
            mock_method.assert_called_once_with(
                "qwen3:32b", "test", 100, 0.7, None
            )

    @pytest.mark.asyncio
    async def test_dispatch_unknown_model_raises(self):
        router = _make_router()
        with pytest.raises(ValueError, match="Unknown model_id"):
            await router._dispatch(
                model_id="totally_unknown_model", prompt="test",
                max_tokens=100, temperature=0.7, system_prompt=None,
            )

    @pytest.mark.asyncio
    async def test_close(self):
        router = _make_router()
        await router.close()  # Should not raise even without a client


# ===================================================================
# 6. Agent base initialization
# ===================================================================


class ConcreteAgent(SwarmAgent):
    """Minimal concrete implementation for testing the abstract base."""

    async def execute(self, task: SubtaskNode) -> TaskResult:
        self._start_task(task)
        response = await self.call_llm("Do the thing")
        self._finish_task()
        return TaskResult(
            task_id=task.subtask_id,
            subtask_id=task.subtask_id,
            agent_id=self.agent_id,
            output=response.content,
            confidence=0.9,
            cost_cents=response.cost_cents,
            duration_ms=100,
        )


class TestAgentBase:
    """Tests for the SwarmAgent abstract base class."""

    def _make_agent(self) -> ConcreteAgent:
        router = MagicMock(spec=LLMRouter)
        bb = MagicMock(spec=Blackboard)
        return ConcreteAgent(
            agent_id="test_agent_1",
            agent_type="tester",
            config={"default_llm": "claude"},
            llm_router=router,
            blackboard=bb,
        )

    def test_init_properties(self):
        agent = self._make_agent()
        assert agent.agent_id == "test_agent_1"
        assert agent.agent_type == "tester"
        assert agent.state == AgentState.IDLE
        assert agent.cost_spent == 0.0

    def test_start_and_finish_task(self):
        agent = self._make_agent()
        node = _make_subtask_node()

        agent._start_task(node)
        assert agent.state == AgentState.WORKING
        assert agent._current_task_id == node.subtask_id

        agent._finish_task()
        assert agent.state == AgentState.IDLE
        assert agent._current_task_id is None

    @pytest.mark.asyncio
    async def test_execute(self):
        router = AsyncMock(spec=LLMRouter)
        bb = AsyncMock(spec=Blackboard)
        agent = ConcreteAgent(
            agent_id="agent1", agent_type="tester",
            config={"default_llm": "claude"},
            llm_router=router, blackboard=bb,
        )
        router.call.return_value = _make_llm_response(content="test output")

        node = _make_subtask_node()
        result = await agent.execute(node)

        assert result.output == "test output"
        assert result.confidence == 0.9
        assert agent.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_call_llm_tracks_cost(self):
        router = AsyncMock(spec=LLMRouter)
        bb = AsyncMock(spec=Blackboard)
        agent = ConcreteAgent(
            agent_id="agent1", agent_type="tester",
            config={"default_llm": "claude"},
            llm_router=router, blackboard=bb,
        )
        router.call.return_value = _make_llm_response(cost_cents=5.0)

        await agent.call_llm("test prompt")
        assert agent.cost_spent == 5.0

        router.call.return_value = _make_llm_response(cost_cents=3.0)
        await agent.call_llm("another prompt")
        assert agent.cost_spent == 8.0

    @pytest.mark.asyncio
    async def test_checkpoint(self):
        router = AsyncMock(spec=LLMRouter)
        bb = AsyncMock(spec=Blackboard)
        agent = ConcreteAgent(
            agent_id="agent1", agent_type="tester",
            config={}, llm_router=router, blackboard=bb,
        )

        node = _make_subtask_node(subtask_id="st_42")
        agent._start_task(node)
        await agent.checkpoint({"step": 1, "data": "partial"})

        bb.put.assert_called_once()
        call_kwargs = bb.put.call_args
        assert "checkpoint:agent1:st_42" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_cleanup(self):
        agent = self._make_agent()
        await agent.cleanup()
        assert agent.state == AgentState.TERMINATED


# ===================================================================
# 7. Orchestrator task submission and basic flow
# ===================================================================


class TestOrchestrator:
    """Tests for the SwarmOrchestrator."""

    def _make_orchestrator(
        self,
        config: dict[str, Any] | None = None,
        router: LLMRouter | None = None,
        blackboard: Blackboard | None = None,
    ) -> SwarmOrchestrator:
        cfg = config or {"anthropic_api_key": "test"}
        r = router or MagicMock(spec=LLMRouter)
        r.call_count = 0
        r.total_cost_cents = 0.0
        bb = blackboard or AsyncMock(spec=Blackboard)
        return SwarmOrchestrator(config=cfg, llm_router=r, blackboard=bb)

    def test_init(self):
        orch = self._make_orchestrator()
        assert orch._total_submitted == 0
        assert orch._total_completed == 0
        assert orch._total_failed == 0

    def test_get_stats(self):
        orch = self._make_orchestrator()
        stats = orch.get_stats()
        assert stats["total_submitted"] == 0
        assert stats["active_tasks"] == 0
        assert stats["completed_tasks"] == 0
        assert stats["failed_tasks"] == 0

    def test_get_task_returns_none_for_missing(self):
        orch = self._make_orchestrator()
        assert orch.get_task("nonexistent") is None

    def test_list_tasks_empty(self):
        orch = self._make_orchestrator()
        assert orch.list_tasks() == []

    @pytest.mark.asyncio
    async def test_submit_task_creates_task(self):
        orch = self._make_orchestrator()

        # Patch the background execution to avoid actually running
        with patch.object(orch, "_execute_task", new_callable=AsyncMock) as mock_exec:
            with patch.object(orch, "_ensure_maintenance_running", new_callable=AsyncMock):
                task = await orch.submit_task(
                    title="Test Task",
                    objective="Test the swarm",
                    priority=7,
                    budget_cents=300,
                    tags=["test"],
                )

        assert task.title == "Test Task"
        assert task.objective == "Test the swarm"
        assert task.priority == 7
        assert task.budget_cents == 300
        assert task.tags == ["test"]
        assert orch._total_submitted == 1
        assert orch.get_task(task.task_id) is task

    @pytest.mark.asyncio
    async def test_cancel_task(self):
        orch = self._make_orchestrator()

        # Manually insert a task
        task = SwarmTask(title="Cancel me", objective="test", status=TaskStatus.IN_PROGRESS)
        orch._tasks[task.task_id] = task
        orch._task_locks[task.task_id] = asyncio.Lock()

        result = await orch.cancel_task(task.task_id)
        assert result is True
        assert task.status == TaskStatus.CANCELLED
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        orch = self._make_orchestrator()
        result = await orch.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_already_completed_task(self):
        orch = self._make_orchestrator()
        task = SwarmTask(title="Done", objective="test", status=TaskStatus.COMPLETED)
        orch._tasks[task.task_id] = task
        orch._task_locks[task.task_id] = asyncio.Lock()

        result = await orch.cancel_task(task.task_id)
        assert result is False

    def test_list_tasks_with_filter(self):
        orch = self._make_orchestrator()
        t1 = SwarmTask(title="A", objective="o", status=TaskStatus.COMPLETED)
        t2 = SwarmTask(title="B", objective="o", status=TaskStatus.PENDING)
        t3 = SwarmTask(title="C", objective="o", status=TaskStatus.COMPLETED)
        orch._tasks = {t1.task_id: t1, t2.task_id: t2, t3.task_id: t3}

        completed = orch.list_tasks(status_filter=TaskStatus.COMPLETED)
        assert len(completed) == 2
        pending = orch.list_tasks(status_filter=TaskStatus.PENDING)
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_shutdown(self):
        orch = self._make_orchestrator()
        # Should not raise
        await orch.shutdown()


# ===================================================================
# 8. Specialist agent instantiation
# ===================================================================


class TestSpecialistAgents:
    """Verify all 7 specialist agents can be instantiated via the registry."""

    def _make_specialist(self, agent_type: str) -> SwarmAgent:
        from runtime.swarm.agents import get_agent_class

        cls = get_agent_class(agent_type)
        router = MagicMock(spec=LLMRouter)
        bb = MagicMock(spec=Blackboard)
        return cls(
            agent_id=f"{agent_type}_test",
            agent_type=agent_type,
            config={"default_llm": "claude"},
            llm_router=router,
            blackboard=bb,
        )

    def test_analyst_instantiation(self):
        agent = self._make_specialist("analyst")
        assert agent.agent_type == "analyst"
        assert agent.state == AgentState.IDLE

    def test_architect_instantiation(self):
        agent = self._make_specialist("architect")
        assert agent.agent_type == "architect"

    def test_coder_instantiation(self):
        agent = self._make_specialist("coder")
        assert agent.agent_type == "coder"

    def test_scholar_instantiation(self):
        agent = self._make_specialist("scholar")
        assert agent.agent_type == "scholar"

    def test_scout_instantiation(self):
        agent = self._make_specialist("scout")
        assert agent.agent_type == "scout"

    def test_scribe_instantiation(self):
        agent = self._make_specialist("scribe")
        assert agent.agent_type == "scribe"

    def test_sentinel_instantiation(self):
        agent = self._make_specialist("sentinel")
        assert agent.agent_type == "sentinel"

    def test_all_registered_types(self):
        from runtime.swarm.agents import list_agent_types

        types = list_agent_types()
        expected = {"analyst", "architect", "coder", "scholar", "scout", "scribe", "sentinel"}
        assert set(types) == expected

    def test_unknown_agent_type_raises(self):
        from runtime.swarm.agents import get_agent_class

        with pytest.raises(KeyError, match="No agent registered"):
            get_agent_class("nonexistent")

    @pytest.mark.asyncio
    async def test_specialist_execute_mocked(self):
        """Verify a specialist agent's execute method runs with mocked LLM."""
        from runtime.swarm.agents import get_agent_class

        cls = get_agent_class("scholar")
        router = AsyncMock(spec=LLMRouter)
        bb = AsyncMock(spec=Blackboard)
        agent = cls(
            agent_id="scholar_test",
            agent_type="scholar",
            config={"default_llm": "claude"},
            llm_router=router,
            blackboard=bb,
        )

        # Mock all LLM calls the scholar might make
        router.call.return_value = _make_llm_response(
            content="Research findings with citations",
            cost_cents=2.0,
        )

        node = _make_subtask_node(
            agent_type="scholar",
            input_data={"question": "What is quantum computing?"},
        )
        result = await agent.execute(node)
        assert isinstance(result, TaskResult)
        assert result.agent_id == "scholar_test"
        assert agent.state == AgentState.IDLE


# ===================================================================
# LLM Response dataclass
# ===================================================================


class TestLLMResponse:
    """Tests for the LLMResponse frozen dataclass."""

    def test_creation(self):
        resp = LLMResponse(
            content="hello",
            model="claude-sonnet-4-20250514",
            tokens_in=50,
            tokens_out=100,
            cost_cents=0.5,
            latency_ms=200,
        )
        assert resp.content == "hello"
        assert resp.model == "claude-sonnet-4-20250514"
        assert resp.tokens_in == 50
        assert resp.tokens_out == 100

    def test_immutable(self):
        resp = _make_llm_response()
        with pytest.raises(AttributeError):
            resp.content = "new"  # type: ignore[misc]


# ===================================================================
# Scheduler hooks
# ===================================================================


class TestSchedulerHooks:
    """Tests for SwarmSchedulerHooks."""

    def test_init(self):
        from runtime.swarm.scheduler_hooks import SwarmSchedulerHooks

        mock_swarm = MagicMock()
        hooks = SwarmSchedulerHooks(swarm=mock_swarm)
        assert hooks.swarm is mock_swarm
        assert hooks.scheduler is None
        assert hooks._running is False

    def test_default_recurring_tasks(self):
        from runtime.swarm.scheduler_hooks import SwarmSchedulerHooks

        hooks = SwarmSchedulerHooks(swarm=MagicMock())
        assert len(hooks._recurring_tasks) == 2
        titles = [t["title"] for t in hooks._recurring_tasks]
        assert "Daily Intelligence Brief" in titles
        assert "Weekly Strategy Review" in titles

    @pytest.mark.asyncio
    async def test_attach_and_detach(self):
        from runtime.swarm.scheduler_hooks import SwarmSchedulerHooks

        mock_swarm = MagicMock()
        mock_swarm.get_stats.return_value = {"active_tasks": 0}
        hooks = SwarmSchedulerHooks(swarm=mock_swarm)

        await hooks.attach()
        assert hooks._running is True
        assert hooks._maintenance_handle is not None

        await hooks.detach()
        assert hooks._running is False
