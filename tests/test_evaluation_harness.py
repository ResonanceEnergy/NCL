"""Tests for NUREALCORTEXLINK Golden Task Evaluation Harness."""

import json

import pytest

from evaluation_harness import EvaluationResult, GoldenTask, GoldenTaskEvaluator


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


# ── _simulate_agent_output ─────────────────────────────────


class TestSimulateAgentOutput:

    @pytest.fixture
    def evaluator(self, tmp_path):
        """Evaluator with golden tasks for multiple IDs."""
        tasks_dir = tmp_path / "golden_tasks"
        tasks_dir.mkdir()
        for i in range(1, 6):
            tid = f"golden_{i:04d}"
            data = {
                "id": tid,
                "name": f"Task {i}",
                "input": {"events": []},
                "expected": {},
                "failure_conditions": [],
            }
            (tasks_dir / f"golden_{i:04d}.json").write_text(json.dumps(data))
        return GoldenTaskEvaluator(tasks_dir)

    def test_golden_0001_returns_summary(self, evaluator):
        task = evaluator.tasks["golden_0001"]
        out = evaluator._simulate_agent_output(task)
        assert "summary" in out

    def test_golden_0002_returns_action_items(self, evaluator):
        task = evaluator.tasks["golden_0002"]
        out = evaluator._simulate_agent_output(task)
        assert isinstance(out.get("action_items"), list)

    def test_golden_0003_returns_categories(self, evaluator):
        task = evaluator.tasks["golden_0003"]
        out = evaluator._simulate_agent_output(task)
        assert isinstance(out.get("categories"), dict)

    def test_golden_0004_returns_insights(self, evaluator):
        task = evaluator.tasks["golden_0004"]
        out = evaluator._simulate_agent_output(task)
        insights = out.get("insights", [])
        assert len(insights) > 0

    def test_golden_0005_returns_pattern(self, evaluator):
        task = evaluator.tasks["golden_0005"]
        out = evaluator._simulate_agent_output(task)
        assert "pattern" in out
        assert "severity" in out

    def test_unknown_task_returns_empty(self, evaluator, tmp_path):
        tasks_dir = tmp_path / "golden_tasks"
        data = {"id": "golden_9999", "name": "Unknown", "input": {}, "expected": {}, "failure_conditions": []}
        (tasks_dir / "golden_9999.json").write_text(json.dumps(data))
        evaluator2 = GoldenTaskEvaluator(tasks_dir)
        task = evaluator2.tasks["golden_9999"]
        assert evaluator2._simulate_agent_output(task) == {}


# ── _evaluate_output task-specific scoring ─────────────────


class TestEvaluateOutput:

    def _make_task(self, tid, expected):
        return GoldenTask(
            id=tid,
            name=f"Task {tid}",
            input_data={},
            expected_output=expected,
            failure_conditions=["missing_core_fact"],
        )

    def test_non_dict_output_fails(self):
        task = self._make_task("golden_0001", {"summary": "test"})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        passed, score, failures = evaluator._evaluate_output(task, "not a dict")
        assert passed is False
        assert score == 0.0
        assert "output_not_dict" in failures

    def test_golden_0001_exact_match(self):
        task = self._make_task("golden_0001", {"summary": "Call Alice"})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        passed, score, _failures = evaluator._evaluate_output(task, {"summary": "Call Alice about meeting"})
        assert passed is True
        assert score == 1.0

    def test_golden_0001_missing_fact(self):
        task = self._make_task("golden_0001", {"summary": "Call Alice"})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        _passed, _score, failures = evaluator._evaluate_output(task, {"summary": "Buy milk"})
        assert _passed is False
        assert "missing_core_fact" in failures

    def test_golden_0002_all_items_present(self):
        items = ["item1", "item2"]
        task = self._make_task("golden_0002", {"action_items": items})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        passed, score, _failures = evaluator._evaluate_output(task, {"action_items": items})
        assert passed is True
        assert score == 1.0

    def test_golden_0002_missing_items(self):
        task = self._make_task("golden_0002", {"action_items": ["a", "b", "c"]})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        _passed, score, failures = evaluator._evaluate_output(task, {"action_items": ["a"]})
        assert "missing_action_item" in failures
        assert score < 1.0

    def test_golden_0004_all_code_phases(self):
        task = self._make_task("golden_0004", {})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        insights = [
            "Capture: note this",
            "Organize: sort that",
            "Distill: key insight",
            "Express: share findings",
        ]
        passed, score, _failures = evaluator._evaluate_output(task, {"insights": insights})
        assert passed is True
        assert score == 1.0

    def test_golden_0004_missing_phase(self):
        task = self._make_task("golden_0004", {})
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        _passed, _score, failures = evaluator._evaluate_output(task, {"insights": ["Capture: only one"]})
        assert "missing_code_phase" in failures

    def test_golden_0005_correct_pattern(self):
        expected = {"pattern": "elevated_hr", "severity": "concerning"}
        task = self._make_task("golden_0005", expected)
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        passed, _score, _failures = evaluator._evaluate_output(task, {"pattern": "elevated_hr", "severity": "concerning"})
        assert passed is True

    def test_golden_0005_wrong_pattern(self):
        expected = {"pattern": "elevated_hr", "severity": "concerning"}
        task = self._make_task("golden_0005", expected)
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        _passed, _score, failures = evaluator._evaluate_output(task, {"pattern": "wrong", "severity": "concerning"})
        assert "missed_pattern" in failures

    def test_golden_0005_wrong_severity(self):
        expected = {"pattern": "elevated_hr", "severity": "concerning"}
        task = self._make_task("golden_0005", expected)
        evaluator = GoldenTaskEvaluator.__new__(GoldenTaskEvaluator)
        _passed, _score, failures = evaluator._evaluate_output(task, {"pattern": "elevated_hr", "severity": "mild"})
        assert "incorrect_severity" in failures
