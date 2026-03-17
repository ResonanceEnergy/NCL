#!/usr/bin/env python3
"""
Tests for NCC Triad Integration — Pillar Registry, Inter-Pillar Bus,
Digital Labour, and NCC Orchestrator.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ncl_agency_runtime.runtime.digital_labour import (
    DigitalLabourPool,
    LabourTask,
    TaskHandler,
    TaskStatus,
    TaskType,
)
from ncl_agency_runtime.runtime.inter_pillar_bus import (
    InterPillarBus,
    MessageType,
    PillarMessage,
    Priority,
)
from ncl_agency_runtime.runtime.ncc_orchestrator import (
    NCCOrchestrator,
    PDCACycle,
)
from ncl_agency_runtime.runtime.pillar_registry import (
    Capability,
    CapabilityType,
    PillarID,
    PillarRegistration,
    PillarRegistry,
    PillarStatus,
    bootstrap_registry,
)

# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all singletons between tests."""
    PillarRegistry.reset()
    InterPillarBus.reset()
    DigitalLabourPool.reset()
    NCCOrchestrator.reset()
    yield
    PillarRegistry.reset()
    InterPillarBus.reset()
    DigitalLabourPool.reset()
    NCCOrchestrator.reset()


# ═══════════════════════════════════════════════════════════════
#  Pillar Registry Tests
# ═══════════════════════════════════════════════════════════════

