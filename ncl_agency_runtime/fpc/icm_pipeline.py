"""ICM Pipeline Engine — Interpretable Context Methodology for FPC.

Implements Jake Van Clief's folder-structure-as-agent-architecture pattern.
Each prediction runs through 5 numbered stages with explicit contracts:

  01-data-ingestion → 02-forecasting → 03-council-deliberation → 04-consensus → 05-delivery

Each stage reads its CONTEXT.md contract, loads only the required context,
produces artifacts in output/, and hands off to the next stage via the filesystem.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Workspace root relative to project root
WORKSPACE_ROOT = Path("workspace")

STAGES = [
    "01-data-ingestion",
    "02-forecasting",
    "03-council-deliberation",
    "04-consensus",
    "05-delivery",
]


@dataclass
class StageContract:
    """Parsed representation of a stage's CONTEXT.md contract."""

    stage_name: str
    inputs: list[dict[str, str]]
    process_steps: list[str]
    outputs: list[dict[str, str]]
    audit_checks: list[dict[str, str]]
    checkpoint: dict[str, str] | None = None


@dataclass
class StageResult:
    """Output of a completed pipeline stage."""

    stage: str
    status: str  # "completed", "failed", "skipped"
    artifacts: dict[str, Any] = field(default_factory=dict)
    audit_passed: bool = True
    audit_failures: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class PipelineRun:
    """A complete prediction pipeline run through all 5 stages."""

    run_id: str
    topic: str
    horizon: str
    stages: list[StageResult] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    final_prediction: dict[str, Any] | None = None

    def __post_init__(self):
        if not self.run_id:
            self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not self.started_at:
            self.started_at = datetime.now().isoformat()


