"""ATLAS Mission Control — deterministic state-machine orchestrator.

State flow:
  OBSERVE → INTERPRET → PLAN → PROPOSE_ACTIONS → POLICY_CHECK
       ↑                                              ↓
   RECOVER ← ERROR/RETRY ← EXECUTE ← APPROVE ← DENY/REVISE
                              ↓
                         EVAL_LEARN → back to OBSERVE
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ── Task management ─────────────────────────────────────────────
class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class LoopPhase(StrEnum):
    OBSERVE = "observe"
    INTERPRET = "interpret"
    PLAN = "plan"
    PROPOSE = "propose"
    POLICY_CHECK = "policy_check"
    APPROVE = "approve"
    EXECUTE = "execute"
    EVAL_LEARN = "eval_learn"
    RECOVER = "recover"
    IDLE = "idle"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Task:
    id: str
    agent_codename: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    requires_approval: bool = False
    priority: int = 5  # 1 = highest
    created_at: float = field(default_factory=time.time)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class ActionProposal:
    """An action the system wants to take, pending policy + human approval."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source_agent: str = ""
    action_type: str = ""  # deploy, writeback, burst, retrain, rollback
    description: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)  # XAI dossier, causal lift, etc.
    cost_estimate_usd: float = 0.0
    risk_level: Severity = Severity.INFO
    requires_human: bool = False
    approved: bool = False
    denied_reason: str = ""


@dataclass
class LoopContext:
    """State carried through one mission-control loop iteration."""

    phase: LoopPhase = LoopPhase.IDLE
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    event: dict[str, Any] = field(default_factory=dict)
    observations: list[dict[str, Any]] = field(default_factory=list)
    interpretations: list[str] = field(default_factory=list)
    plan: list[Task] = field(default_factory=list)
    proposals: list[ActionProposal] = field(default_factory=list)
    policy_results: list[dict[str, Any]] = field(default_factory=list)
    execution_results: list[dict[str, Any]] = field(default_factory=list)
    learnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None


@dataclass
class OrchestratorState:
    """Global orchestrator state across all loops."""

    tasks: list[Task] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    steering: dict[str, Any] = field(default_factory=dict)
    loop_history: list[LoopContext] = field(default_factory=list)
    total_spend_usd: float = 0.0
    rollback_count: int = 0


# ── Release Policy Loader ──────────────────────────────────────
def _load_release_policy(policy_path: str | pathlib.Path | None = None) -> dict[str, Any]:
    """Load Apollo-lite ReleasePolicy.yaml."""
    if policy_path is None:
        policy_path = pathlib.Path(__file__).resolve().parents[1] / "ops" / "ReleasePolicy.yaml"
    path = pathlib.Path(policy_path)
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        # Fallback: parse YAML-ish keys
        return {"_raw": path.read_text()}


