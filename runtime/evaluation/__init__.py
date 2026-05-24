"""Golden Task Suite v1 — NCL brain pipeline evaluation framework."""

from .ci_gate import main as ci_gate_main
from .golden_tasks import get_golden_tasks
from .models import (
    GoldenTask,
    SuiteResult,
    TaskCategory,
    TaskDifficulty,
    TaskResult,
)
from .runner import GoldenTaskRunner


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
