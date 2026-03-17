#!/usr/bin/env python3
"""
NUREALCORTEXLINK Golden Task Evaluation Harness

Runs golden tasks to evaluate AI agent performance in the second brain system.
Supports capture, summarize, plan, recall, and pattern recognition tasks.

Strategic Doctrine Integration:
- Art of War: 'Every battle is won before it is fought' — golden tasks validate
  readiness before deployment.
- Habit 2: Begin with the End in Mind — each task defines expected outcomes upfront.
- Law 9: Win through actions, not argument — test results are evidence, not opinion.

Usage:
    python evaluation_harness.py [--task-id TASK_ID] [--all] [--verbose]

Author: NUREALCORTEXLINK Evaluation System
"""

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class TaskType(Enum):
    SUMMARIZE = "summarize"
    EXTRACT = "extract"
    CATEGORIZE = "categorize"
    INSIGHT = "insight"
    PATTERN = "pattern"


@dataclass
class GoldenTask:
    id: str
    name: str
    input_data: dict[str, Any]
    expected_output: dict[str, Any]
    failure_conditions: list[str]

    @classmethod
    def from_file(cls, filepath: Path) -> 'GoldenTask':
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        return cls(
            id=data['id'],
            name=data['name'],
            input_data=data['input'],
            expected_output=data['expected'],
            failure_conditions=data.get('failure_conditions', [])
        )


@dataclass
class EvaluationResult:
    task_id: str
    passed: bool
    score: float
    failures: list[str]
    actual_output: dict[str, Any]
    expected_output: dict[str, Any]


class GoldenTaskEvaluator:
    """Evaluates golden tasks against AI agent outputs."""

    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks = self._load_tasks()

    def _load_tasks(self) -> dict[str, GoldenTask]:
        """Load all golden task files."""
        tasks = {}
        for json_file in self.tasks_dir.glob("golden_*.json"):
            task = GoldenTask.from_file(json_file)
            tasks[task.id] = task
        return tasks

    def run_task(self, task_id: str, agent_output: dict[str, Any] | None = None) -> EvaluationResult:
        """Run a single golden task evaluation."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self.tasks[task_id]

        # For now, simulate agent output if not provided
        if agent_output is None:
            agent_output = self._simulate_agent_output(task)

        # Evaluate the output
        passed, score, failures = self._evaluate_output(task, agent_output)

        return EvaluationResult(
            task_id=task_id,
            passed=passed,
            score=score,
            failures=failures,
            actual_output=agent_output,
            expected_output=task.expected_output
        )

    def _simulate_agent_output(self, task: GoldenTask) -> dict[str, Any]:
        """Simulate AI agent output for demonstration purposes."""
        # This would be replaced with actual AI agent calls
        if task.id == "golden_0001":
            return {"summary": "Call Alice about meeting; Buy milk"}
        elif task.id == "golden_0002":
            return {
                "action_items": [
                    "John: Research competitor analysis (due: Friday)",
                    "Sarah: Prepare budget presentation",
                    "Follow up on vendor quotes (due: next week)"
                ]
            }
        elif task.id == "golden_0003":
            return {
                "categories": {
                    "projects": ["Ideas for new product features"],
                    "areas": ["Meeting notes from quarterly planning"],
                    "resources": ["Research paper on cognitive load theory"],
                    "archive": ["Tax documents for 2025", "Grocery list for weekend"]
                }
            }
        elif task.id == "golden_0004":
            return {
                "insights": [
                    "Capture: Authentication debugging took longer than expected - investigate root causes",
                    "Organize: Zettelkasten and digital gardens are complementary knowledge management approaches",
                    "Distill: Focus issues during deep work may indicate need for better environment design",
                    "Express: Share debugging patterns and knowledge management learnings with team"
                ]
            }
        elif task.id == "golden_0005":
            return {
                "pattern": "elevated_resting_heart_rate_trend",
                "severity": "concerning",
                "insights": [
                    "Resting heart rate trending upward over 4 days",
                    "Correlates with reduced sleep duration",
                    "May indicate stress or recovery debt accumulation"
                ],
                "recommendations": [
                    "Monitor for additional symptoms",
                    "Consider stress reduction techniques",
                    "Evaluate sleep hygiene improvements"
                ]
            }
        else:
            return {}

    def _evaluate_output(self, task: GoldenTask, actual_output: dict[str, Any]) -> tuple[bool, float, list[str]]:
        """Evaluate actual output against expected output."""
        failures = []
        score = 1.0

        # Basic structure check
        if not isinstance(actual_output, dict):
            failures.append("output_not_dict")
            return False, 0.0, failures

        # Task-specific evaluation logic
        if task.id == "golden_0001":
            expected_summary = task.expected_output.get("summary", "")
            actual_summary = actual_output.get("summary", "")
            if expected_summary not in actual_summary:
                failures.append("missing_core_fact")
                score -= 0.5

        elif task.id.startswith("test_") or task.id == "golden_0001":
            # Generic string matching for test tasks and golden_0001
            expected_summary = task.expected_output.get("summary", "")
            actual_summary = actual_output.get("summary", "")
            if expected_summary not in actual_summary:
                failures.append("missing_core_fact")
                score -= 0.5

        elif task.id == "golden_0002":
            expected_items = set(task.expected_output.get("action_items", []))
            actual_items = set(actual_output.get("action_items", []))
            missing = expected_items - actual_items
            if missing:
                failures.append("missing_action_item")
                score -= 0.3 * len(missing)

        elif task.id == "golden_0003":
            # Check categorization accuracy
            expected_cats = task.expected_output.get("categories", {})
            actual_cats = actual_output.get("categories", {})
            for category, items in expected_cats.items():
                actual_items = actual_cats.get(category, [])
                missing = set(items) - set(actual_items)
                if missing:
                    failures.append(f"wrong_category_{category}")
                    score -= 0.2

        elif task.id == "golden_0004":
            # Check CODE methodology coverage
            actual_insights = actual_output.get("insights", [])
            code_phases = ["Capture:", "Organize:", "Distill:", "Express:"]
            covered_phases = sum(1 for phase in code_phases if any(phase in insight for insight in actual_insights))
            if covered_phases < len(code_phases):
                failures.append("missing_code_phase")
                score -= 0.25 * (len(code_phases) - covered_phases)

        elif task.id == "golden_0005":
            # Check pattern detection
            if actual_output.get("pattern") != task.expected_output.get("pattern"):
                failures.append("missed_pattern")
                score -= 0.4
            if actual_output.get("severity") != task.expected_output.get("severity"):
                failures.append("incorrect_severity")
                score -= 0.2

        # Check failure conditions
        for condition in task.failure_conditions:
            if condition in failures:
                score = max(0.0, score - 0.2)

        passed = score >= 0.7 and not failures
        return passed, max(0.0, score), failures

    def run_all_tasks(self, verbose: bool = False) -> list[EvaluationResult]:
        """Run all available golden tasks."""
        results = []
        for task_id in sorted(self.tasks.keys()):
            result = self.run_task(task_id)
            results.append(result)
            if verbose:
                print(f"Task {task_id}: {'PASS' if result.passed else 'FAIL'} (Score: {result.score:.2f})")
                if result.failures:
                    print(f"  Failures: {', '.join(result.failures)}")
        return results

    def generate_report(self, results: list[EvaluationResult]) -> str:
        """Generate a comprehensive evaluation report."""
        total_tasks = len(results)
        passed_tasks = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / total_tasks if total_tasks > 0 else 0

        report = f"""
