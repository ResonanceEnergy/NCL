#!/usr/bin/env python3
"""
NCC Governance Orchestrator — Supreme command layer for Resonance Energy.
═════════════════════════════════════════════════════════════════════════
NCC (Natrix Command & Control) is the governance root that orchestrates
the triad: NCL (Brain), AAC (Bank), BRS (Bit Rage Systems).

Responsibilities:
    1. Bootstrap all pillars and the inter-pillar bus
    2. Enforce PDCA governance loop (Plan-Do-Check-Act)
    3. Route cross-pillar requests
    4. Dispatch tasks to Bit Rage Systems
    5. Generate triad health reports
    6. Enforce doctrine compliance

Design Principles:
    - NCC Master Doctrine v3.0: "If it isn't governed, it isn't real."
    - Art of War: "Supreme excellence — win without fighting" → proactive governance
    - Law 29: "Plan all the way to the end" → full lifecycle orchestration
    - Habit 7: "Sharpen the Saw" → continuous audit and improvement
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from ncl_agency_runtime.runtime.digital_labour import (
    DigitalLabourPool,
    LabourTask,
    TaskType,
)
from ncl_agency_runtime.runtime.inter_pillar_bus import (
    InterPillarBus,
    MessageType,
    PillarMessage,
    Priority,
)
from ncl_agency_runtime.runtime.pillar_registry import (
    PillarID,
    PillarRegistry,
    PillarStatus,
    bootstrap_registry,
)

LOG = logging.getLogger("ncc.orchestrator")


# ═══════════════════════════════════════════════════════════════
#  PDCA Governance Cycle
# ═══════════════════════════════════════════════════════════════

class PDCACycle:
    """Plan-Do-Check-Act governance loop.

    Tracks the current phase, actions taken, and evidence trail.
    NCC Master Doctrine: "If it isn't captured, it isn't trusted."
    """

    PHASES = ("plan", "do", "check", "act")

    def __init__(self) -> None:
        self._current_phase = 0
        self._cycle_count = 0
        self._log: list[dict[str, Any]] = []

    @property
    def current_phase(self) -> str:
        return self.PHASES[self._current_phase]

    def advance(self, evidence: dict[str, Any] | None = None) -> str:
        """Advance to the next PDCA phase."""
        entry = {
            "cycle": self._cycle_count,
            "from_phase": self.current_phase,
            "evidence": evidence or {},
            "ts": datetime.now(UTC).isoformat(),
        }
        self._current_phase = (self._current_phase + 1) % 4
        if self._current_phase == 0:
            self._cycle_count += 1
        entry["to_phase"] = self.current_phase
        self._log.append(entry)
        return self.current_phase

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._log)


# ═══════════════════════════════════════════════════════════════
#  NCC Orchestrator
# ═══════════════════════════════════════════════════════════════

class NCCOrchestrator:
    """Supreme governance orchestrator for the Resonance Energy ecosystem.

    Wires together:
        PillarRegistry  → knows who's alive
        InterPillarBus  → delivers messages between pillars
        DigitalLabourPool → executes autonomous work
        PDCACycle       → enforces governance rhythm

    Usage::

        orch = NCCOrchestrator()
        orch.bootstrap()
        await orch.start()          # starts bus + labour pool
        # ... system runs ...
        await orch.stop()
    """

    _instance: ClassVar[NCCOrchestrator | None] = None

    def __init__(self) -> None:
        self.registry: PillarRegistry = PillarRegistry.get_instance()
        self.bus: InterPillarBus = InterPillarBus.get_instance()
        self.labour: DigitalLabourPool = DigitalLabourPool.get_instance()
        self.pdca = PDCACycle()
        self._boot_time = time.time()
        self._running = False

    @classmethod
    def get_instance(cls) -> NCCOrchestrator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        PillarRegistry.reset()
        InterPillarBus.reset()
        DigitalLabourPool.reset()

    # ── Bootstrap ─────────────────────────────────────────────

    def bootstrap(self) -> dict[str, Any]:
        """Bootstrap the entire NCC ecosystem.

        1. Populate pillar registry with all default pillars
        2. Wire Digital Labour to the bus
        3. Subscribe NCC governance handler
        4. Set NCC pillar to ONLINE
        """
        # 1. Registry
        bootstrap_registry()

        # 2. Wire DL to bus
        self.labour.connect_to_bus(self.bus)

        # 3. NCC governance subscription — handles commands and alerts
        self.bus.subscribe(PillarID.NCC, MessageType.COMMAND, self._handle_ncc_command)
        self.bus.subscribe(PillarID.NCC, MessageType.ALERT, self._handle_alert)
        self.bus.subscribe("*", MessageType.HEARTBEAT, self._handle_heartbeat)
        self.bus.subscribe("*", MessageType.STATUS_REPORT, self._handle_status_report)

        # 4. NCC online
        self.registry.set_status(PillarID.NCC, PillarStatus.ONLINE)

        status = self.registry.triad_status()
        LOG.info("NCC Bootstrap complete — Triad: %s", status)
        return status

    # ── Start / Stop ──────────────────────────────────────────

    async def start(self) -> None:
        """Start the bus dispatch loop and labour pool."""
        self._running = True
        asyncio.create_task(self.bus.start())
        await self.labour.start()
        LOG.info("NCC Orchestrator ONLINE")

    async def stop(self) -> None:
        """Gracefully stop all components."""
        self._running = False
        await self.labour.stop()
        await self.bus.stop()
        LOG.info("NCC Orchestrator stopped")

    # ── Cross-Pillar Routing ──────────────────────────────────

    async def route_to_pillar(self, target: PillarID, payload: dict[str, Any],
                              msg_type: MessageType = MessageType.REQUEST,
                              priority: Priority = Priority.NORMAL) -> PillarMessage | None:
        """Route a message from NCC to any pillar.

        Returns the response if msg_type is REQUEST, else None.
        """
        msg = PillarMessage(
            source=PillarID.NCC,
            target=target,
            msg_type=msg_type,
            payload=payload,
            priority=priority,
        )

        if msg_type == MessageType.REQUEST:
            return await self.bus.request(msg, timeout=30.0)
        await self.bus.publish(msg)
        return None

    async def broadcast(self, payload: dict[str, Any],
                        msg_type: MessageType = MessageType.COMMAND,
                        priority: Priority = Priority.NORMAL) -> None:
        """Broadcast a message to ALL pillars (except NCC itself)."""
        for pid in (PillarID.NCL, PillarID.AAC, PillarID.BRS):
            msg = PillarMessage(
                source=PillarID.NCC,
                target=pid,
                msg_type=msg_type,
                payload=payload,
                priority=priority,
            )
            await self.bus.publish(msg)

    # ── Digital Labour dispatch ───────────────────────────────

    async def dispatch_labour(self, task_type: TaskType, title: str,
                              payload: dict[str, Any],
                              priority: Priority = Priority.NORMAL,
                              requested_by: PillarID = PillarID.NCC) -> str:
        """Submit a task directly to the Digital Labour pool."""
        task = LabourTask(
            task_type=task_type,
            title=title,
            payload=payload,
            priority=priority,
            requested_by=requested_by,
        )
        return await self.labour.submit_task(task)

    def dispatch_labour_sync(self, task_type: TaskType, title: str,
                             payload: dict[str, Any],
                             priority: Priority = Priority.NORMAL,
                             requested_by: PillarID = PillarID.NCC) -> str:
        """Submit a task synchronously (non-async context)."""
        task = LabourTask(
            task_type=task_type,
            title=title,
            payload=payload,
            priority=priority,
            requested_by=requested_by,
        )
        return self.labour.submit_task_sync(task)

    # ── NCL Integration Helpers ───────────────────────────────

    async def ncl_memory_search(self, query: str) -> PillarMessage | None:
        """Ask NCL (Brain) to search its memory."""
        return await self.route_to_pillar(
            PillarID.NCL,
            {"action": "memory_search", "query": query},
        )

    async def ncl_generate_brief(self, brief_type: str = "daily") -> PillarMessage | None:
        """Ask NCL to generate a cognitive brief."""
        return await self.route_to_pillar(
            PillarID.NCL,
            {"action": "generate_brief", "brief_type": brief_type},
        )

    # ── AAC Integration Helpers ───────────────────────────────

    async def aac_portfolio_status(self) -> PillarMessage | None:
        """Ask AAC (Bank) for current portfolio status."""
        return await self.route_to_pillar(
            PillarID.AAC,
            {"action": "portfolio_status"},
        )

    async def aac_risk_check(self) -> PillarMessage | None:
        """Ask AAC for current risk assessment."""
        return await self.route_to_pillar(
            PillarID.AAC,
            {"action": "risk_check"},
        )

    # ── Bit Rage Systems Integration Helpers ──────────────────

    async def agency_dispatch_agents(self, mission: str, agents: list[str] | None = None) -> PillarMessage | None:
        """Ask Bit Rage Systems to dispatch agents for a mission."""
        return await self.route_to_pillar(
            PillarID.BRS,
            {"action": "dispatch_agents", "mission": mission, "agents": agents or []},
        )

    async def agency_entropy_check(self) -> PillarMessage | None:
        """Ask the Entropy Sentinel for current drift/coupling metrics."""
        return await self.route_to_pillar(
            PillarID.BRS,
            {"action": "entropy_check"},
        )

    # ── Governance ────────────────────────────────────────────

    async def run_pdca_cycle(self) -> dict[str, Any]:
        """Execute one full PDCA governance cycle.

        PLAN  → gather health via Matrix Monitor, identify issues
        DO    → dispatch corrective tasks for offline pillars and SLO violations
        CHECK → verify task results, bus stats
        ACT   → update doctrine, publish report to bus
        """
        results: dict[str, Any] = {"cycle": self.pdca.cycle_count, "phases": {}}

        # PLAN — use Matrix Monitor for comprehensive health intelligence
        self.pdca.advance({"action": "gather_health"})
        health = self.registry.health_summary()
        triad = self.registry.triad_status()

        matrix_report = None
        try:
            from ncl_agency_runtime.runtime.matrix_monitor import (
                MatrixMonitorOrchestrator,
            )
            monitor = MatrixMonitorOrchestrator.get_instance()
            matrix_report = monitor.collect_all()
            results["phases"]["plan"] = {
                "health": health,
                "triad": triad,
                "matrix_score": matrix_report.overall_score,
                "matrix_status": matrix_report.health_status,
                "checks_passed": matrix_report.checks_passed,
                "checks_total": matrix_report.checks_total,
                "slo_violations": matrix_report.slos_in_violation,
                "alerts": len(matrix_report.alerts),
            }
        except Exception as exc:
            LOG.warning("Matrix Monitor unavailable in PDCA: %s", exc)
            results["phases"]["plan"] = {"health": health, "triad": triad}

        # DO
        self.pdca.advance({"action": "dispatch_corrective_tasks"})
        offline = [pid for pid, status in triad.items() if status != "online"]
        if offline:
            task_id = await self.dispatch_labour(
                TaskType.MONITORING,
                f"Investigate offline pillars: {', '.join(offline)}",
                {"target_pillars": offline},
                priority=Priority.HIGH,
            )
            results["phases"]["do"] = {"monitoring_task": task_id, "offline": offline}
        else:
            results["phases"]["do"] = {"status": "all_online", "offline": []}

        # CHECK
        self.pdca.advance({"action": "verify_results"})
        bus_stats = self.bus.stats
        labour_stats = self.labour.stats
        results["phases"]["check"] = {"bus": bus_stats, "labour": labour_stats}

        # ACT — publish Matrix Report to bus for cross-pillar visibility
        self.pdca.advance({"action": "update_doctrine"})
        if matrix_report is not None:
            try:
                from ncl_agency_runtime.runtime.matrix_monitor import (
                    MatrixMonitorOrchestrator,
                )
                monitor = MatrixMonitorOrchestrator.get_instance()
                monitor.publish_to_bus(matrix_report)
            except Exception as exc:
                LOG.warning("Failed to publish matrix report to bus: %s", exc)
        results["phases"]["act"] = {"cycle_completed": self.pdca.cycle_count}

        LOG.info("PDCA cycle %d complete", self.pdca.cycle_count)
        return results

    # ── NCC Command handlers ──────────────────────────────────

    async def _handle_ncc_command(self, msg: PillarMessage) -> PillarMessage | None:
        """Process commands directed at NCC."""
        action = msg.payload.get("action", "")
        LOG.info("NCC command from %s: %s", msg.source.value, action)

        if action == "health_check":
            return msg.make_response(self.registry.health_summary())
        if action == "triad_status":
            return msg.make_response({"triad": self.registry.triad_status()})
        if action == "matrix_status":
            try:
                from ncl_agency_runtime.runtime.matrix_monitor import (
                    MatrixMonitorOrchestrator,
                )
                monitor = MatrixMonitorOrchestrator.get_instance()
                report = monitor.collect_all()
                return msg.make_response(report.to_dict())
            except Exception as exc:
                return msg.make_response({"error": f"Matrix Monitor unavailable: {exc}"})
        if action == "run_pdca":
            result = await self.run_pdca_cycle()
            return msg.make_response(result)
        if action == "dispatch_labour":
            task_id = await self.dispatch_labour(
                TaskType(msg.payload.get("task_type", "data_processing")),
                msg.payload.get("title", "NCC-dispatched task"),
                msg.payload.get("task_payload", {}),
                requested_by=msg.source,
            )
            return msg.make_response({"task_id": task_id, "status": "queued"})

        return msg.make_response({"error": f"Unknown NCC command: {action}"})

    async def _handle_alert(self, msg: PillarMessage) -> PillarMessage | None:
        """Process alerts escalated to NCC.

        Law 17: "Keep others in suspended terror" — alerts trigger immediate response.
        """
        severity = msg.payload.get("severity", "warning")
        LOG.warning("ALERT from %s [%s]: %s", msg.source.value, severity, msg.payload.get("message", ""))

        if severity == "critical":
            # Dispatch monitoring task for critical alerts
            await self.dispatch_labour(
                TaskType.MONITORING,
                f"Critical alert from {msg.source.value}",
                {"alert": msg.payload},
                priority=Priority.CRITICAL,
            )

        return msg.make_response({"acknowledged": True, "severity": severity})

    async def _handle_heartbeat(self, msg: PillarMessage) -> None:
        """Process heartbeats from any pillar."""
        self.registry.heartbeat(msg.source)

    async def _handle_status_report(self, msg: PillarMessage) -> None:
        """Process status reports from any pillar."""
        LOG.info("Status report from %s: %s", msg.source.value, msg.payload.get("status", "unknown"))

    # ── Diagnostics ───────────────────────────────────────────

    def full_status(self) -> dict[str, Any]:
        """Complete NCC ecosystem status."""
        return {
            "ncc": {
                "uptime_s": round(time.time() - self._boot_time, 1),
                "running": self._running,
                "pdca_cycle": self.pdca.cycle_count,
                "pdca_phase": self.pdca.current_phase,
            },
            "registry": self.registry.health_summary(),
            "bus": self.bus.stats,
            "labour": self.labour.stats,
            "triad": self.registry.triad_status(),
            "triad_online": self.registry.triad_online(),
        }
