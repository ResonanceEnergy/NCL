#!/usr/bin/env python3
"""
Digital Labour — Autonomous worker pool for the NCC triad.
═══════════════════════════════════════════════════════════
Digital Labour is the WORKFORCE that executes tasks dispatched by NCC,
NCL (Brain), AAC (Bank), and Super Agency (Agency).

Workers are stateless, queue-driven units that:
    1. Pull tasks from the labour queue
    2. Execute via registered task handlers
    3. Report results back through the inter-pillar bus
    4. Maintain audit trails for every unit of work

Design Principles:
    - Nate B Jones: "AI-First Thinking" — automate before you hire
    - Agentic Lab: "Agent-First Design" — autonomous, human-in-the-loop optional
    - Art of War: "Five Factors" — discipline in execution
    - Tom Bilyeu: "Radical Accountability" — every task has an owner and outcome
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

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
)

LOG = logging.getLogger("ncc.digital_labour")


# ═══════════════════════════════════════════════════════════════
#  Task Types
# ═══════════════════════════════════════════════════════════════

class TaskType(StrEnum):
    """Categories of Digital Labour tasks."""
    CONTENT_CREATION = "content_creation"
    DATA_PROCESSING = "data_processing"
    RESEARCH = "research"
    REPORT_GENERATION = "report_generation"
    CODE_REVIEW = "code_review"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    MONITORING = "monitoring"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"


class TaskStatus(StrEnum):
    """Lifecycle of a labour task."""
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


# ═══════════════════════════════════════════════════════════════
#  Labour Task
# ═══════════════════════════════════════════════════════════════

@dataclass
class LabourTask:
    """A unit of work to be executed by a Digital Labour worker."""
    task_id: str = field(default_factory=lambda: f"dl-{uuid.uuid4().hex[:10]}")
    task_type: TaskType = TaskType.DATA_PROCESSING
    title: str = ""
    description: str = ""
    requested_by: PillarID = PillarID.NCC
    payload: dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    status: TaskStatus = TaskStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str = ""
    completed_at: str = ""
    assigned_worker: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempt: int = 0
    max_attempts: int = 3
    timeout_seconds: int = 300

    def to_dict(self) -> dict:
        d = asdict(self)
        d["task_type"] = self.task_type.value
        d["requested_by"] = self.requested_by.value
        d["priority"] = self.priority.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> LabourTask:
        d = dict(d)
        d["task_type"] = TaskType(d.get("task_type", "data_processing"))
        d["requested_by"] = PillarID(d.get("requested_by", "ncc"))
        d["priority"] = Priority(d.get("priority", "normal"))
        d["status"] = TaskStatus(d.get("status", "queued"))
        return cls(**d)


# ═══════════════════════════════════════════════════════════════
#  Task Handler Interface
# ═══════════════════════════════════════════════════════════════

class TaskHandler:
    """Base class for Digital Labour task handlers.

    Subclass and implement `execute()` to create a new worker type.
    """
    task_type: TaskType = TaskType.DATA_PROCESSING
    name: str = "base_handler"

    async def execute(self, task: LabourTask) -> dict[str, Any]:
        """Execute the task and return a result dict."""
        raise NotImplementedError

    async def validate(self, task: LabourTask) -> tuple[bool, str]:
        """Validate task payload before execution. Override for custom validation."""
        return True, "OK"


# ═══════════════════════════════════════════════════════════════
#  Built-in Handlers
# ═══════════════════════════════════════════════════════════════

class ReportHandler(TaskHandler):
    """Generate cross-pillar reports."""
    task_type = TaskType.REPORT_GENERATION
    name = "report_generator"

    async def execute(self, task: LabourTask) -> dict[str, Any]:
        report_type = task.payload.get("report_type", "summary")
        data = task.payload.get("data", {})

        sections = []
        sections.append(f"# {report_type.replace('_', ' ').title()} Report")
        sections.append(f"Generated: {datetime.now(UTC).isoformat()}")
        sections.append(f"Requested by: {task.requested_by.value}")
        sections.append("")

        if isinstance(data, dict):
            for key, value in data.items():
                sections.append(f"## {key.replace('_', ' ').title()}")
                sections.append(str(value))
                sections.append("")

        return {
            "report": "\n".join(sections),
            "report_type": report_type,
            "word_count": sum(len(s.split()) for s in sections),
        }


class DataProcessingHandler(TaskHandler):
    """Process and transform data."""
    task_type = TaskType.DATA_PROCESSING
    name = "data_processor"

    async def execute(self, task: LabourTask) -> dict[str, Any]:
        operation = task.payload.get("operation", "passthrough")
        data = task.payload.get("data", [])

        if operation == "count":
            return {"count": len(data), "operation": operation}
        if operation == "aggregate":
            if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
                return {"sum": sum(data), "avg": sum(data) / len(data) if data else 0,
                        "min": min(data) if data else 0, "max": max(data) if data else 0}
            return {"error": "Cannot aggregate non-numeric data"}
        # passthrough
        return {"data": data, "operation": operation}


class ResearchHandler(TaskHandler):
    """Execute research tasks."""
    task_type = TaskType.RESEARCH
    name = "researcher"

    async def execute(self, task: LabourTask) -> dict[str, Any]:
        topic = task.payload.get("topic", "unspecified")
        sources = task.payload.get("sources", [])
        return {
            "topic": topic,
            "sources_checked": len(sources),
            "findings": f"Research on '{topic}' queued for manual review",
            "status": "pending_review",
        }


class AnalysisHandler(TaskHandler):
    """Analyse data and produce insights."""
    task_type = TaskType.ANALYSIS
    name = "analyst"

    async def execute(self, task: LabourTask) -> dict[str, Any]:
        data = task.payload.get("data", {})
        analysis_type = task.payload.get("analysis_type", "general")
        return {
            "analysis_type": analysis_type,
            "data_points": len(data) if isinstance(data, (list, dict)) else 1,
            "insights": [],
            "status": "complete",
        }


class MonitoringHandler(TaskHandler):
    """Monitor pillar health and metrics."""
    task_type = TaskType.MONITORING
    name = "monitor"

    async def execute(self, task: LabourTask) -> dict[str, Any]:
        target = task.payload.get("target_pillar", "all")
        registry = PillarRegistry.get_instance()
        health = registry.health_summary()
        return {
            "target": target,
            "health": health,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# ═══════════════════════════════════════════════════════════════
#  Digital Labour Pool
# ═══════════════════════════════════════════════════════════════

class DigitalLabourPool:
    """Manages a pool of workers that execute tasks from the labour queue.

    Integrates with:
        - InterPillarBus: receives TASK_ASSIGN, sends TASK_RESULT/TASK_FAILED
        - PillarRegistry: registers DL pillar, reports health

    Nate B Jones: "Systems Over Tactics" — the pool IS the system.
    Agentic Lab: "Composable Agents" — handlers are pluggable components.
    """

    _instance: ClassVar[DigitalLabourPool | None] = None

    def __init__(self, max_workers: int = 4) -> None:
        self.max_workers = max_workers
        self._handlers: dict[TaskType, TaskHandler] = {}
        self._task_queue: asyncio.Queue[LabourTask] = asyncio.Queue()
        self._active_tasks: dict[str, LabourTask] = {}
        self._completed: list[LabourTask] = []
        self._failed: list[LabourTask] = []
        self._running = False
        self._workers: list[asyncio.Task[None]] = []

        # Register built-in handlers
        for handler_cls in (ReportHandler, DataProcessingHandler, ResearchHandler,
                            AnalysisHandler, MonitoringHandler):
            h = handler_cls()
            self._handlers[h.task_type] = h

    @classmethod
    def get_instance(cls, max_workers: int = 4) -> DigitalLabourPool:
        if cls._instance is None:
            cls._instance = cls(max_workers=max_workers)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ── Handler registration ──────────────────────────────────

    def register_handler(self, handler: TaskHandler) -> None:
        """Register a custom task handler."""
        self._handlers[handler.task_type] = handler
        LOG.info("Handler registered: %s → %s", handler.task_type.value, handler.name)

    # ── Task submission ───────────────────────────────────────

    async def submit_task(self, task: LabourTask) -> str:
        """Submit a task to the labour queue. Returns task_id."""
        task.status = TaskStatus.QUEUED
        await self._task_queue.put(task)
        LOG.info("Task submitted: %s [%s] from %s", task.task_id, task.task_type.value, task.requested_by.value)
        return task.task_id

    def submit_task_sync(self, task: LabourTask) -> str:
        """Submit a task synchronously (for non-async callers)."""
        task.status = TaskStatus.QUEUED
        # Use thread-safe put_nowait
        self._task_queue.put_nowait(task)
        LOG.info("Task submitted (sync): %s [%s]", task.task_id, task.task_type.value)
        return task.task_id

    # ── Worker loop ───────────────────────────────────────────

    async def start(self) -> None:
        """Start worker coroutines."""
        self._running = True
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker_loop(f"worker-{i}"))
            self._workers.append(worker)
        LOG.info("DigitalLabourPool started with %d workers", self.max_workers)

        # Register as ONLINE
        registry = PillarRegistry.get_instance()
        registry.set_status(PillarID.BRS, PillarStatus.ONLINE)

    async def stop(self) -> None:
        """Stop all workers."""
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        LOG.info("DigitalLabourPool stopped (completed=%d, failed=%d)", len(self._completed), len(self._failed))

    async def _worker_loop(self, worker_id: str) -> None:
        """Individual worker loop — pulls and executes tasks."""
        LOG.debug("Worker %s started", worker_id)
        while self._running:
            try:
                task = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            task.status = TaskStatus.IN_PROGRESS
            task.assigned_worker = worker_id
            task.started_at = datetime.now(UTC).isoformat()
            task.attempt += 1
            self._active_tasks[task.task_id] = task

            handler = self._handlers.get(task.task_type)
            if not handler:
                task.status = TaskStatus.FAILED
                task.error = f"No handler for task type: {task.task_type.value}"
                self._failed.append(task)
                self._active_tasks.pop(task.task_id, None)
                LOG.warning("No handler for %s", task.task_type.value)
                continue

            try:
                valid, reason = await handler.validate(task)
                if not valid:
                    task.status = TaskStatus.FAILED
                    task.error = f"Validation failed: {reason}"
                    self._failed.append(task)
                    self._active_tasks.pop(task.task_id, None)
                    continue

                result = await asyncio.wait_for(
                    handler.execute(task),
                    timeout=task.timeout_seconds,
                )
                task.result = result
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(UTC).isoformat()
                self._completed.append(task)
                LOG.info("Task %s completed by %s", task.task_id, worker_id)

            except TimeoutError:
                task.error = f"Timeout after {task.timeout_seconds}s"
                if task.attempt < task.max_attempts:
                    task.status = TaskStatus.QUEUED
                    await self._task_queue.put(task)
                    LOG.warning("Task %s timed out — retry %d/%d", task.task_id, task.attempt, task.max_attempts)
                else:
                    task.status = TaskStatus.DEAD_LETTER
                    self._failed.append(task)
                    LOG.error("Task %s exhausted retries", task.task_id)

            except Exception as exc:
                task.error = str(exc)
                if task.attempt < task.max_attempts:
                    task.status = TaskStatus.QUEUED
                    await self._task_queue.put(task)
                else:
                    task.status = TaskStatus.FAILED
                    self._failed.append(task)
                    LOG.error("Task %s failed: %s", task.task_id, exc)

            finally:
                self._active_tasks.pop(task.task_id, None)

    # ── Bus integration ───────────────────────────────────────

    async def handle_bus_message(self, msg: PillarMessage) -> PillarMessage | None:
        """Handle TASK_ASSIGN messages from the InterPillarBus."""
        if msg.msg_type != MessageType.TASK_ASSIGN:
            return None

        task = LabourTask(
            task_type=TaskType(msg.payload.get("task_type", "data_processing")),
            title=msg.payload.get("title", ""),
            description=msg.payload.get("description", ""),
            requested_by=msg.source,
            payload=msg.payload.get("task_payload", {}),
            priority=msg.priority,
        )
        await self.submit_task(task)

        return msg.make_response({
            "task_id": task.task_id,
            "status": "queued",
            "message": f"Task queued: {task.title}",
        })

    def connect_to_bus(self, bus: InterPillarBus) -> None:
        """Subscribe to TASK_ASSIGN messages on the bus."""
        bus.subscribe(PillarID.BRS, MessageType.TASK_ASSIGN, self.handle_bus_message)
        LOG.info("DigitalLabourPool connected to InterPillarBus")

    # ── Diagnostics ───────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "max_workers": self.max_workers,
            "queue_size": self._task_queue.qsize(),
            "active_tasks": len(self._active_tasks),
            "completed": len(self._completed),
            "failed": len(self._failed),
            "running": self._running,
        }

    def get_task(self, task_id: str) -> LabourTask | None:
        """Look up a task by ID across all states."""
        if task_id in self._active_tasks:
            return self._active_tasks[task_id]
        for t in self._completed:
            if t.task_id == task_id:
                return t
        for t in self._failed:
            if t.task_id == task_id:
                return t
        return None
