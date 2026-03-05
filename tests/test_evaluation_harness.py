"""Tests for NUREALCORTEXLINK Golden Task Evaluation Harness."""

import pytest
import json
from pathlib import Path
from evaluation_harness import GoldenTaskEvaluator, GoldenTask, EvaluationResult


class TestGoldenTaskEvaluator:
    """Test the golden task evaluation system."""

    @pytest.fixture
    def evaluator(self, tmp_path):
        """Create a test evaluator with sample tasks."""
        # Create test golden task files
        tasks_dir = tmp_path / "golden_tasks"
        tasks_dir.mkdir()

        # Create a simple test task
        task_data = {
            "id": "test_0001",
            "name": "Test summarization",
            "input": {
                "events": [
                    {"id": "e1", "text": "Task 1"},
                    {"id": "e2", "text": "Task 2"}
                ]
            },
            "expected": {
                "summary": "Task 1; Task 2"
            },
            "failure_conditions": ["missing_core_fact"]
        }

        task_file = tasks_dir / "golden_test_0001.json"
        task_file.write_text(json.dumps(task_data), encoding='utf-8')

        return GoldenTaskEvaluator(tasks_dir)

    def test_load_tasks(self, evaluator):
        """Test that tasks are loaded correctly."""
        assert len(evaluator.tasks) == 1
        assert "test_0001" in evaluator.tasks
        task = evaluator.tasks["test_0001"]
        assert task.name == "Test summarization"
        assert len(task.input_data["events"]) == 2

    def test_run_task_success(self, evaluator):
        """Test successful task execution."""
        # Mock the agent output to return expected result
        result = evaluator.run_task("test_0001", {"summary": "Task 1; Task 2"})
        assert result.passed is True
        assert result.score == 1.0
        assert result.failures == []
        assert result.task_id == "test_0001"

    def test_run_task_failure(self, evaluator):
        """Test task execution with incorrect output."""
        result = evaluator.run_task("test_0001", {"summary": "Completely wrong output"})
        assert result.passed is False
        assert result.score < 1.0
        assert len(result.failures) > 0

    def test_run_nonexistent_task(self, evaluator):
        """Test error handling for nonexistent tasks."""
        with pytest.raises(ValueError, match="Task nonexistent not found"):
            evaluator.run_task("nonexistent")

    def test_generate_report(self, evaluator):
        """Test report generation."""
        results = [evaluator.run_task("test_0001", {"summary": "Task 1; Task 2"})]
        report = evaluator.generate_report(results)

        assert "# NUREALCORTEXLINK Golden Task Evaluation Report" in report
        assert "**Total Tasks**: 1" in report
        assert "**Passed Tasks**: 1" in report
        assert "**Pass Rate**: 100.0%" in report
        assert "test_0001: Test summarization" in report


class TestGoldenTask:
    """Test GoldenTask data structure."""

    def test_from_file(self, tmp_path):
        """Test loading task from JSON file."""
        task_data = {
            "id": "test_0001",
            "name": "Test task",
            "input": {"events": []},
            "expected": {"result": "value"},
            "failure_conditions": ["test_failure"]
        }

        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task_data), encoding='utf-8')

        task = GoldenTask.from_file(task_file)
        assert task.id == "test_0001"
        assert task.name == "Test task"
        assert task.expected_output == {"result": "value"}
        assert task.failure_conditions == ["test_failure"]


class TestEvaluationResult:
    """Test EvaluationResult data structure."""

    def test_result_creation(self):
        """Test creating evaluation results."""
        result = EvaluationResult(
            task_id="test_0001",
            passed=True,
            score=0.95,
            failures=["minor_issue"],
            actual_output={"result": "actual"},
            expected_output={"result": "expected"}
        )

        assert result.task_id == "test_0001"
        assert result.passed is True
        assert result.score == 0.95
        assert result.failures == ["minor_issue"]
        assert result.actual_output == {"result": "actual"}
        assert result.expected_output == {"result": "expected"}