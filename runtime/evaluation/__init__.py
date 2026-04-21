"""Golden Task Suite v1 — NCL brain pipeline evaluation framework."""

from .models import (
    GoldenTask,
    TaskCategory,
    TaskDifficulty,
    TaskResult,
    SuiteResult,
)
from .golden_tasks import get_golden_tasks
from .runner import GoldenTaskRunner
from .ci_gate import main as ci_gate_main

__version__ = "1.0.0"
__all__ = [
    "GoldenTask",
    "TaskCategory",
    "TaskDifficulty",
    "TaskResult",
    "SuiteResult",
    "get_golden_tasks",
    "GoldenTaskRunner",
    "ci_gate_main",
]
