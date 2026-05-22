"""Tests for runtime.memory.pii_redactor (Loop 10 — PII redactor on-write hook)."""

from __future__ import annotations

import time

import pytest

from runtime.memory.pii_redactor import (
    PIIRedactor,
    RedactionResult,
    _stable_token,
)


# ---------------------------------------------------------------------------
# Core pattern coverage
# ---------------------------------------------------------------------------

def test_detects_email_and_phone_us():
    text = "Call me at 555-123-4567 or email john@example.com"
    r = PIIRedactor.scan(text)
    types = {f["type"] for f in r.findings}
    assert "email" in types, f"expected email finding, got {types}"
    assert "phone_us" in types, f"expected phone_us finding, got {types}"
    assert r.redaction_count >= 2
    assert "john@example.com" not in r.redacted_text
    assert "555-123-4567" not in r.redacted_text


def test_detects_ssn():
    text = "SSN on file: 123-45-6789. Do not share."
    r = PIIRedactor.scan(text)
    assert any(f["type"] == "ssn" for f in r.findings)
    assert "123-45-6789" not in r.redacted_text


def test_detects_anthropic_and_openai_api_keys():
    text = (
        "ANTHROPIC=sk-ant-abc123DEFghi456jklMNO_test "
        "OPENAI=sk-abcdef123456ghijklmnopqr"
    )
    r = PIIRedactor.scan(text)
    types = {f["type"] for f in r.findings}
    # The anthropic key must classify as api_key_anthropic, not as
    # api_key_openai (overlap-resolution test — long/specific wins).
    assert "api_key_anthropic" in types
    assert "api_key_openai" in types
    assert "sk-ant-abc123DEFghi456jklMNO_test" not in r.redacted_text
    assert "sk-abcdef123456ghijklmnopqr" not in r.redacted_text


def test_detects_bearer_token():
    text = "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2"
    r = PIIRedactor.scan(text)
    assert any(f["type"] == "bearer_token" for f in r.findings)
    assert "QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2" not in r.redacted_text


def test_detects_private_address():
    text = "Ship to 1234 Maple Street, suite 200"
    r = PIIRedactor.scan(text)
    assert any(f["type"] == "private_address" for f in r.findings)


# ---------------------------------------------------------------------------
# Allowlist — infrastructure must NOT be flagged
# ---------------------------------------------------------------------------

def test_allowlist_tailscale_and_localhost():
    text = (
        "Brain at 100.72.223.123:8800, dev at 127.0.0.1, "
        "but customer at 73.42.18.5"
    )
    r = PIIRedactor.scan(text)
    ipv4_findings = [f for f in r.findings if f["type"] == "ipv4"]
    assert len(ipv4_findings) == 1, (
        f"expected 1 non-allowlisted ipv4, got {[f['original'] for f in ipv4_findings]}"
    )
    assert ipv4_findings[0]["original"] == "73.42.18.5"
    # Allowlisted IPs must appear verbatim in the output
    assert "100.72.223.123" in r.redacted_text
    assert "127.0.0.1" in r.redacted_text


def test_strict_mode_account_id_off_by_default():
    # An 8-16 char alnum that looks like a broker account ID.
    text = "Account A1B2C3D4E5 has issues"
    default = PIIRedactor.scan(text, strict=False)
    strict = PIIRedactor.scan(text, strict=True)
    assert all(f["type"] != "account_id_numeric" for f in default.findings)
    assert any(f["type"] == "account_id_numeric" for f in strict.findings)


# ---------------------------------------------------------------------------
# Stable tokens / idempotency
# ---------------------------------------------------------------------------

def test_stable_token_is_deterministic():
    t1 = _stable_token("email", "foo@bar.com")
    t2 = _stable_token("email", "foo@bar.com")
    assert t1 == t2
    assert t1.startswith("[REDACTED:email:")
    assert t1.endswith("]")
    assert len(t1.split(":")[-1].rstrip("]")) == 8  # sha8 segment


def test_same_email_gets_same_token_across_calls():
    text_a = "Email: alice@example.com"
    text_b = "Forward to alice@example.com please"
    ra = PIIRedactor.scan(text_a)
    rb = PIIRedactor.scan(text_b)
    token_a = ra.findings[0]["replaced_with"]
    token_b = rb.findings[0]["replaced_with"]
    assert token_a == token_b


def test_idempotent_double_redaction():
    """Running redact() twice yields the same output (token has no PII)."""
    text = "Reach me at jane@example.com today"
    once = PIIRedactor.redact(text)
    twice = PIIRedactor.redact(once)
    assert once == twice
    assert PIIRedactor.is_clean(once) is True


def test_is_clean_truthy_for_safe_text():
    assert PIIRedactor.is_clean("Routine memory unit with no PII whatsoever.") is True


def test_is_clean_false_for_email():
    assert PIIRedactor.is_clean("ping me: x@y.io") is False


def test_empty_text_safe():
    r = PIIRedactor.scan("")
    assert isinstance(r, RedactionResult)
    assert r.redaction_count == 0
    assert r.redacted_text == ""


# ---------------------------------------------------------------------------
# Performance — must stay under the budget
# ---------------------------------------------------------------------------

def test_perf_typical_memory_unit_under_5ms():
    """A ~2 KB unit (well above the median) must scan in well under 5 ms."""
    text = (
        "Council brief 2026-05-21: NATRIX directive to accelerate Brain hardening. "
        "Mention foo@bar.com, broker at 100.72.223.123, customer ping at 73.42.18.5. "
    ) * 8  # ~ 2 KB
    # Warm the regex cache.
    PIIRedactor.scan(text)
    n = 50
    start = time.perf_counter()
    for _ in range(n):
        PIIRedactor.scan(text)
    elapsed_ms = (time.perf_counter() - start) * 1000 / n
    assert elapsed_ms < 5.0, f"scan took {elapsed_ms:.3f}ms per call (budget 5ms)"


def test_perf_single_scan_under_1ms_target():
    """Soft target: single short scan under ~1 ms after warmup."""
    text = "Call 555-123-4567 or email john@example.com"
    PIIRedactor.scan(text)
    n = 200
    start = time.perf_counter()
    for _ in range(n):
        PIIRedactor.scan(text)
    elapsed_ms = (time.perf_counter() - start) * 1000 / n
    # 1ms is the stretch target; assert a generous ceiling so CI is not
    # flaky on slow runners but still catches catastrophic regressions.
    assert elapsed_ms < 3.0, f"short scan {elapsed_ms:.3f}ms per call (target ~1ms)"


# ---------------------------------------------------------------------------
# Audit dict — must never leak the raw value
# ---------------------------------------------------------------------------

def test_audit_dict_omits_raw_values():
    r = PIIRedactor.scan("email alice@example.com, ssn 123-45-6789")
    audit = r.to_audit_dict()
    serialized = repr(audit)
    assert "alice@example.com" not in serialized
    assert "123-45-6789" not in serialized
    assert audit["redaction_count"] == 2
    assert "email" in audit["types_found"]
    assert "ssn" in audit["types_found"]