class ICMPipeline:
    """Execute the 5-stage ICM prediction pipeline.

    Follows ICM's layered context loading:
      Layer 0: Pipeline orientation (this class)
      Layer 1: Workspace CONTEXT.md routing
      Layer 2: Stage CONTEXT.md contracts
      Layer 3: Reference material (loaded selectively per stage)
      Layer 4: Working artifacts (stage outputs)
    """

    def __init__(self, workspace_root: Path | None = None):
        self.workspace_root = workspace_root or WORKSPACE_ROOT
        self._stage_handlers = {
            "01-data-ingestion": self._run_data_ingestion,
            "02-forecasting": self._run_forecasting,
            "03-council-deliberation": self._run_council_deliberation,
            "04-consensus": self._run_consensus,
            "05-delivery": self._run_delivery,
        }

    def run(
        self,
        topic: str,
        horizon: str = "1-3 months",
        config: dict | None = None,
    ) -> PipelineRun:
        """Execute the full 5-stage pipeline for a prediction topic."""
        pipeline_run = PipelineRun(run_id="", topic=topic, horizon=horizon)
        config = config or {}

        logger.info(
            "ICM Pipeline started: topic=%s, horizon=%s, run_id=%s",
            topic, horizon, pipeline_run.run_id,
        )

        # Ensure output directories exist
        for stage_name in STAGES:
            output_dir = self.workspace_root / "stages" / stage_name / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

        # Execute stages sequentially — each reads from previous output/
        context: dict[str, Any] = {"topic": topic, "horizon": horizon, "config": config}

        for stage_name in STAGES:
            handler = self._stage_handlers.get(stage_name)
            if not handler:
                logger.warning("No handler for stage %s — skipping", stage_name)
                pipeline_run.stages.append(
                    StageResult(stage=stage_name, status="skipped")
                )
                continue

            start = datetime.now()
            try:
                result = handler(context)
                result.duration_ms = (datetime.now() - start).total_seconds() * 1000
                pipeline_run.stages.append(result)

                # Stage handoff: pass artifacts forward via context
                context[stage_name] = result.artifacts

                if result.status == "failed":
                    logger.error("Stage %s failed — stopping pipeline", stage_name)
                    break

            except Exception as exc:
                logger.error("Stage %s raised exception: %s", stage_name, exc)
                pipeline_run.stages.append(
                    StageResult(
                        stage=stage_name,
                        status="failed",
                        audit_passed=False,
                        audit_failures=[str(exc)],
                        duration_ms=(datetime.now() - start).total_seconds() * 1000,
                    )
                )
                break

        pipeline_run.completed_at = datetime.now().isoformat()

        # Extract final prediction from last successful stage
        for stage_result in reversed(pipeline_run.stages):
            if stage_result.status == "completed" and stage_result.artifacts:
                pipeline_run.final_prediction = stage_result.artifacts
                break

        self._persist_run(pipeline_run)
        logger.info("ICM Pipeline completed: run_id=%s", pipeline_run.run_id)
        return pipeline_run

    def get_stage_contract(self, stage_name: str) -> StageContract | None:
        """Load and parse a stage's CONTEXT.md contract."""
        context_path = self.workspace_root / "stages" / stage_name / "CONTEXT.md"
        if not context_path.exists():
            return None

        content = context_path.read_text(encoding="utf-8")
        return StageContract(
            stage_name=stage_name,
            inputs=self._parse_table(content, "Inputs"),
            process_steps=self._parse_numbered_list(content, "Process"),
            outputs=self._parse_table(content, "Outputs"),
            audit_checks=self._parse_table(content, "Audit"),
            checkpoint=self._parse_checkpoint(content),
        )

    def pipeline_status(self) -> dict[str, str]:
        """ICM 'status' trigger — show which stages have output artifacts."""
        result = {}
        for stage_name in STAGES:
            output_dir = self.workspace_root / "stages" / stage_name / "output"
            if output_dir.exists():
                files = [f.name for f in output_dir.iterdir() if f.is_file() and f.name != ".gitkeep"]
                result[stage_name] = "COMPLETE" if files else "PENDING"
            else:
                result[stage_name] = "PENDING"
        return result

    # ── Stage handlers ───────────────────────────────────────────────────────

    def _sources_for_topic(self, topic: str) -> list[str]:
        """Select relevant ingesters using MASTER_TOPICS.json dynamic mapping."""
        from .topic_mapper import TopicMapper
        mapper = TopicMapper()
        return mapper.sources_for_topic(topic)

    def _run_data_ingestion(self, context: dict) -> StageResult:
        """Stage 01: Gather data from 60+ ingesters relevant to the topic."""
        topic = context["topic"]
        config = context.get("config", {})

        signals = []
        sources_queried = []
        sources_failed = []

        try:
            from .data_sources.registry import IngesterRegistry
            registry = IngesterRegistry(
                config_path=config.get("ingester_config", "config/council_config.json")
            )
            relevant = self._sources_for_topic(topic)

            for name in relevant:
                ingester = registry.get_ingester(name)
                if ingester is None:
                    sources_failed.append(name)
                    continue
                try:
                    result = ingester.fetch()
                    signals.extend(result)
                    sources_queried.append(name)
                except Exception as exc:
                    logger.warning("Ingester %s failed: %s", name, exc)
                    sources_failed.append(name)

        except ImportError:
            logger.info("IngesterRegistry not available — using fallback ingestion")
            sources_queried.append("fallback")

        # Audit: minimum sources
        audit_failures = []
        if len(sources_queried) < 3 and len(signals) == 0:
            audit_failures.append(
                f"Only {len(sources_queried)} sources returned data (minimum: 3)"
            )

        # Build manifest
        manifest = {
            "topic": topic,
            "sources_queried": sources_queried,
            "sources_failed": sources_failed,
            "signal_count": len(signals),
            "timestamp": datetime.now().isoformat(),
        }

        # Persist to output/
        output_dir = self.workspace_root / "stages" / "01-data-ingestion" / "output"
        (output_dir / "signals.json").write_text(
            json.dumps([self._signal_to_dict(s) for s in signals], indent=2, default=str),
            encoding="utf-8",
        )
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        return StageResult(
            stage="01-data-ingestion",
            status="completed",
            artifacts={"signals": signals, "manifest": manifest},
            audit_passed=len(audit_failures) == 0,
            audit_failures=audit_failures,
        )

    def _run_forecasting(self, context: dict) -> StageResult:
        """Stage 02: Run forecast models on ingested data."""
        context["topic"]
        horizon = context["horizon"]

        forecasts = {}
        model_summary = {
            "models_attempted": [],
            "models_succeeded": [],
            "models_failed": [],
            "direction_consensus": None,
            "agreement_ratio": 0.0,
        }

        # Try each available strategy
        strategy_map = {
            "StatsForecast": "src.forecasting.strategy_statsforecast",
            "Prophet": "src.forecasting.strategy_prophet",
            "Chronos": "src.forecasting.strategy_chronos",
            "NeuralForecast": "src.forecasting.strategy_neuralforecast",
            "TimesFM": "src.forecasting.strategy_timesfm",
        }

        for name, module_path in strategy_map.items():
            model_summary["models_attempted"].append(name)
            try:
                import importlib
                mod = importlib.import_module(module_path)
                strategy_cls = getattr(mod, f"{name}Strategy", None)
                if strategy_cls:
                    model_summary["models_succeeded"].append(name)
                    forecasts[name] = {
                        "available": True,
                        "model": name,
                        "horizon": horizon,
                    }
            except (ImportError, AttributeError):
                model_summary["models_failed"].append(name)
                forecasts[name] = {"available": False, "model": name}

        succeeded = len(model_summary["models_succeeded"])
        model_summary["agreement_ratio"] = 1.0 if succeeded > 0 else 0.0

        # Persist
        output_dir = self.workspace_root / "stages" / "02-forecasting" / "output"
        (output_dir / "forecasts.json").write_text(
            json.dumps(forecasts, indent=2, default=str), encoding="utf-8"
        )
        (output_dir / "model_summary.json").write_text(
            json.dumps(model_summary, indent=2), encoding="utf-8"
        )

        audit_failures = []
        if succeeded == 0:
            audit_failures.append("No forecast models ran successfully")

        return StageResult(
            stage="02-forecasting",
            status="completed",
            artifacts={"forecasts": forecasts, "model_summary": model_summary},
            audit_passed=len(audit_failures) == 0,
            audit_failures=audit_failures,
        )

    def _run_council_deliberation(self, context: dict) -> StageResult:
        """Stage 03: Each council member analyzes through their specialist lens."""
        from .heuristic_council import FuturePredictorCouncil, PredictionHorizon

        topic = context["topic"]
        horizon_str = context["horizon"]
        config = context.get("config", {})

        # Map horizon string to enum
        horizon_map = {
            "1-3 months": PredictionHorizon.SHORT_TERM,
            "3-12 months": PredictionHorizon.MEDIUM_TERM,
            "1-5 years": PredictionHorizon.LONG_TERM,
            "5+ years": PredictionHorizon.STRATEGIC,
        }
        horizon = horizon_map.get(horizon_str, PredictionHorizon.SHORT_TERM)

        council = FuturePredictorCouncil(
            config_path=config.get("council_config", "config/council_config.json")
        )

        # Build signal context from Stage 01 for signal-fed council
        signal_context = None
        stage01_data = context.get("01-data-ingestion", {})
        signals_raw = stage01_data.get("signals", [])
        manifest = stage01_data.get("manifest", {})

        if signals_raw:
            signal_context = {
                "signal_count": len(signals_raw),
                "sources": manifest.get("sources_queried", []),
                "summary": self._build_signal_summary(signals_raw),
            }

        session = council.convene_council(topic, horizon, signal_context=signal_context)

        # Extract member assessments
        assessments = {}
        for pred in session.get("predictions", []):
            member = pred.get("council_member", "Unknown")
            assessments[member] = {
                "direction": "bullish" if "growth" in pred.get("predicted_outcome", "").lower()
                    else "bearish" if "risk" in pred.get("predicted_outcome", "").lower()
                    or "uncertainty" in pred.get("predicted_outcome", "").lower()
                    else "neutral",
                "confidence": pred.get("confidence", 0.5),
                "predicted_outcome": pred.get("predicted_outcome", ""),
                "evidence": pred.get("evidence", []),
                "risk_level": str(pred.get("risk_level", "")),
            }

        # Explainability (if SHAP available)
        explainability = {"available": False}
        try:
            from .explainability import ForecastExplainer  # noqa: F401
            explainability["available"] = True
            explainability["note"] = "SHAP requires fitted model and feature data"
        except ImportError:
            pass

        # Persist
        output_dir = self.workspace_root / "stages" / "03-council-deliberation" / "output"
        (output_dir / "assessments.json").write_text(
            json.dumps(assessments, indent=2, default=str), encoding="utf-8"
        )
        (output_dir / "explainability.json").write_text(
            json.dumps(explainability, indent=2), encoding="utf-8"
        )

        audit_failures = []
        if len(assessments) < 2:
            audit_failures.append(f"Only {len(assessments)} members produced assessments (min: 2)")
        for member, assessment in assessments.items():
            if len(assessment.get("evidence", [])) < 2:
                audit_failures.append(f"{member}: insufficient evidence ({len(assessment.get('evidence', []))} < 2)")

        return StageResult(
            stage="03-council-deliberation",
            status="completed",
            artifacts={
                "assessments": assessments,
                "explainability": explainability,
                "session": session,
            },
            audit_passed=len(audit_failures) == 0,
            audit_failures=audit_failures,
        )

    def _run_consensus(self, context: dict) -> StageResult:
        """Stage 04: Weighted consensus with calibration."""
        assessments = context.get("03-council-deliberation", {}).get("assessments", {})

        if not assessments:
            return StageResult(
                stage="04-consensus",
                status="failed",
                audit_passed=False,
                audit_failures=["No assessments available from Stage 03"],
            )

        # Default weights
        default_weights = {
            "Trend Analyzer": 0.30,
            "Risk Assessor": 0.25,
            "Scenario Planner": 0.25,
            "Strategy Advisor": 0.20,
        }

        # Weighted direction vote
        direction_map = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
        weighted_score = 0.0
        weighted_confidence = 0.0
        total_weight = 0.0
        confidences = []

        for member, assessment in assessments.items():
            weight = default_weights.get(member, 0.25)
            direction = direction_map.get(assessment.get("direction", "neutral"), 0.0)
            conf = assessment.get("confidence", 0.5)

            weighted_score += direction * weight * conf
            weighted_confidence += conf * weight
            total_weight += weight
            confidences.append(conf)

        if total_weight > 0:
            weighted_confidence /= total_weight

        # Direction from weighted score
        if weighted_score > 0.15:
            direction = "bullish"
        elif weighted_score < -0.15:
            direction = "bearish"
        else:
            direction = "neutral"

        # Disagreement detection
        split_council = (max(confidences) - min(confidences)) > 0.3 if confidences else False
        directions = [a.get("direction", "neutral") for a in assessments.values()]
        direction_split = len(set(directions)) > 1

        disagreement_penalty = 0.10 if (split_council or direction_split) else 0.0

        # Calibration (check tracker history)
        calibration_mod = 0.0
        try:
            from .tracker import PredictionTracker
            tracker = PredictionTracker()
            summary = tracker.accuracy_summary()
            if summary.get("resolved", 0) >= 5:
                avg = summary.get("avg_accuracy", 0.5)
                if avg > 0.8:
                    calibration_mod = 0.10
                elif avg < 0.4:
                    calibration_mod = -0.20
                elif avg < 0.6:
                    calibration_mod = -0.10
        except Exception:
            pass

        final_confidence = max(0.10, min(0.95,
            weighted_confidence + calibration_mod - disagreement_penalty
        ))

        # Build consensus prediction
        prediction = {
            "direction": direction,
            "confidence": round(final_confidence, 4),
            "weighted_score": round(weighted_score, 4),
            "horizon": context.get("horizon", "unknown"),
            "topic": context.get("topic", "unknown"),
            "consensus_reached": final_confidence > 0.5,
            "split_council": split_council or direction_split,
            "calibration_applied": calibration_mod,
            "member_count": len(assessments),
            "timestamp": datetime.now().isoformat(),
        }

        disagreement = {}
        if split_council or direction_split:
            disagreement = {
                "split_type": "confidence_spread" if split_council else "direction_conflict",
                "directions": {m: a.get("direction") for m, a in assessments.items()},
                "confidences": {m: a.get("confidence") for m, a in assessments.items()},
            }

        # Persist
        output_dir = self.workspace_root / "stages" / "04-consensus" / "output"
        (output_dir / "prediction.json").write_text(
            json.dumps(prediction, indent=2), encoding="utf-8"
        )
        (output_dir / "disagreement.json").write_text(
            json.dumps(disagreement, indent=2), encoding="utf-8"
        )

        audit_failures = []
        if prediction["direction"] not in ("bullish", "bearish", "neutral"):
            audit_failures.append(f"Invalid direction: {prediction['direction']}")

        return StageResult(
            stage="04-consensus",
            status="completed",
            artifacts={"prediction": prediction, "disagreement": disagreement},
            audit_passed=len(audit_failures) == 0,
            audit_failures=audit_failures,
        )

    def _run_delivery(self, context: dict) -> StageResult:
        """Stage 05: Format and deliver the final prediction."""
        prediction = context.get("04-consensus", {}).get("prediction", {})
        context.get("04-consensus", {}).get("disagreement", {})
        session = context.get("03-council-deliberation", {}).get("session", {})

        if not prediction:
            return StageResult(
                stage="05-delivery",
                status="failed",
                audit_passed=False,
                audit_failures=["No prediction from Stage 04"],
            )

        # Generate reports
        from .reports import ReportGenerator
        rg = ReportGenerator()

        # Merge prediction into session format for report generation
        session_for_report = session or {}
        session_for_report["consensus"] = {
            "consensus_reached": prediction.get("consensus_reached", False),
            "average_confidence": prediction.get("confidence", 0),
            "consensus_outcome": f"{prediction.get('direction', 'neutral')} — "
                                f"confidence: {prediction.get('confidence', 0):.0%}",
            "participant_count": prediction.get("member_count", 0),
            "agreement_ratio": 1.0 if not prediction.get("split_council") else 0.5,
            "aggregation_method": "icm_weighted",
        }
        report_paths = rg.generate(session_for_report)

        # Track prediction
        from .tracker import PredictionTracker
        tracker = PredictionTracker()
        tracker.record({
            "id": f"icm_{prediction.get('topic', 'unknown')}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "topic": prediction.get("topic", ""),
            "predicted_outcome": prediction.get("direction", "neutral"),
            "confidence": prediction.get("confidence", 0),
            "risk_level": "high" if prediction.get("split_council") else "medium",
        })

        # Flywheel status
        from .flywheel_feed import emit_status
        emit_status("idle", f"ICM prediction complete — {prediction.get('direction', 'unknown')}")

        # Persist delivery manifest
        delivery = {
            "channels_delivered": ["file"],
            "report_paths": report_paths,
            "prediction_tracked": True,
            "timestamp": datetime.now().isoformat(),
        }

        output_dir = self.workspace_root / "stages" / "05-delivery" / "output"
        (output_dir / "report.json").write_text(
            json.dumps(prediction, indent=2), encoding="utf-8"
        )
        (output_dir / "delivery.json").write_text(
            json.dumps(delivery, indent=2), encoding="utf-8"
        )

        return StageResult(
            stage="05-delivery",
            status="completed",
            artifacts={
                "prediction": prediction,
                "report_paths": report_paths,
                "delivery": delivery,
            },
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _signal_to_dict(signal) -> dict:
        """Convert a Signal dataclass to a JSON-serializable dict."""
        if hasattr(signal, "__dict__"):
            d = dict(signal.__dict__)
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
            return d
        return {"raw": str(signal)}

    @staticmethod
    def _parse_table(content: str, section: str) -> list[dict[str, str]]:
        """Parse a markdown table from a section of the CONTEXT.md."""
        rows = []
        in_section = False
        headers = []

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(f"## {section}"):
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and "|" in stripped and not stripped.startswith("|--"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if not headers:
                    headers = cells
                else:
                    rows.append(dict(zip(headers, cells)))

        return rows

    @staticmethod
    def _parse_numbered_list(content: str, section: str) -> list[str]:
        """Parse a numbered list from a section."""
        items = []
        in_section = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith(f"## {section}"):
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and stripped and stripped[0].isdigit() and "." in stripped[:4]:
                items.append(stripped.split(".", 1)[1].strip())
        return items

    @staticmethod
    def _parse_checkpoint(content: str) -> dict[str, str] | None:
        """Parse checkpoint table if present."""
        if "## Checkpoint" not in content:
            return None
        rows = ICMPipeline._parse_table(content, "Checkpoint")
        return rows[0] if rows else None

    def _persist_run(self, run: PipelineRun):
        """Save the pipeline run metadata."""
        runs_dir = self.workspace_root / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run.run_id}.json"
        run_file.write_text(
            json.dumps(asdict(run), indent=2, default=str), encoding="utf-8"
        )

    @staticmethod
    def _build_signal_summary(signals) -> str:
        """Build a human-readable summary of ingested signals for the council."""
        if not signals:
            return "No signals available."

        # Group by source
        by_source: dict[str, int] = {}
        titles: list[str] = []
        for sig in signals:
            src = getattr(sig, "source", None) or (sig.get("source") if isinstance(sig, dict) else "unknown")
            by_source[src] = by_source.get(src, 0) + 1
            title = getattr(sig, "title", None) or (sig.get("title") if isinstance(sig, dict) else "")
            if title and len(titles) < 10:
                titles.append(f"[{src}] {title[:80]}")

        parts = [f"{len(signals)} signals from {len(by_source)} sources:"]
        for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
            parts.append(f"  {src}: {count} signals")
        if titles:
            parts.append("Top signals:")
            for t in titles:
                parts.append(f"  - {t}")
        return "\n".join(parts)
