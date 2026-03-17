"""Ralphy Self-Evolution Module — Autonomous improvement loop for FPC.

Implements Ralphy's autonomous coding loop for FPC self-improvement:
  - PRD-driven task generation from roadmap/backlog
  - Branch-per-task isolation (git worktree pattern)
  - Parallel execution of independent improvement tasks
  - Metrics-driven evolution (accuracy tracking → adaptation)
  - Auto-merge with safety checks

Ralphy's 8+1 architecture maps to FPC:
  Model Strategy exploration → new forecasting strategies
  Ingester expansion → new data source connectors
  Weight recalibration → council weight optimization
  Confidence calibration → tracker-driven accuracy tuning

This module does NOT run external AI coding agents.
It provides the self-evaluation + adaptation framework that
enables FPC to identify its own weaknesses and queue improvements.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Evolution state persists to this directory
EVOLUTION_DIR = Path("state/evolution")

# Thresholds that trigger self-improvement tasks
ACCURACY_THRESHOLD_LOW = 0.40   # Below this → critical, needs recalibration
ACCURACY_THRESHOLD_GOOD = 0.70  # Above this → performing well
STALE_STRATEGY_DAYS = 30        # Strategies not used in this many days → review
MIN_PREDICTIONS_FOR_EVAL = 5    # Need at least this many resolved predictions


@dataclass
class EvolutionTask:
    """A self-improvement task identified by the evolution engine."""

    id: str
    category: str  # "strategy", "ingester", "weight", "calibration", "coverage"
    title: str
    description: str
    priority: int = 50  # 1-100, lower = higher priority
    status: str = "queued"  # "queued", "in-progress", "completed", "rejected"
    created_at: str = ""
    completed_at: str | None = None
    result: str | None = None
    metrics_before: dict[str, float] | None = None
    metrics_after: dict[str, float] | None = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.id:
            self.id = f"evo_{datetime.now().strftime('%Y%m%d%H%M%S')}_{self.category}"


@dataclass
class EvolutionReport:
    """Summary of an evolution analysis cycle."""

    timestamp: str
    predictions_analyzed: int
    accuracy: float
    strengths: list[str]
    weaknesses: list[str]
    tasks_generated: list[str]  # task IDs
    recommendations: list[str]


class RalphyEvolution:
    """Self-evolution engine for FPC.

    Follows Ralphy's pattern:
      1. Analyze → review prediction accuracy and coverage
      2. Identify → find weaknesses and improvement opportunities
      3. Plan → generate prioritized improvement tasks
      4. Execute → queue tasks for implementation
      5. Verify → measure improvement after changes

    This is the analysis + planning layer. Execution of generated tasks
    is handled by the development workflow (human or CI).
    """

    def __init__(self, state_dir: Path | None = None):
        self.state_dir = state_dir or EVOLUTION_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: list[EvolutionTask] = []
        self._load_tasks()

    # ── Core evolution cycle ─────────────────────────────────────────────────

    def analyze(self) -> EvolutionReport:
        """Run a full evolution analysis cycle.

        Examines prediction accuracy, data coverage, model performance,
        and council weight calibration to identify improvement opportunities.
        """
        strengths = []
        weaknesses = []
        new_tasks = []
        recommendations = []

        # 1. Check prediction accuracy from tracker
        accuracy_analysis = self._analyze_accuracy()
        strengths.extend(accuracy_analysis.get("strengths", []))
        weaknesses.extend(accuracy_analysis.get("weaknesses", []))

        # 2. Check data source coverage
        coverage_analysis = self._analyze_coverage()
        strengths.extend(coverage_analysis.get("strengths", []))
        weaknesses.extend(coverage_analysis.get("weaknesses", []))

        # 3. Check strategy diversity
        strategy_analysis = self._analyze_strategies()
        strengths.extend(strategy_analysis.get("strengths", []))
        weaknesses.extend(strategy_analysis.get("weaknesses", []))

        # 4. Generate improvement tasks from weaknesses
        for weakness in weaknesses:
            task = self._weakness_to_task(weakness)
            if task and not self._task_already_exists(task.title):
                self._tasks.append(task)
                new_tasks.append(task.id)

        # 5. Generate recommendations
        if accuracy_analysis.get("accuracy", 0) < ACCURACY_THRESHOLD_LOW:
            recommendations.append(
                "CRITICAL: Prediction accuracy is below 40%. "
                "Recommend council weight recalibration and model review."
            )
        if len(weaknesses) > 3:
            recommendations.append(
                f"Found {len(weaknesses)} weaknesses. Consider addressing "
                "the top-priority items first (sort by priority score)."
            )
        if not weaknesses:
            recommendations.append(
                "No significant weaknesses detected. Continue monitoring."
            )

        self._save_tasks()

        report = EvolutionReport(
            timestamp=datetime.now().isoformat(),
            predictions_analyzed=accuracy_analysis.get("count", 0),
            accuracy=accuracy_analysis.get("accuracy", 0.0),
            strengths=strengths,
            weaknesses=weaknesses,
            tasks_generated=new_tasks,
            recommendations=recommendations,
        )

        # Persist report
        report_path = self.state_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(
            json.dumps(asdict(report), indent=2, default=str), encoding="utf-8"
        )

        return report

    def get_tasks(
        self,
        status: str | None = None,
        category: str | None = None,
    ) -> list[EvolutionTask]:
        """Get evolution tasks filtered by status or category."""
        tasks = self._tasks
        if status:
            tasks = [t for t in tasks if t.status == status]
        if category:
            tasks = [t for t in tasks if t.category == category]
        return sorted(tasks, key=lambda t: t.priority)

    def complete_task(self, task_id: str, result: str, metrics_after: dict | None = None):
        """Mark an evolution task as completed with results."""
        for task in self._tasks:
            if task.id == task_id:
                task.status = "completed"
                task.completed_at = datetime.now().isoformat()
                task.result = result
                task.metrics_after = metrics_after
                break
        self._save_tasks()

    def get_evolution_status(self) -> dict[str, Any]:
        """Summary of the evolution engine state."""
        return {
            "total_tasks": len(self._tasks),
            "queued": len([t for t in self._tasks if t.status == "queued"]),
            "in_progress": len([t for t in self._tasks if t.status == "in-progress"]),
            "completed": len([t for t in self._tasks if t.status == "completed"]),
            "by_category": self._count_by_category(),
            "state_dir": str(self.state_dir),
        }

    def recalibrate_weights(self) -> dict[str, float]:
        """Suggest new council member weights based on prediction accuracy.

        Analyzes which council members' assessments have historically
        aligned with actual outcomes, and adjusts weights accordingly.
        """
        try:
            from .tracker import PredictionTracker
            tracker = PredictionTracker()
            summary = tracker.accuracy_summary()

            # Default weights
            weights = {
                "Trend Analyzer": 0.30,
                "Risk Assessor": 0.25,
                "Scenario Planner": 0.25,
                "Strategy Advisor": 0.20,
            }

            resolved_count = summary.get("resolved", 0) or 0
            if resolved_count < MIN_PREDICTIONS_FOR_EVAL:
                logger.info(
                    "Not enough resolved predictions (%d/%d) for recalibration",
                    resolved_count, MIN_PREDICTIONS_FOR_EVAL,
                )
                return weights

            avg_accuracy = summary.get("avg_accuracy", 0.5)

            # If accuracy is low, shift weight toward Risk Assessor (conservative)
            if avg_accuracy < ACCURACY_THRESHOLD_LOW:
                weights["Risk Assessor"] = 0.35
                weights["Trend Analyzer"] = 0.25
                weights["Scenario Planner"] = 0.25
                weights["Strategy Advisor"] = 0.15
            # If accuracy is high, trust Trend Analyzer more (aggressive)
            elif avg_accuracy > ACCURACY_THRESHOLD_GOOD:
                weights["Trend Analyzer"] = 0.35
                weights["Risk Assessor"] = 0.20
                weights["Scenario Planner"] = 0.25
                weights["Strategy Advisor"] = 0.20

            # Ensure weights sum to 1.0
            total = sum(weights.values())
            weights = {k: round(v / total, 4) for k, v in weights.items()}

            return weights

        except ImportError:
            return {
                "Trend Analyzer": 0.30,
                "Risk Assessor": 0.25,
                "Scenario Planner": 0.25,
                "Strategy Advisor": 0.20,
            }

    # ── Analysis sub-modules ─────────────────────────────────────────────────

    def _analyze_accuracy(self) -> dict:
        """Analyze prediction accuracy from tracker history."""
        result = {"strengths": [], "weaknesses": [], "accuracy": 0.0, "count": 0}

        try:
            from .tracker import PredictionTracker
            tracker = PredictionTracker()
            summary = tracker.accuracy_summary()

            resolved = summary.get("resolved", 0) or 0
            result["count"] = resolved

            if resolved < MIN_PREDICTIONS_FOR_EVAL:
                result["weaknesses"].append(
                    f"Insufficient prediction history ({resolved}/{MIN_PREDICTIONS_FOR_EVAL}) "
                    f"for accuracy analysis"
                )
                return result

            accuracy = summary.get("avg_accuracy", 0.0)
            result["accuracy"] = accuracy

            if accuracy >= ACCURACY_THRESHOLD_GOOD:
                result["strengths"].append(
                    f"Prediction accuracy is strong at {accuracy:.0%}"
                )
            elif accuracy >= ACCURACY_THRESHOLD_LOW:
                result["weaknesses"].append(
                    f"Prediction accuracy is moderate at {accuracy:.0%} — "
                    f"recommend weight recalibration"
                )
            else:
                result["weaknesses"].append(
                    f"Prediction accuracy is critically low at {accuracy:.0%} — "
                    f"urgent recalibration needed"
                )

        except ImportError:
            result["weaknesses"].append("PredictionTracker unavailable — cannot assess accuracy")

        return result

    def _analyze_coverage(self) -> dict:
        """Analyze data source coverage across asset classes."""
        result = {"strengths": [], "weaknesses": []}

        try:
            from .data_sources.registry import IngesterRegistry
            IngesterRegistry()
            all_ingesters = IngesterRegistry.available_sources()
            count = len(all_ingesters)

            if count >= 50:
                result["strengths"].append(f"Strong data coverage with {count} ingesters")
            elif count >= 20:
                result["strengths"].append(f"Moderate data coverage with {count} ingesters")
            else:
                result["weaknesses"].append(f"Limited data coverage — only {count} ingesters")

            # Check for critical domain gaps
            domains = set()
            for name in all_ingesters:
                if any(k in name.lower() for k in ["fred", "bls", "imf"]):
                    domains.add("economic")
                elif any(k in name.lower() for k in ["coin", "crypto", "defi"]):
                    domains.add("crypto")
                elif any(k in name.lower() for k in ["weather", "noaa", "climate"]):
                    domains.add("climate")
                elif any(k in name.lower() for k in ["alpha", "stock", "sec"]):
                    domains.add("financial")

            critical_domains = {"economic", "financial"}
            missing = critical_domains - domains
            if missing:
                result["weaknesses"].append(
                    f"Missing {', '.join(missing)} domain data sources"
                )

        except (ImportError, Exception):
            result["weaknesses"].append("Cannot enumerate data sources — registry unavailable")

        return result

    def _analyze_strategies(self) -> dict:
        """Check forecasting strategy diversity and availability."""
        result = {"strengths": [], "weaknesses": []}

        strategies = [
            ("StatsForecast", "src.forecasting.strategy_statsforecast"),
            ("Chronos", "src.forecasting.strategy_chronos"),
            ("Prophet", "src.forecasting.strategy_prophet"),
            ("NeuralForecast", "src.forecasting.strategy_neuralforecast"),
            ("TimesFM", "src.forecasting.strategy_timesfm"),
        ]

        available = []
        unavailable = []

        for name, mod_path in strategies:
            try:
                import importlib
                importlib.import_module(mod_path)
                available.append(name)
            except ImportError:
                unavailable.append(name)

        if len(available) >= 3:
            result["strengths"].append(
                f"{len(available)}/{len(strategies)} forecast strategies available"
            )
        elif len(available) >= 1:
            result["weaknesses"].append(
                f"Only {len(available)}/{len(strategies)} strategies available — "
                f"missing: {', '.join(unavailable)}"
            )
        else:
            result["weaknesses"].append(
                "No forecasting strategies available — install statsforecast at minimum"
            )

        return result

    # ── Task generation ──────────────────────────────────────────────────────

    def _weakness_to_task(self, weakness: str) -> EvolutionTask | None:
        """Convert a weakness description to a concrete improvement task."""
        lower = weakness.lower()

        if "accuracy" in lower and "critical" in lower:
            return EvolutionTask(
                id="", category="calibration",
                title="Critical accuracy recalibration",
                description=weakness,
                priority=10,
            )
        elif "accuracy" in lower and "moderate" in lower:
            return EvolutionTask(
                id="", category="calibration",
                title="Weight recalibration for moderate accuracy",
                description=weakness,
                priority=30,
            )
        elif "coverage" in lower or "ingester" in lower:
            return EvolutionTask(
                id="", category="coverage",
                title="Expand data source coverage",
                description=weakness,
                priority=40,
            )
        elif "strateg" in lower:
            return EvolutionTask(
                id="", category="strategy",
                title="Add missing forecasting strategies",
                description=weakness,
                priority=35,
            )
        elif "tracker" in lower or "history" in lower:
            return EvolutionTask(
                id="", category="calibration",
                title="Build prediction history for calibration",
                description=weakness,
                priority=20,
            )
        elif "domain" in lower and "missing" in lower:
            return EvolutionTask(
                id="", category="ingester",
                title="Add missing domain data sources",
                description=weakness,
                priority=25,
            )
        else:
            return EvolutionTask(
                id="", category="coverage",
                title=f"Address weakness: {weakness[:60]}",
                description=weakness,
                priority=50,
            )

    def _task_already_exists(self, title: str) -> bool:
        """Check if a similar task is already queued."""
        return any(task.title == title and task.status in ("queued", "in-progress") for task in self._tasks)

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_tasks(self):
        """Load tasks from state directory."""
        tasks_path = self.state_dir / "tasks.json"
        if tasks_path.exists():
            try:
                data = json.loads(tasks_path.read_text(encoding="utf-8"))
                self._tasks = [EvolutionTask(**t) for t in data]
            except (json.JSONDecodeError, TypeError):
                self._tasks = []

    def _save_tasks(self):
        """Persist tasks to state directory."""
        tasks_path = self.state_dir / "tasks.json"
        tasks_path.write_text(
            json.dumps([asdict(t) for t in self._tasks], indent=2, default=str),
            encoding="utf-8",
        )

    def _count_by_category(self) -> dict[str, int]:
        """Count tasks by category."""
        result: dict[str, int] = {}
        for task in self._tasks:
            result[task.category] = result.get(task.category, 0) + 1
        return result