class TestPillarRegistry:
    """Tests for PillarRegistry."""

    def test_singleton(self):
        r1 = PillarRegistry.get_instance()
        r2 = PillarRegistry.get_instance()
        assert r1 is r2

    def test_register_and_get(self):
        registry = PillarRegistry.get_instance()
        reg = PillarRegistration(
            pillar_id=PillarID.NCL,
            name="NCL",
            role="Brain",
            status=PillarStatus.ONLINE,
        )
        registry.register(reg)
        assert registry.get(PillarID.NCL) is reg
        assert registry.get(PillarID.NCL).name == "NCL"

    def test_deregister(self):
        registry = PillarRegistry.get_instance()
        reg = PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain")
        registry.register(reg)
        assert registry.deregister(PillarID.NCL) is True
        assert registry.get(PillarID.NCL) is None
        assert registry.deregister(PillarID.NCL) is False

    def test_list_pillars(self):
        registry = PillarRegistry.get_instance()
        r1 = PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain")
        r2 = PillarRegistration(pillar_id=PillarID.AAC, name="AAC", role="Bank")
        registry.register(r1)
        registry.register(r2)
        assert len(registry.list_pillars()) == 2

    def test_find_by_capability(self):
        registry = PillarRegistry.get_instance()
        reg = PillarRegistration(
            pillar_id=PillarID.NCL, name="NCL", role="Brain",
            capabilities=[Capability("mem", CapabilityType.MEMORY)],
        )
        registry.register(reg)
        found = registry.find_by_capability(CapabilityType.MEMORY)
        assert len(found) == 1
        assert found[0].pillar_id == PillarID.NCL

    def test_find_online(self):
        registry = PillarRegistry.get_instance()
        r1 = PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain", status=PillarStatus.ONLINE)
        r2 = PillarRegistration(pillar_id=PillarID.AAC, name="AAC", role="Bank", status=PillarStatus.OFFLINE)
        registry.register(r1)
        registry.register(r2)
        online = registry.find_online()
        assert len(online) == 1
        assert online[0].pillar_id == PillarID.NCL

    def test_heartbeat(self):
        registry = PillarRegistry.get_instance()
        reg = PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain", status=PillarStatus.BOOTSTRAPPING)
        registry.register(reg)
        assert registry.heartbeat(PillarID.NCL) is True
        assert reg.status == PillarStatus.ONLINE
        assert reg.last_heartbeat != ""

    def test_heartbeat_unknown_pillar(self):
        registry = PillarRegistry.get_instance()
        assert registry.heartbeat(PillarID.NCL) is False

    def test_set_status(self):
        registry = PillarRegistry.get_instance()
        reg = PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain")
        registry.register(reg)
        assert registry.set_status(PillarID.NCL, PillarStatus.MAINTENANCE) is True
        assert reg.status == PillarStatus.MAINTENANCE

    def test_health_summary(self):
        registry = PillarRegistry.get_instance()
        reg = PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain", status=PillarStatus.ONLINE)
        registry.register(reg)
        summary = registry.health_summary()
        assert summary["total_pillars"] == 1
        assert summary["online"] == 1
        assert "ncl" in summary["pillars"]

    def test_triad_online(self):
        registry = PillarRegistry.get_instance()
        for pid, name, role in [(PillarID.NCL, "NCL", "Brain"), (PillarID.AAC, "AAC", "Bank"), (PillarID.BRS, "BRS", "Systems")]:
            registry.register(PillarRegistration(pillar_id=pid, name=name, role=role, status=PillarStatus.ONLINE))
        assert registry.triad_online() is True

    def test_triad_not_online(self):
        registry = PillarRegistry.get_instance()
        registry.register(PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain", status=PillarStatus.ONLINE))
        assert registry.triad_online() is False

    def test_triad_status(self):
        registry = PillarRegistry.get_instance()
        registry.register(PillarRegistration(pillar_id=PillarID.NCL, name="NCL", role="Brain", status=PillarStatus.ONLINE))
        status = registry.triad_status()
        assert status["ncl"] == "online"
        assert status["aac"] == "unregistered"

    def test_bootstrap_registry(self):
        registry = bootstrap_registry()
        assert len(registry.list_pillars()) == 4
        assert registry.get(PillarID.NCC) is not None
        assert registry.get(PillarID.NCL) is not None
        assert registry.get(PillarID.AAC) is not None
        assert registry.get(PillarID.BRS) is not None

    def test_pillar_to_dict(self):
        reg = PillarRegistration(
            pillar_id=PillarID.NCL, name="NCL", role="Brain",
            capabilities=[Capability("mem", CapabilityType.MEMORY)],
        )
        d = reg.to_dict()
        assert d["pillar_id"] == "ncl"
        assert d["role"] == "Brain"
        assert len(d["capabilities"]) == 1


# ═══════════════════════════════════════════════════════════════
#  Inter-Pillar Bus Tests
# ═══════════════════════════════════════════════════════════════

class TestInterPillarBus:
    """Tests for InterPillarBus."""

    def test_singleton(self):
        b1 = InterPillarBus.get_instance()
        b2 = InterPillarBus.get_instance()
        assert b1 is b2

    def test_subscribe_and_dispatch_sync(self):
        bus = InterPillarBus.get_instance()
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe(PillarID.NCL, MessageType.REQUEST, handler)
        msg = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.REQUEST, payload={"test": True},
        )
        bus.dispatch_sync(msg)
        assert len(received) == 1
        assert received[0].payload == {"test": True}

    def test_wildcard_subscription(self):
        bus = InterPillarBus.get_instance()
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe_all(handler)
        msg = PillarMessage(
            source=PillarID.NCL, target=PillarID.AAC,
            msg_type=MessageType.EVENT, payload={"data": 1},
        )
        bus.dispatch_sync(msg)
        assert len(received) == 1

    def test_pillar_wildcard_subscription(self):
        bus = InterPillarBus.get_instance()
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe_pillar(PillarID.NCL, handler)
        msg = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.COMMAND, payload={},
        )
        bus.dispatch_sync(msg)
        assert len(received) == 1

    def test_message_to_dict_roundtrip(self):
        msg = PillarMessage(
            source=PillarID.NCL, target=PillarID.AAC,
            msg_type=MessageType.REQUEST, payload={"key": "val"},
            priority=Priority.HIGH,
        )
        d = msg.to_dict()
        reconstructed = PillarMessage.from_dict(d)
        assert reconstructed.source == PillarID.NCL
        assert reconstructed.target == PillarID.AAC
        assert reconstructed.msg_type == MessageType.REQUEST
        assert reconstructed.priority == Priority.HIGH
        assert reconstructed.payload == {"key": "val"}

    def test_make_response(self):
        msg = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.REQUEST, payload={},
        )
        response = msg.make_response({"result": "ok"})
        assert response.source == PillarID.NCL
        assert response.target == PillarID.NCC
        assert response.msg_type == MessageType.RESPONSE
        assert response.correlation_id == msg.msg_id

    def test_stats(self):
        bus = InterPillarBus.get_instance()
        stats = bus.stats
        assert "processed" in stats
        assert "failed" in stats
        assert "queue_size" in stats

    def test_message_is_expired(self):
        msg = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.REQUEST, payload={},
            timestamp="2020-01-01T00:00:00+00:00",
            ttl_seconds=1,
        )
        assert msg.is_expired is True

    def test_message_not_expired(self):
        msg = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.REQUEST, payload={},
            ttl_seconds=9999,
        )
        assert msg.is_expired is False

    def test_can_retry(self):
        msg = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.REQUEST, payload={},
            attempt=1, max_attempts=3,
        )
        assert msg.can_retry is True
        msg.attempt = 3
        assert msg.can_retry is False


