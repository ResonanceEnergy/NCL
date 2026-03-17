"""Thinking Layer Orchestrator — Unifies ICM, OpenClaw, and Ralphy for FPC.

This is the top-level integration point that ties together:
  - ICM Pipeline: 5-stage prediction execution with contracts/audits
  - OpenClaw Gateway: Runtime delivery to 24+ channels
  - Ralphy Evolution: Self-assessment and weight recalibration

The orchestrator provides a single `think()` method that:
  1. Fires OpenClaw hooks (before_prompt_build) to inject domain context
  2. Runs the 5-stage ICM pipeline for prediction generation
  3. Delivers results via OpenClaw channels
  4. Triggers Ralphy evolution analysis post-prediction
  5. Emits flywheel status for BRS pipeline visibility
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .icm_pipeline import ICMPipeline, PipelineRun
from .openclaw_gateway import (
    CronJob,
    OpenClawGateway,
    WebhookTrigger,
)
from .ralphy_evolution import EvolutionReport, RalphyEvolution

logger = logging.getLogger(__name__)


@dataclass
class ThinkingResult:
    """Complete result of a thinking layer invocation."""

    pipeline_run: PipelineRun | None = None
    prediction: dict[str, Any] | None = None
    delivery_results: dict[str, str] = field(default_factory=dict)
    evolution_report: EvolutionReport | None = None
    gateway_status: dict[str, Any] | None = None
    thinking_duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ThinkingLayer:
    """Unified thinking layer integrating ICM + OpenClaw + Ralphy.

    Usage:
        thinking = ThinkingLayer()
        result = thinking.think("Bitcoin price trajectory", horizon="1-3 months")
        print(result.prediction)
    """

    def __init__(
        self,
        config: dict | None = None,
        workspace_root: Path | None = None,
        gateway_url: str | None = None,
        gateway_api_key: str | None = None,
        evolution_dir: Path | None = None,
    ):
        config = config or self._load_config()

        # Initialize the three subsystems
        self.icm = ICMPipeline(
            workspace_root=workspace_root or Path(config.get("workspace_root", "workspace"))
        )
        self.gateway = OpenClawGateway(
            gateway_url=gateway_url or config.get("gateway_url", "http://127.0.0.1:18789"),
            api_key=gateway_api_key or config.get("gateway_api_key"),
        )
        self.evolution = RalphyEvolution(
            state_dir=evolution_dir or Path(config.get("evolution_dir", "state/evolution"))
        )

        self._config = config

        # Set up delivery channels from config
        for channel_name, channel_config in config.get("channels", {}).items():
            self.gateway.configure_channel(channel_name, channel_config)

        # Default file channel always available
        if "file" not in config.get("channels", {}):
            self.gateway.configure_channel("file", {"output_dir": "reports"})

    def think(
        self,
        topic: str,
        horizon: str = "1-3 months",
        channels: list[str] | None = None,
        run_evolution: bool = True,
        config: dict | None = None,
    ) -> ThinkingResult:
        """Execute a complete prediction through the thinking layer.

        Flow:
          1. OpenClaw before_prompt_build → inject domain context
          2. ICM 5-stage pipeline → generate prediction
          3. OpenClaw delivery → push to channels
          4. Ralphy evolution → analyze and improve
          5. Flywheel emit → BRS visibility
        """
        start = datetime.now()
        run_config = config or {}

        # ── Step 1: OpenClaw pre-processing ──────────────────────────────────
        context = {"topic": topic, "horizon": horizon}
        context = self.gateway.fire_hook("before_prompt_build", context)
        run_config.update({k: v for k, v in context.items() if k not in run_config})

        # ── Step 2: ICM Pipeline execution ───────────────────────────────────
        logger.info("Thinking: starting ICM pipeline for topic=%s", topic)
        pipeline_run = self.icm.run(topic=topic, horizon=horizon, config=run_config)

        prediction = pipeline_run.final_prediction

        # Fire after_tool_call hook with results
        self.gateway.fire_hook("after_tool_call", {
            "tool_result": prediction,
            "pipeline_run_id": pipeline_run.run_id,
        })

        # ── Step 3: Delivery via OpenClaw ────────────────────────────────────
        delivery_results = {}
        if prediction:
            delivery_results = self.gateway.deliver_prediction(
                prediction=prediction,
                channels=channels,
            )

            # Fire agent_end hook
            self.gateway.fire_hook("agent_end", {
                "prediction": prediction,
                "delivery_results": delivery_results,
            })

        # ── Step 4: Ralphy evolution ─────────────────────────────────────────
        evolution_report = None
        if run_evolution:
            try:
                evolution_report = self.evolution.analyze()

                # If evolution suggests weight recalibration, apply it
                if evolution_report.accuracy < 0.5 and evolution_report.predictions_analyzed >= 5:
                    new_weights = self.evolution.recalibrate_weights()
                    logger.info("Evolution triggered weight recalibration: %s", new_weights)
            except Exception as exc:
                logger.warning("Evolution analysis failed: %s", exc)

        # ── Step 5: Flywheel status ──────────────────────────────────────────
        self._emit_flywheel(prediction, pipeline_run)

        duration = (datetime.now() - start).total_seconds() * 1000

        result = ThinkingResult(
            pipeline_run=pipeline_run,
            prediction=prediction,
            delivery_results=delivery_results,
            evolution_report=evolution_report,
            gateway_status=self.gateway.get_gateway_status(),
            thinking_duration_ms=duration,
        )

        logger.info(
            "Thinking complete: topic=%s, direction=%s, confidence=%s, duration=%.0fms",
            topic,
            prediction.get("prediction", {}).get("direction", "unknown") if prediction else "none",
            prediction.get("prediction", {}).get("confidence", 0) if prediction else 0,
            duration,
        )

        return result

    def status(self) -> dict[str, Any]:
        """Return combined status of all three subsystems."""
        return {
            "icm_pipeline": self.icm.pipeline_status(),
            "gateway": self.gateway.get_gateway_status(),
            "evolution": self.evolution.get_evolution_status(),
            "config_loaded": bool(self._config),
        }

    def schedule_prediction(self, schedule: str, topic: str, horizon: str = "1-3 months"):
        """Add a recurring prediction via OpenClaw cron."""
        self.gateway.add_cron_job(CronJob(
            schedule=schedule,
            topic=topic,
            horizon=horizon,
        ))

    def add_trigger(self, event_type: str, topic_template: str, horizon: str = "1-3 months"):
        """Add an event-triggered prediction via OpenClaw webhook."""
        self.gateway.add_webhook_trigger(WebhookTrigger(
            event_type=event_type,
            topic_template=topic_template,
            horizon=horizon,
        ))

    def handle_event(self, event_type: str, event_data: dict) -> ThinkingResult | None:
        """Handle an incoming event — trigger prediction if matched."""
        prediction_config = self.gateway.handle_webhook(event_type, event_data)
        if prediction_config:
            return self.think(
                topic=prediction_config["topic"],
                horizon=prediction_config["horizon"],
            )
        return None

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _emit_flywheel(self, prediction: dict | None, pipeline_run: PipelineRun):
        """Emit flywheel status for BRS pipeline visibility."""
        try:
            from .flywheel_feed import emit_status
            if prediction:
                # Extract direction from nested or flat structure
                direction = "unknown"
                if isinstance(prediction, dict):
                    p = prediction.get("prediction", prediction)
                    direction = p.get("direction", "unknown")

                emit_status(
                    "idle",
                    f"ICM prediction: {direction} | "
                    f"run: {pipeline_run.run_id}",
                    {
                        "pipeline_run_id": pipeline_run.run_id,
                        "stages_completed": len([
                            s for s in pipeline_run.stages if s.status == "completed"
                        ]),
                        "stages_total": len(pipeline_run.stages),
                    },
                )
            else:
                emit_status(
                    "error",
                    "ICM pipeline produced no prediction",
                    {"pipeline_run_id": pipeline_run.run_id},
                )
        except ImportError:
            pass

    @staticmethod
    def _load_config() -> dict:
        """Load thinking layer config from config/thinking_config.json."""
        config_path = Path("config/thinking_config.json")
        if config_path.exists():
            try:
                return json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        # Defaults
        return {
            "workspace_root": "workspace",
            "gateway_url": "http://127.0.0.1:18789",
            "gateway_api_key": None,
            "evolution_dir": "state/evolution",
            "channels": {
                "file": {"output_dir": "reports"},
            },
        }
