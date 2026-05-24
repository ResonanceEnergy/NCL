"""Privacy-Safe Telemetry Schema v1 — NCL Pipeline Telemetry.

Every telemetry record passes through redaction rules before persistence.
UI toggle defaults to privacy-safe mode. CI lint enforces schema compliance.
"""

import hashlib
import re
import uuid as _uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TelemetryLevel(str, Enum):
    """Telemetry detail level — user toggle."""

    OFF = "off"  # No telemetry collected
    MINIMAL = "minimal"  # Counts + timings only
    STANDARD = "standard"  # + workflow names, status (DEFAULT)
    VERBOSE = "verbose"  # + payloads (development only, never in prod)


class TelemetryCategory(str, Enum):
    """Telemetry event categories."""

    PUMP = "pump"
    COUNCIL = "council"
    MANDATE = "mandate"
    MEMORY = "memory"
    SEARCH = "search"
    LDE = "lde"
    AWAREBOT = "awarebot"
    PREDICTION = "prediction"
    FEEDBACK = "feedback"
    API = "api"
    SYSTEM = "system"


class RedactionRule:
    """Redaction rules for privacy-safe telemetry."""

    # PII patterns to scrub
    EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    PHONE_PATTERN = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
    SSN_PATTERN = re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b")
    API_KEY_PATTERN = re.compile(r"(sk-|xai-|key-|token-)[a-zA-Z0-9_-]{20,}")
    IP_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    BEARER_PATTERN = re.compile(r"Bearer\s+[a-zA-Z0-9_.-]+")

    PATTERNS = [
        ("email", EMAIL_PATTERN, "[REDACTED_EMAIL]"),
        ("phone", PHONE_PATTERN, "[REDACTED_PHONE]"),
        ("ssn", SSN_PATTERN, "[REDACTED_SSN]"),
        ("api_key", API_KEY_PATTERN, "[REDACTED_KEY]"),
        ("ip", IP_PATTERN, "[REDACTED_IP]"),
        ("bearer", BEARER_PATTERN, "[REDACTED_BEARER]"),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        """Apply all redaction rules to text."""
        if not isinstance(text, str):
            return text
        for name, pattern, replacement in cls.PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    @classmethod
    def redact_dict(cls, data: dict) -> dict:
        """Recursively redact all string values in a dict."""
        result = {}
        for k, v in data.items():
            if isinstance(v, str):
                result[k] = cls.redact(v)
            elif isinstance(v, dict):
                result[k] = cls.redact_dict(v)
            elif isinstance(v, list):
                result[k] = [cls.redact(i) if isinstance(i, str) else i for i in v]
            else:
                result[k] = v
        return result

    @classmethod
    def hash_identifier(cls, value: str) -> str:
        """One-way hash for identifiers that need correlation without PII."""
        return hashlib.sha256(value.encode()).hexdigest()[:16]


class TelemetryRecord(BaseModel):
    """Single telemetry record — the atomic unit of NCL telemetry."""

    record_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    category: TelemetryCategory
    workflow: str = Field(..., description="Workflow name (e.g., 'pump_intake', 'council_debate')")
    action: str = Field(..., description="Specific action (e.g., 'started', 'completed', 'failed')")

    # Timing
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: Optional[float] = Field(default=None, description="Operation duration in ms")

    # Context (privacy-safe)
    correlation_id: Optional[str] = Field(default=None, description="Hashed correlation ID")
    session_id: Optional[str] = Field(default=None)

    # Metrics
    counters: dict[str, int] = Field(default_factory=dict, description="Count metrics")
    gauges: dict[str, float] = Field(
        default_factory=dict, description="Gauge metrics (current values)"
    )

    # Status
    success: bool = True
    error_type: Optional[str] = Field(default=None, description="Error class name, not message")

    # Payload (only in VERBOSE mode, always redacted)
    payload: dict[str, Any] = Field(default_factory=dict)

    # Schema
    schema_version: str = "1.0"
    telemetry_level: TelemetryLevel = TelemetryLevel.STANDARD

    @field_validator("workflow", "action")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Ensure workflow and action are non-empty strings."""
        if not v or not isinstance(v, str):
            raise ValueError("workflow and action must be non-empty strings")
        return v.strip()

    def redacted(self) -> "TelemetryRecord":
        """Return a copy with all PII redacted."""
        data = self.model_dump()
        data["payload"] = RedactionRule.redact_dict(data.get("payload", {}))
        if data.get("correlation_id"):
            data["correlation_id"] = RedactionRule.hash_identifier(data["correlation_id"])
        return TelemetryRecord(**data)


class WorkflowTelemetry(BaseModel):
    """Aggregated telemetry for a workflow over a time period."""

    workflow: str
    period_start: datetime
    period_end: datetime
    total_executions: int = 0
    successful: int = 0
    failed: int = 0
    avg_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    error_distribution: dict[str, int] = Field(default_factory=dict)


class TelemetryConfig(BaseModel):
    """User-configurable telemetry settings."""

    level: TelemetryLevel = TelemetryLevel.STANDARD
    enabled: bool = True
    flush_interval_seconds: int = 30
    max_buffer_size: int = 1000
    redaction_enabled: bool = True  # Always True in production
    export_format: str = "ndjson"  # ndjson or json

    @field_validator("flush_interval_seconds", "max_buffer_size")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """Ensure positive integer values."""
        if v <= 0:
            raise ValueError("Value must be positive")
        return v