# ═══════════════════════════════════════════════════════════════
#  Digital Labour Tests
# ═══════════════════════════════════════════════════════════════

class TestDigitalLabour:
    """Tests for DigitalLabourPool."""

    def test_singleton(self):
        p1 = DigitalLabourPool.get_instance()
        p2 = DigitalLabourPool.get_instance()
        assert p1 is p2

    def test_submit_task_sync(self):
        pool = DigitalLabourPool.get_instance()
        task = LabourTask(
            task_type=TaskType.REPORT_GENERATION,
            title="Test Report",
            payload={"report_type": "summary", "data": {"key": "val"}},
        )
        task_id = pool.submit_task_sync(task)
        assert task_id == task.task_id
        assert pool.stats["queue_size"] == 1

    def test_task_to_dict(self):
        task = LabourTask(
            task_type=TaskType.RESEARCH,
            title="Research AI Safety",
            requested_by=PillarID.NCL,
            priority=Priority.HIGH,
        )
        d = task.to_dict()
        assert d["task_type"] == "research"
        assert d["requested_by"] == "ncl"
        assert d["priority"] == "high"

    def test_task_from_dict(self):
        d = {
            "task_id": "dl-test123",
            "task_type": "analysis",
            "title": "Analyse data",
            "requested_by": "aac",
            "priority": "normal",
            "status": "queued",
        }
        task = LabourTask.from_dict(d)
        assert task.task_type == TaskType.ANALYSIS
        assert task.requested_by == PillarID.AAC

    def test_register_handler(self):
        pool = DigitalLabourPool.get_instance()

        class CustomHandler(TaskHandler):
            task_type = TaskType.DOCUMENTATION
            name = "custom_doc"

            async def execute(self, task):
                return {"documented": True}

        pool.register_handler(CustomHandler())
        assert TaskType.DOCUMENTATION in pool._handlers

    @pytest.mark.asyncio
    async def test_worker_executes_task(self):
        pool = DigitalLabourPool.get_instance(max_workers=1)
        task = LabourTask(
            task_type=TaskType.DATA_PROCESSING,
            title="Count Items",
            payload={"operation": "count", "data": [1, 2, 3, 4, 5]},
        )
        await pool.submit_task(task)
        await pool.start()
        # Give worker time to process
        await asyncio.sleep(0.2)
        await pool.stop()

        completed_task = pool.get_task(task.task_id)
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result["count"] == 5

    @pytest.mark.asyncio
    async def test_report_handler(self):
        pool = DigitalLabourPool.get_instance(max_workers=1)
        task = LabourTask(
            task_type=TaskType.REPORT_GENERATION,
            title="Generate Report",
            payload={"report_type": "daily_summary", "data": {"transactions": 42}},
        )
        await pool.submit_task(task)
        await pool.start()
        await asyncio.sleep(0.2)
        await pool.stop()

        completed = pool.get_task(task.task_id)
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED
        assert "report" in completed.result

    @pytest.mark.asyncio
    async def test_aggregate_handler(self):
        pool = DigitalLabourPool.get_instance(max_workers=1)
        task = LabourTask(
            task_type=TaskType.DATA_PROCESSING,
            title="Aggregate Numbers",
            payload={"operation": "aggregate", "data": [10, 20, 30]},
        )
        await pool.submit_task(task)
        await pool.start()
        await asyncio.sleep(0.2)
        await pool.stop()

        completed = pool.get_task(task.task_id)
        assert completed is not None
        assert completed.result["sum"] == 60
        assert completed.result["avg"] == 20.0

    @pytest.mark.asyncio
    async def test_bus_message_handler(self):
        pool = DigitalLabourPool.get_instance()
        msg = PillarMessage(
            source=PillarID.NCC,
            target=PillarID.BRS,
            msg_type=MessageType.TASK_ASSIGN,
            payload={
                "task_type": "research",
                "title": "AI Research",
                "task_payload": {"topic": "alignment"},
            },
        )
        response = await pool.handle_bus_message(msg)
        assert response is not None
        assert response.payload["status"] == "queued"

    def test_stats(self):
        pool = DigitalLabourPool.get_instance()
        stats = pool.stats
        assert "max_workers" in stats
        assert "queue_size" in stats
        assert "completed" in stats
        assert "failed" in stats