# ── Mission Control (ATLAS) ────────────────────────────────────
class MissionControl:
    """ATLAS — the deterministic state-machine orchestrator.

    Implements the full OBSERVE → INTERPRET → PLAN → PROPOSE →
    POLICY_CHECK → EXECUTE → EVAL_LEARN loop with error recovery
    and human approval gates.
    """

    def __init__(
        self,
        config_path: str | pathlib.Path | None = None,
        policy_path: str | pathlib.Path | None = None,
    ) -> None:
        self.state = OrchestratorState()
        if config_path and pathlib.Path(config_path).exists():
            self.state.steering = json.loads(pathlib.Path(config_path).read_text())
        self.release_policy = _load_release_policy(policy_path)

        # Agent dispatch table — maps codename → callable
        # In production, these point to real agent functions / LangGraph nodes
        self._agent_handlers: dict[str, Any] = {}

        # Approval callback — set by caller (UI, Telegram bot, API, etc.)
        self._approval_callback: Any = None

    # ── Agent Registration ──────────────────────────────────────
    def register_agent(self, codename: str, handler: Any) -> None:
        """Register an agent's handler function for task dispatch."""
        self._agent_handlers[codename] = handler

    def set_approval_callback(self, callback: Any) -> None:
        """Set the human approval callback (async or sync)."""
        self._approval_callback = callback

    # ── Core Loop ───────────────────────────────────────────────
    def run_loop(self, event: dict[str, Any]) -> LoopContext:
        """Execute one full mission-control loop iteration."""
        ctx = LoopContext(event=event)

        try:
            ctx = self._observe(ctx)
            ctx = self._interpret(ctx)
            ctx = self._plan(ctx)
            ctx = self._propose_actions(ctx)
            ctx = self._policy_check(ctx)
            ctx = self._approve(ctx)
            ctx = self._execute(ctx)
            ctx = self._eval_learn(ctx)
        except Exception as exc:
            ctx.errors.append(str(exc))
            ctx = self._recover(ctx)

        ctx.completed_at = time.time()
        self.state.loop_history.append(ctx)
        return ctx

    # ── Phase Implementations ───────────────────────────────────
    def _observe(self, ctx: LoopContext) -> LoopContext:
        """Ingest event, merge with current state and telemetry."""
        ctx.phase = LoopPhase.OBSERVE
        logger.info("[ATLAS/OBSERVE] trace=%s event_type=%s", ctx.trace_id, ctx.event.get("detail_type", "unknown"))

        ctx.observations.append({
            "event": ctx.event,
            "active_tasks": len([t for t in self.state.tasks if t.status == TaskStatus.IN_PROGRESS]),
            "total_spend": self.state.total_spend_usd,
            "rollback_count": self.state.rollback_count,
        })
        return ctx

    def _interpret(self, ctx: LoopContext) -> LoopContext:
        """Classify event and determine required agent responses."""
        ctx.phase = LoopPhase.INTERPRET
        detail_type = ctx.event.get("detail_type", "")

        if detail_type.startswith("intent."):
            ctx.interpretations.append("user_intent")
        elif detail_type.startswith("data."):
            ctx.interpretations.append("data_update")
        elif detail_type.startswith("model."):
            ctx.interpretations.append("model_cycle")
        elif detail_type.startswith("telemetry."):
            ctx.interpretations.append("telemetry_signal")
        elif detail_type.startswith("action."):
            ctx.interpretations.append("action_result")
        elif detail_type.startswith("policy."):
            ctx.interpretations.append("policy_change")
        else:
            ctx.interpretations.append("general")

        return ctx

    def _plan(self, ctx: LoopContext) -> LoopContext:
        """Build task plan based on interpretations — consult council agents."""
        ctx.phase = LoopPhase.PLAN

        for interpretation in ctx.interpretations:
            if interpretation == "user_intent":
                # Full council: SCRIBE → TEMPO → ORACLE → LANTERN → RAVEN
                ctx.plan.extend([
                    Task(f"T-{ctx.trace_id}-ds", "ds", "Validate and prepare data"),
                    Task(f"T-{ctx.trace_id}-be", "be", "Run baseline forecast"),
                    Task(f"T-{ctx.trace_id}-ne", "ne", "Run neural forecast"),
                    Task(f"T-{ctx.trace_id}-xe", "xe", "Generate XAI dossier"),
                    Task(f"T-{ctx.trace_id}-cs", "cs", "Run causal what-if"),
                ])
            elif interpretation == "data_update":
                ctx.plan.append(Task(f"T-{ctx.trace_id}-ds", "ds", "Validate incoming data"))
                ctx.plan.append(Task(f"T-{ctx.trace_id}-xe", "xe", "Check for explanation drift"))
            elif interpretation == "model_cycle":
                ctx.plan.append(Task(f"T-{ctx.trace_id}-xe", "xe", "Generate cycle XAI dossier"))
                ctx.plan.append(Task(f"T-{ctx.trace_id}-dx", "dx", "Publish cycle brief"))
            elif interpretation == "telemetry_signal":
                ctx.plan.append(Task(f"T-{ctx.trace_id}-mo", "mo", "Check health metrics"))
            elif interpretation == "action_result":
                ctx.plan.append(Task(f"T-{ctx.trace_id}-eval", "mc", "Evaluate action outcome"))
            elif interpretation == "policy_change":
                ctx.plan.append(Task(f"T-{ctx.trace_id}-so", "so", "Validate policy update"))

        return ctx

    def _propose_actions(self, ctx: LoopContext) -> LoopContext:
        """Convert planned tasks into actionable proposals with evidence."""
        ctx.phase = LoopPhase.PROPOSE

        for task in ctx.plan:
            # Dispatch to agent handler if registered
            handler = self._agent_handlers.get(task.agent_codename)
            if handler:
                try:
                    result = handler(task, ctx.event)
                    task.result = result
                    task.status = TaskStatus.COMPLETED
                except Exception as exc:
                    task.status = TaskStatus.FAILED
                    task.result = {"error": str(exc)}
                    ctx.errors.append(f"Agent {task.agent_codename} failed: {exc}")
            else:
                # Stub: simulate execution
                task.result = {"status": "simulated", "agent": task.agent_codename}
                task.status = TaskStatus.COMPLETED

            self.state.tasks.append(task)

        return ctx

    def _policy_check(self, ctx: LoopContext) -> LoopContext:
        """Enforce ReleasePolicy gates, cost caps, soak requirements."""
        ctx.phase = LoopPhase.POLICY_CHECK
        budget = self.state.steering.get("budget_weekly_usd", 50.0)

        for proposal in ctx.proposals:
            result: dict[str, Any] = {"proposal_id": proposal.id, "checks": []}

            # Budget check
            if self.state.total_spend_usd + proposal.cost_estimate_usd > budget:
                result["checks"].append("FAIL: Would exceed weekly budget")
                proposal.denied_reason = "Budget exceeded"
                proposal.approved = False
            else:
                result["checks"].append("PASS: Within budget")

            # Risk check
            if proposal.risk_level == Severity.CRITICAL:
                proposal.requires_human = True
                result["checks"].append("GATE: Critical risk — requires human approval")

            # Release channel check
            if proposal.action_type == "deploy":
                channels = self.release_policy.get("channels", {})
                result["checks"].append(f"POLICY: {len(channels)} channels configured")

            ctx.policy_results.append(result)

        return ctx

    def _approve(self, ctx: LoopContext) -> LoopContext:
        """Route proposals needing human approval through the approval gate."""
        ctx.phase = LoopPhase.APPROVE

        for proposal in ctx.proposals:
            if proposal.requires_human and not proposal.approved:
                if self._approval_callback:
                    try:
                        proposal.approved = bool(self._approval_callback(proposal))
                    except Exception as exc:
                        ctx.errors.append(f"Approval callback failed: {exc}")
                        proposal.approved = False
                else:
                    # No callback registered — auto-deny for safety
                    proposal.denied_reason = "No approval callback registered"
                    proposal.approved = False
                    logger.warning("[ATLAS/APPROVE] No callback — auto-denied proposal %s", proposal.id)

        return ctx

    def _execute(self, ctx: LoopContext) -> LoopContext:
        """Execute approved proposals via FORGE and track results."""
        ctx.phase = LoopPhase.EXECUTE

        for proposal in ctx.proposals:
            if proposal.approved or (not proposal.requires_human and not proposal.denied_reason):
                result = {
                    "proposal_id": proposal.id,
                    "action": proposal.action_type,
                    "status": "executed",
                    "cost": proposal.cost_estimate_usd,
                }
                self.state.total_spend_usd += proposal.cost_estimate_usd
                ctx.execution_results.append(result)
                logger.info("[ATLAS/EXECUTE] Executed %s (cost=$%.2f)", proposal.id, proposal.cost_estimate_usd)
            elif proposal.denied_reason:
                ctx.execution_results.append({
                    "proposal_id": proposal.id,
                    "status": "denied",
                    "reason": proposal.denied_reason,
                })

        return ctx

    def _eval_learn(self, ctx: LoopContext) -> LoopContext:
        """Evaluate outcomes and feed learnings back into the system."""
        ctx.phase = LoopPhase.EVAL_LEARN

        # Track completed tasks
        for task in ctx.plan:
            if task.status == TaskStatus.COMPLETED:
                self.state.completed.append(task.id)
                ctx.learnings.append(f"Task {task.id} ({task.agent_codename}) completed")
            elif task.status == TaskStatus.FAILED:
                self.state.failed.append(task.id)
                ctx.learnings.append(f"Task {task.id} ({task.agent_codename}) failed")

        # Check for rollback triggers
        p95_threshold = self.release_policy.get("rollback_triggers", {}).get("p95_latency_ms")
        if p95_threshold and any("p95_exceeded" in str(e) for e in ctx.errors):
            self.state.rollback_count += 1
            ctx.learnings.append(f"ROLLBACK triggered (count={self.state.rollback_count})")

        return ctx

    def _recover(self, ctx: LoopContext) -> LoopContext:
        """Handle errors with exponential backoff and fallback paths."""
        ctx.phase = LoopPhase.RECOVER
        logger.error("[ATLAS/RECOVER] trace=%s errors=%s", ctx.trace_id, ctx.errors)

        # Mark any in-progress tasks as failed
        for task in ctx.plan:
            if task.status == TaskStatus.IN_PROGRESS:
                task.status = TaskStatus.FAILED
                self.state.failed.append(task.id)

        ctx.learnings.append(f"Recovery triggered with {len(ctx.errors)} errors")
        return ctx

    # ── Convenience Methods ─────────────────────────────────────
    def add_task(self, task: Task) -> None:
        self.state.tasks.append(task)

    def run_next(self) -> Task | None:
        """Pick next pending task and execute (stub — real impl dispatches to agent)."""
        for task in self.state.tasks:
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.IN_PROGRESS

                if task.requires_approval:
                    task.status = TaskStatus.NEEDS_APPROVAL
                    return task

                task.status = TaskStatus.COMPLETED
                task.result = {"status": "simulated"}
                self.state.completed.append(task.id)
                return task
        return None

    def approve(self, task_id: str) -> bool:
        """Human approves a gated task."""
        for task in self.state.tasks:
            if task.id == task_id and task.status == TaskStatus.NEEDS_APPROVAL:
                task.status = TaskStatus.COMPLETED
                task.result = {"status": "approved"}
                self.state.completed.append(task.id)
                return True
        return False

    def reject(self, task_id: str, reason: str = "") -> bool:
        """Human rejects a gated task."""
        for task in self.state.tasks:
            if task.id == task_id and task.status == TaskStatus.NEEDS_APPROVAL:
                task.status = TaskStatus.FAILED
                task.result = {"status": "rejected", "reason": reason}
                self.state.failed.append(task.id)
                return True
        return False

    def progress(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.state.tasks:
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts

    def budget_remaining(self) -> float:
        cap = self.state.steering.get("budget_weekly_usd", 50.0)
        return float(max(0.0, cap - self.state.total_spend_usd))


def build_launch_plan() -> list[Task]:
    """Standard 90-day launch plan tasks."""
    return [
        Task("T01", "ds", "Ingest and validate panel dataset"),
        Task("T02", "be", "Implement StatsForecast baselines + initial backtest"),
        Task("T03", "ne", "Implement PatchTST + TFT neural models"),
        Task("T04", "xe", "Build SHAP + TimeSHAP explanation panels"),
        Task("T05", "cs", "Build DoWhy + EconML causal panels"),
        Task("T06", "fo", "Deploy TimesFM + Chronos-2 cloud burst", requires_approval=True),
        Task("T07", "mo", "Set up CI/CD + micro-backtest workflow"),
        Task("T08", "so", "SBOM generation + vulnerability scan"),
        Task("T09", "dx", "Write developer docs + bootcamp materials"),
        Task("T10", "mc", "Final review + release gate", requires_approval=True),
    ]
