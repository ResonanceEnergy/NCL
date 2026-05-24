"""Tests for NCL golden task evaluation suite."""

import tempfile

import pytest

from runtime.evaluation.golden_tasks import get_golden_tasks
from runtime.evaluation.models import (
    GoldenTask,
    SuiteResult,
    TaskCategory,
    TaskDifficulty,
    TaskResult,
)
from runtime.evaluation.runner import GoldenTaskRunner


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_golden_tasks_count_50():
    """Test that we have exactly 50 golden tasks."""
    tasks = get_golden_tasks()

    assert len(tasks) == 50


def test_golden_tasks_all_categories():
    """Test that golden tasks cover all required categories."""
    tasks = get_golden_tasks()

    categories = {task.category for task in tasks}

    required_categories = {
        TaskCategory.CAPTURE,
        TaskCategory.SUMMARIZE,
        TaskCategory.PLAN,
        TaskCategory.RECALL,
        TaskCategory.CLASSIFY,
        TaskCategory.EXTRACT,
        TaskCategory.DEBATE,
        TaskCategory.MANDATE,
        TaskCategory.SEARCH,
        TaskCategory.PIPELINE,
    }

    assert categories == required_categories


def test_golden_tasks_have_inputs():
    """Test that all golden tasks have input data."""
    tasks = get_golden_tasks()

    for task in tasks:
        assert task.input_data is not None
        assert isinstance(task.input_data, dict)
        assert len(task.input_data) > 0


def test_golden_tasks_have_failure_conditions():
    """Test that all golden tasks define failure conditions."""
    tasks = get_golden_tasks()

    for task in tasks:
        assert task.failure_conditions is not None
        assert isinstance(task.failure_conditions, list)
        assert len(task.failure_conditions) > 0


def test_golden_tasks_have_expected_keys():
    """Test that all golden tasks define expected output keys."""
    tasks = get_golden_tasks()

    for task in tasks:
        assert task.expected_keys is not None
        assert isinstance(task.expected_keys, list)
        assert len(task.expected_keys) > 0


def test_golden_tasks_have_expected_patterns():
    """Test that all golden tasks define expected patterns."""
    tasks = get_golden_tasks()

    for task in tasks:
        assert task.expected_patterns is not None
        assert isinstance(task.expected_patterns, list)
        assert len(task.expected_patterns) > 0


def test_golden_task_model():
    """Test creating a golden task."""
    task = GoldenTask(
        name="test_task",
        category=TaskCategory.CAPTURE,
        difficulty=TaskDifficulty.STANDARD,
        description="Test task description",
        input_data={"key": "value"},
        expected_keys=["result"],
        expected_patterns=[r"test"],
        failure_conditions=["Failed"],
        tags=["test"],
    )

    assert task.name == "test_task"
    assert task.category == TaskCategory.CAPTURE
    assert task.difficulty == TaskDifficulty.STANDARD
    assert task.input_data == {"key": "value"}


@pytest.mark.asyncio
async def test_runner_evaluates_task(temp_data_dir):
    """Test that the runner can evaluate a task."""
    runner = GoldenTaskRunner(temp_data_dir)

    task = GoldenTask(
        name="test_evaluate",
        category=TaskCategory.CAPTURE,
        difficulty=TaskDifficulty.TRIVIAL,
        description="Simple test",
        input_data={"action": "test"},
        expected_keys=["action"],
        expected_patterns=[r"test"],
        failure_conditions=["error"],
        tags=["test"],
    )

    result = await runner.run_task(task)

    assert isinstance(result, TaskResult)
    assert result.task_name == "test_evaluate"


@pytest.mark.asyncio
async def test_suite_result_model():
    """Test SuiteResult model."""
    result = SuiteResult(
        suite_version="1.0",
        total_tasks=50,
        passed=45,
        failed=5,
        pass_rate=90.0,
        total_duration_ms=15000.0,
        results=[],
        regression_detected=False,
        regression_tasks=[],
    )

    assert result.suite_version == "1.0"
    assert result.total_tasks == 50
    assert result.passed == 45
    assert result.failed == 5
    assert result.pass_rate == 90.0
    assert result.regression_detected is False


@pytest.mark.asyncio
async def test_runner_run_suite(temp_data_dir):
    """Test running the full golden task suite."""
    runner = GoldenTaskRunner(temp_data_dir)

    # This should run all 50 tasks
    suite_result = await runner.run_suite()

    assert suite_result.total_tasks == 50
    assert len(suite_result.results) == 50
    # Pass rate should be between 0 and 100
    assert 0.0 <= suite_result.pass_rate <= 100.0


def test_task_categories_distribution():
    """Test that task categories are reasonably distributed."""
    tasks = get_golden_tasks()

    category_counts = {}
    for task in tasks:
        category_counts[task.category] = category_counts.get(task.category, 0) + 1

    # Should have tasks in each category
    for category in category_counts.values():
        assert category > 0

    # Total should be 50
    assert sum(category_counts.values()) == 50


def test_task_difficulties_distribution():
    """Test that task difficulties are varied."""
    tasks = get_golden_tasks()

    difficulties = {task.difficulty for task in tasks}

    # Should have multiple difficulty levels
    assert len(difficulties) > 1


def test_task_tags():
    """Test that tasks have meaningful tags."""
    tasks = get_golden_tasks()

    all_tags = set()
    for task in tasks:
        all_tags.update(task.tags or [])

    # Should have a reasonable number of distinct tags
    assert len(all_tags) > 5