# NUREALCORTEXLINK Golden Task Evaluation Report

## Summary
- **Total Tasks**: {total_tasks}
- **Passed Tasks**: {passed_tasks}
- **Pass Rate**: {passed_tasks/total_tasks*100:.1f}%
- **Average Score**: {avg_score:.2f}

## Task Results
"""

        for result in results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            report += f"### {result.task_id}: {self.tasks[result.task_id].name}\n"
            report += f"**Status**: {status} (Score: {result.score:.2f})\n"
            if result.failures:
                report += f"**Failures**: {', '.join(result.failures)}\n"
            report += "\n"

        return report


def main():
    parser = argparse.ArgumentParser(description="NUREALCORTEXLINK Golden Task Evaluator")
    parser.add_argument("--task-id", help="Run specific task ID")
    parser.add_argument("--all", action="store_true", help="Run all tasks")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--report", action="store_true", help="Generate detailed report")

    args = parser.parse_args()

    # Find tasks directory
    script_dir = Path(__file__).parent
    tasks_dir = script_dir / "evaluation" / "golden_tasks"

    if not tasks_dir.exists():
        print(f"Error: Golden tasks directory not found at {tasks_dir}")
        sys.exit(1)

    evaluator = GoldenTaskEvaluator(tasks_dir)

    if args.task_id:
        try:
            result = evaluator.run_task(args.task_id)
            print(f"Task {args.task_id}: {'PASS' if result.passed else 'FAIL'} (Score: {result.score:.2f})")
            if result.failures:
                print(f"Failures: {', '.join(result.failures)}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif args.all or args.report:
        results = evaluator.run_all_tasks(verbose=args.verbose)

        if args.report:
            report = evaluator.generate_report(results)
            report_file = script_dir / "evaluation_report.md"
            report_file.write_text(report, encoding='utf-8')
            print(f"Report generated: {report_file}")

        # Exit with error code if any task failed
        if not all(r.passed for r in results):
            sys.exit(1)

    else:
        print("Available tasks:")
        for task_id, task in evaluator.tasks.items():
            print(f"  {task_id}: {task.name}")
        print("\nUse --all to run all tasks, or --task-id TASK_ID for specific task")


if __name__ == "__main__":
    main()
