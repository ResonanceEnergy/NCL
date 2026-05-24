"""Golden Task Suite v1 — evaluation models."""

import uuid as _uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskCategory(str, Enum):
    """Task categories aligned with NCL brain pipeline stages."""

    CAPTURE = "capture"  # Input ingestion & parsing
    SUMMARIZE = "summarize"  # Content summarization
    PLAN = "plan"  # Strategy & planning
    RECALL = "recall"  # Memory retrieval
    CLASSIFY = "classify"  # Categorization & routing
    EXTRACT = "extract"  # Structured data extraction
    DEBATE = "debate"  # Council debate quality
    MANDATE = "mandate"  # Mandate generation
    SEARCH = "search"  # Search accuracy
    PIPELINE = "pipeline"  # End-to-end pipeline


class TaskDifficulty(str, Enum):
    """Task difficulty levels."""

    TRIVIAL = "trivial"  # Should always pass
    STANDARD = "standard"  # Normal operation
    EDGE_CASE = "edge_case"  # Boundary conditions
    STRESS = "stress"  # High load / large input


class GoldenTask(BaseModel):
    """A single deterministic evaluation task."""

    task_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str = Field(..., description="Task name")
    category: TaskCategory = Field(..., description="Task category")
    difficulty: TaskDifficulty = Field(
        default=TaskDifficulty.STANDARD, description="Task difficulty"
    )
    description: str = Field(..., description="Task description")

    # Input specification
    input_data: dict[str, Any] = Field(..., description="Structured input for the task")

    # Expected output specification
    expected_output: dict[str, Any] = Field(
        default_factory=dict, description="Expected structured output (for value matching)"
    )
    expected_keys: list[str] = Field(
        default_factory=list, description="Keys that MUST exist in output"
    )
    expected_patterns: list[str] = Field(
        default_factory=list, description="Regex patterns output string values must match"
    )
    expected_type: Optional[str] = Field(
        default=None, description="Expected output type name (e.g., 'dict', 'list', 'str')"
    )

    # Failure conditions
    failure_conditions: list[str] = Field(
        default_factory=list, description="Error messages that constitute failure"
    )
    max_duration_ms: float = Field(
        default=30000, description="Maximum allowed execution duration in milliseconds"
    )

    # Metadata
    tags: list[str] = Field(default_factory=list, description="Task tags")
    version: str = Field(default="1.0", description="Task version")

    model_config = {"use_enum_values": False}


class TaskResult(BaseModel):
    """Result of running a single golden task."""

    task_id: str = Field(..., description="Task ID")
    task_name: str = Field(..., description="Task name")
    passed: bool = Field(..., description="Whether task passed")
    duration_ms: float = Field(..., description="Execution duration in milliseconds")
    actual_output: dict[str, Any] = Field(default_factory=dict, description="Actual output")
    errors: list[str] = Field(default_factory=list, description="Caught errors")
    failure_reasons: list[str] = Field(default_factory=list, description="Reasons for failure")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Result timestamp"
    )

    model_config = {"use_enum_values": False}


class SuiteResult(BaseModel):
    """Result of running the full golden task suite."""

    suite_version: str = Field(default="1.0", description="Suite version")
    total_tasks: int = Field(..., description="Total tasks run")
    passed: int = Field(..., description="Number of passed tasks")
    failed: int = Field(..., description="Number of failed tasks")
    skipped: int = Field(default=0, description="Number of skipped tasks")
    pass_rate: float = Field(..., description="Pass rate as percentage (0-100)")
    total_duration_ms: float = Field(..., description="Total execution time")
    results: list[TaskResult] = Field(..., description="Individual task results")
    regression_detected: bool = Field(default=False, description="Whether regression detected")
    regression_tasks: list[str] = Field(default_factory=list, description="Tasks with regressions")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Suite execution timestamp"
    )

    model_config = {"use_enum_values": False}
