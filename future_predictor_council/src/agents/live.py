"""Live System Bootstrap — wires ATLAS + Router + Agents + Policy into a running system.

Usage:
    from future_predictor_council.src.agents.live import boot, LiveSystem

    system = boot()
    system.dispatch_intent("Run a 14-day forecast on sales data")
    system.status()
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from . import ALL_AGENTS
from .events import (
    Event,
    EventType,
    make_data_update,
    make_intent,
    make_model_cycle,
)
from .expansion import register_expansion
from .orchestrator import MissionControl
from .policy import PolicyEngine
from .router import EventRouter
from .stubs import register_all

logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]


class LiveSystem:
    """The fully wired autonomous agent system.

    Components:
        router  — EventRouter (real-time event dispatch)
        atlas   — MissionControl (OBSERVE→...→EVAL_LEARN state machine)
        policy  — PolicyEngine (budget, channels, rollback, security)
    """

    def __init__(
        self,
        config_path: str | pathlib.Path | None = None,
        policy_path: str | pathlib.Path | None = None,
    ) -> None:
        config = config_path or BASE_DIR / "config" / "steering.json"
        policy = policy_path or BASE_DIR / "ops" / "ReleasePolicy.yaml"

        # Core components
        self.policy = PolicyEngine(steering_path=config, policy_path=policy)
        self.atlas = MissionControl(config_path=config, policy_path=policy)
        self.router = EventRouter()

        # Register all agents
        register_all(self.atlas)
        register_expansion(self.atlas)

        # Wire router → ATLAS
        self.router.set_atlas(self._atlas_event_handler)

        # Wire type-specific subscribers
        self.router.subscribe(EventType.MODEL_CYCLE, self._on_model_cycle)
        self.router.subscribe(EventType.TELEMETRY_AGENT, self._on_telemetry)
        self.router.subscribe(EventType.ACTION_RESULT, self._on_action_result)

        # Loop history
        self._loop_results: list[dict[str, Any]] = []

    # ── Event Handlers ──────────────────────────────────────────
    def _atlas_event_handler(self, event: Event) -> None:
        """Route event through ATLAS mission control loop."""
        ctx = self.atlas.run_loop(event.to_dict())
        self._loop_results.append({
            "trace_id": ctx.trace_id,
            "phase": ctx.phase.value,
            "tasks": len(ctx.plan),
            "errors": len(ctx.errors),
            "learnings": ctx.learnings,
        })

    def _on_model_cycle(self, event: Event) -> None:
        """Handle model cycle events — check metrics, trigger XAI."""
        metrics = event.payload.get("metrics", {})
        mase = metrics.get("MASE", 0)
        logger.info("[LIVE] Model cycle: MASE=%.3f", mase)

    def _on_telemetry(self, event: Event) -> None:
        """Handle agent telemetry — check for p95 breaches."""
        latency = event.payload.get("latency_ms", 0)
        if latency > 2000:
            logger.warning("[LIVE] High latency from %s: %.1fms", event.source, latency)

    def _on_action_result(self, event: Event) -> None:
        """Handle action results — evaluate and learn."""
        cost = event.cost.usd
        if cost > 0:
            self.policy.record_spend(cost, source=event.source)

    # ── Public API ──────────────────────────────────────────────
    def dispatch_intent(self, goal: str, **kwargs: Any) -> dict[str, Any]:
        """Send a user intent through the system."""
        event = make_intent(goal, **kwargs)
        success = self.router.route(event)
        return {
            "success": success,
            "trace_id": event.trace_id,
            "goal": goal,
        }

    def dispatch_data_update(self, dataset: str, rows: int = 0) -> dict[str, Any]:
        event = make_data_update(dataset, rows)
        success = self.router.route(event)
        return {"success": success, "trace_id": event.trace_id, "dataset": dataset}

    def dispatch_model_cycle(self, model: str, mase: float, smape: float) -> dict[str, Any]:
        event = make_model_cycle(model, mase, smape)
        success = self.router.route(event)
        return {"success": success, "trace_id": event.trace_id, "model": model}

    def dispatch_event(self, event: Event) -> bool:
        """Dispatch an arbitrary event."""
        return self.router.route(event)

    def status(self) -> dict[str, Any]:
        """System-wide status dashboard."""
        return {
            "router": self.router.health(),
            "atlas": {
                "tasks_total": len(self.atlas.state.tasks),
                "completed": len(self.atlas.state.completed),
                "failed": len(self.atlas.state.failed),
                "loops_run": len(self.atlas.state.loop_history),
                "budget_remaining": self.atlas.budget_remaining(),
                "rollback_count": self.atlas.state.rollback_count,
            },
            "policy": self.policy.spend_summary(),
            "agents": {
                "launch_squadron": len([a for a in ALL_AGENTS if a.tier.value != "expansion"]),
                "expansion_pack": len([a for a in ALL_AGENTS if a.tier.value == "expansion"]),
                "total": len(ALL_AGENTS),
            },
        }

    def roster(self) -> list[dict[str, str]]:
        """Return all agents with their callsigns."""
        return [
            {"codename": a.codename, "callsign": a.callsign, "name": a.name, "tier": a.tier.value}
            for a in ALL_AGENTS
        ]


def boot(
    config_path: str | pathlib.Path | None = None,
    policy_path: str | pathlib.Path | None = None,
) -> LiveSystem:
    """Boot the full autonomous agent system."""
    system = LiveSystem(config_path=config_path, policy_path=policy_path)
    logger.info("[LIVE] System booted — %d agents registered", len(ALL_AGENTS))
    return system
