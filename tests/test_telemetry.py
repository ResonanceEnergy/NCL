"""Tests for NCL telemetry system."""
import tempfile
from pathlib import Path

import pytest

from runtime.telemetry.schema import (
    RedactionRule,
    TelemetryRecord,
    TelemetryLevel,
    TelemetryCategory,
)


def test_redaction_email():
    """Test email redaction."""
    text = "Contact user@example.com for support"
    redacted = RedactionRule.redact(text)

    assert "user@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_redaction_phone():
    """Test phone number redaction."""
    text = "Call 555-123-4567 or 555.987.6543"
    redacted = RedactionRule.redact(text)

    assert "555-123-4567" not in redacted
    assert "555.987.6543" not in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_redaction_api_key():
    """Test API key redaction."""
    text = "Use key sk-abcdefg1234567890xyzabc for auth"
    redacted = RedactionRule.redact(text)

    assert "sk-abcdefg1234567890xyzabc" not in redacted
    assert "[REDACTED_KEY]" in redacted


def test_redaction_ip():
    """Test IP address redaction."""
    text = "Server at 192.168.1.100 is online"
    redacted = RedactionRule.redact(text)

    assert "192.168.1.100" not in redacted
    assert "[REDACTED_IP]" in redacted


def test_redaction_nested_dict():
    """Test recursive dict redaction."""
    data = {
        "user_email": "user@example.com",
        "metadata": {
            "phone": "555-123-4567",
            "config": {
                "api_key": "sk-abc123def456ghi789jkl012"
            }
        },
        "ips": ["192.168.1.1", "10.0.0.1"]
    }

    redacted = RedactionRule.redact_dict(data)

    assert "[REDACTED_EMAIL]" in redacted["user_email"]
    assert "[REDACTED_PHONE]" in redacted["metadata"]["phone"]
    assert "[REDACTED_KEY]" in redacted["metadata"]["config"]["api_key"]
    # IPs in list should also be redacted
    assert all("[REDACTED_IP]" in ip for ip in redacted["ips"])


def test_telemetry_record_creation():
    """Test creating a telemetry record."""
    record = TelemetryRecord(
        category=TelemetryCategory.PUMP,
        workflow="pump_intake",
        action="received",
        duration_ms=123.45,
        success=True,
    )

    assert record.record_id is not None
    assert record.category == TelemetryCategory.PUMP
    assert record.workflow == "pump_intake"
    assert record.action == "received"
    assert record.duration_ms == 123.45
    assert record.success is True
    assert record.timestamp is not None


def test_record_redacted_method():
    """Test that record can be redacted."""
    record = TelemetryRecord(
        category=TelemetryCategory.PUMP,
        workflow="pump_intake",
        action="received",
        payload={
            "user_email": "test@example.com",
            "ip_address": "192.168.1.1"
        }
    )

    redacted_payload = RedactionRule.redact_dict(record.payload or {})

    assert "[REDACTED_EMAIL]" in redacted_payload["user_email"]
    assert "[REDACTED_IP]" in redacted_payload["ip_address"]


def test_telemetry_levels():
    """Test telemetry level enum values."""
    assert TelemetryLevel.OFF == "off"
    assert TelemetryLevel.MINIMAL == "minimal"
    assert TelemetryLevel.STANDARD == "standard"
    assert TelemetryLevel.VERBOSE == "verbose"


def test_workflow_telemetry_model():
    """Test creating various telemetry records for different workflows."""
    workflows = [
        ("pump_intake", "received"),
        ("council_spawn", "started"),
        ("mandate_dispatch", "executed"),
        ("memory_consolidate", "completed"),
    ]

    for workflow, action in workflows:
        record = TelemetryRecord(
            category=TelemetryCategory.PUMP,
            workflow=workflow,
            action=action,
            duration_ms=50.0,
            success=True,
        )

        assert record.workflow == workflow
        assert record.action == action
        assert record.success is True


def test_hash_identifier():
    """Test identifier hashing for correlation."""
    value1 = "user-123"
    value2 = "user-123"
    value3 = "user-456"

    hash1 = RedactionRule.hash_identifier(value1)
    hash2 = RedactionRule.hash_identifier(value2)
    hash3 = RedactionRule.hash_identifier(value3)

    # Same input should produce same hash
    assert hash1 == hash2
    # Different input should produce different hash
    assert hash1 != hash3
    # Hash should be 16 characters
    assert len(hash1) == 16


def test_telemetry_record_with_counters_and_gauges():
    """Test telemetry record with metrics."""
    record = TelemetryRecord(
        category=TelemetryCategory.COUNCIL,
        workflow="council_run",
        action="completed",
        counters={"agents_run": 3, "items_processed": 42},
        gauges={"avg_confidence": 0.87, "consensus_score": 92.5}
    )

    assert record.counters == {"agents_run": 3, "items_processed": 42}
    assert record.gauges == {"avg_confidence": 0.87, "consensus_score": 92.5}