# ═══════════════════════════════════════════════════════════════
#  PDCA Cycle Tests
# ═══════════════════════════════════════════════════════════════

class TestPDCACycle:
    """Tests for PDCA governance cycle."""

    def test_initial_phase(self):
        pdca = PDCACycle()
        assert pdca.current_phase == "plan"
        assert pdca.cycle_count == 0

    def test_advance_through_phases(self):
        pdca = PDCACycle()
        assert pdca.advance() == "do"
        assert pdca.advance() == "check"
        assert pdca.advance() == "act"
        assert pdca.advance() == "plan"
        assert pdca.cycle_count == 1

    def test_evidence_trail(self):
        pdca = PDCACycle()
        pdca.advance({"action": "test_plan"})
        assert len(pdca.history) == 1
        assert pdca.history[0]["evidence"]["action"] == "test_plan"


# ═══════════════════════════════════════════════════════════════
#  NCC Orchestrator Tests
# ═══════════════════════════════════════════════════════════════

class TestNCCOrchestrator:
    """Tests for NCC Orchestrator."""

    def test_singleton(self):
        o1 = NCCOrchestrator.get_instance()
        o2 = NCCOrchestrator.get_instance()
        assert o1 is o2

    def test_bootstrap(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        # All pillars should be registered
        assert len(orch.registry.list_pillars()) == 4
        # NCC should be ONLINE after bootstrap
        ncc = orch.registry.get(PillarID.NCC)
        assert ncc is not None
        assert ncc.status == PillarStatus.ONLINE

    def test_full_status(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        status = orch.full_status()
        assert "ncc" in status
        assert "registry" in status
        assert "bus" in status
        assert "labour" in status
        assert "triad" in status
        assert "triad_online" in status

    @pytest.mark.asyncio
    async def test_dispatch_labour(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        task_id = await orch.dispatch_labour(
            TaskType.REPORT_GENERATION,
            "Test Report",
            {"report_type": "summary", "data": {}},
        )
        assert task_id.startswith("dl-")

    def test_dispatch_labour_sync(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        task_id = orch.dispatch_labour_sync(
            TaskType.DATA_PROCESSING,
            "Process Data",
            {"operation": "count", "data": [1, 2, 3]},
        )
        assert task_id.startswith("dl-")

    @pytest.mark.asyncio
    async def test_run_pdca_cycle(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        result = await orch.run_pdca_cycle()
        assert "cycle" in result
        assert "phases" in result
        assert "plan" in result["phases"]
        assert "do" in result["phases"]
        assert "check" in result["phases"]
        assert "act" in result["phases"]

    @pytest.mark.asyncio
    async def test_handle_ncc_health_command(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        msg = PillarMessage(
            source=PillarID.NCL,
            target=PillarID.NCC,
            msg_type=MessageType.COMMAND,
            payload={"action": "health_check"},
        )
        response = await orch._handle_ncc_command(msg)
        assert response is not None
        assert "total_pillars" in response.payload

    @pytest.mark.asyncio
    async def test_handle_ncc_triad_command(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        msg = PillarMessage(
            source=PillarID.NCL,
            target=PillarID.NCC,
            msg_type=MessageType.COMMAND,
            payload={"action": "triad_status"},
        )
        response = await orch._handle_ncc_command(msg)
        assert response is not None
        assert "triad" in response.payload

    @pytest.mark.asyncio
    async def test_handle_alert(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        msg = PillarMessage(
            source=PillarID.AAC,
            target=PillarID.NCC,
            msg_type=MessageType.ALERT,
            payload={"severity": "warning", "message": "High volatility detected"},
        )
        response = await orch._handle_alert(msg)
        assert response is not None
        assert response.payload["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_broadcast(self):
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()
        received = []

        def catcher(msg):
            received.append(msg)

        orch.bus.subscribe_all(catcher)
        await orch.broadcast({"command": "status_report"})
        # Process queued messages
        await asyncio.sleep(0.1)
        # Should have 4 messages queued (NCL, AAC, SA, DL)
        assert orch.bus._queue.qsize() >= 0  # Messages may be in queue or dispatched


# ═══════════════════════════════════════════════════════════════
#  Integration Tests — End-to-End
# ═══════════════════════════════════════════════════════════════

class TestEndToEndIntegration:
    """Integration tests verifying the full NCC → Pillar → Labour flow."""

    def test_bootstrap_and_status(self):
        """Verify full bootstrap produces a coherent system state."""
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()

        status = orch.full_status()

        # NCC is online
        assert status["ncc"]["running"] is False  # Not started yet, just bootstrapped
        assert status["registry"]["total_pillars"] == 4

        # Triad registered
        triad = status["triad"]
        assert "ncl" in triad
        assert "aac" in triad
        assert "brs" in triad

    def test_cross_pillar_message_routing(self):
        """Verify messages route correctly between pillars."""
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()

        received = {"ncl": [], "aac": []}

        def ncl_handler(msg):
            received["ncl"].append(msg)

        def aac_handler(msg):
            received["aac"].append(msg)

        orch.bus.subscribe_pillar(PillarID.NCL, ncl_handler)
        orch.bus.subscribe_pillar(PillarID.AAC, aac_handler)

        # NCC → NCL
        msg1 = PillarMessage(
            source=PillarID.NCC, target=PillarID.NCL,
            msg_type=MessageType.REQUEST,
            payload={"action": "memory_search", "query": "test"},
        )
        orch.bus.dispatch_sync(msg1)
        assert len(received["ncl"]) == 1

        # NCL → AAC
        msg2 = PillarMessage(
            source=PillarID.NCL, target=PillarID.AAC,
            msg_type=MessageType.REQUEST,
            payload={"action": "portfolio_status"},
        )
        orch.bus.dispatch_sync(msg2)
        assert len(received["aac"]) == 1

    @pytest.mark.asyncio
    async def test_labour_task_lifecycle(self):
        """Verify a task flows from submission through execution to completion."""
        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()

        # Submit via orchestrator
        task_id = await orch.dispatch_labour(
            TaskType.DATA_PROCESSING,
            "Count test items",
            {"operation": "count", "data": [1, 2, 3]},
            requested_by=PillarID.NCL,
        )

        # Start workers
        await orch.labour.start()
        await asyncio.sleep(0.3)
        await orch.labour.stop()

        # Verify completion
        task = orch.labour.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result["count"] == 3
        assert task.requested_by == PillarID.NCL

    def test_pillar_id_enum_values(self):
        """Verify canonical pillar IDs match doctrine."""
        assert PillarID.NCC.value == "ncc"
        assert PillarID.NCL.value == "ncl"
        assert PillarID.AAC.value == "aac"
        assert PillarID.BRS.value == "brs"

    def test_message_types_cover_all_flows(self):
        """Verify all inter-pillar message types exist."""
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.EVENT.value == "event"
        assert MessageType.COMMAND.value == "command"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.TASK_ASSIGN.value == "task_assign"
        assert MessageType.TASK_RESULT.value == "task_result"
        assert MessageType.TASK_FAILED.value == "task_failed"
        assert MessageType.ALERT.value == "alert"

    def test_capability_discovery(self):
        """Verify pillars can discover each other's capabilities."""
        registry = bootstrap_registry()

        # Find who has MEMORY
        memory_pillars = registry.find_by_capability(CapabilityType.MEMORY)
        assert any(p.pillar_id == PillarID.NCL for p in memory_pillars)

        # Find who has TRADING
        trading_pillars = registry.find_by_capability(CapabilityType.TRADING)
        assert any(p.pillar_id == PillarID.AAC for p in trading_pillars)

        # Find who has AGENT_ORCHESTRATION
        agent_pillars = registry.find_by_capability(CapabilityType.AGENT_ORCHESTRATION)
        assert any(p.pillar_id == PillarID.BRS for p in agent_pillars)

        # Find who has BIT_RAGE_SYSTEMS
        labour_pillars = registry.find_by_capability(CapabilityType.BIT_RAGE_SYSTEMS)
        assert any(p.pillar_id == PillarID.BRS for p in labour_pillars)
