#!/usr/bin/env python3
"""
Tests for NCL Relay Server — auth, rate limiting, event processing.
"""
import json
import sys
import os
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from io import BytesIO

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / 'ncl_agency_runtime' / 'runtime'))

from ncl_agency_runtime.runtime.relay_server import (
    RateLimiter, AuthManager, load_config
)


# ── RateLimiter Tests ────────────────────────────────────────

class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(events_per_minute=5, api_calls_per_minute=3)
        for _ in range(5):
            assert rl.allow_event("127.0.0.1") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(events_per_minute=3, api_calls_per_minute=2)
        for _ in range(3):
            rl.allow_event("127.0.0.1")
        assert rl.allow_event("127.0.0.1") is False

    def test_separate_buckets_per_ip(self):
        rl = RateLimiter(events_per_minute=2, api_calls_per_minute=2)
        rl.allow_event("10.0.0.1")
        rl.allow_event("10.0.0.1")
        assert rl.allow_event("10.0.0.1") is False
        assert rl.allow_event("10.0.0.2") is True  # different IP

    def test_api_rate_limit(self):
        rl = RateLimiter(events_per_minute=100, api_calls_per_minute=2)
        assert rl.allow_api("127.0.0.1") is True
        assert rl.allow_api("127.0.0.1") is True
        assert rl.allow_api("127.0.0.1") is False

    def test_event_and_api_independent(self):
        rl = RateLimiter(events_per_minute=2, api_calls_per_minute=2)
        rl.allow_event("127.0.0.1")
        rl.allow_event("127.0.0.1")
        assert rl.allow_event("127.0.0.1") is False
        assert rl.allow_api("127.0.0.1") is True  # separate bucket


# ── AuthManager Tests ────────────────────────────────────────

class TestAuthManager:
    def test_auth_not_required(self):
        am = AuthManager(required=False)
        ok, reason = am.authenticate({})
        assert ok is True
        assert reason == "auth_not_required"

    def test_auth_required_no_key(self):
        am = AuthManager(keys=["secret123"], required=True)
        ok, reason = am.authenticate({})
        assert ok is False
        assert reason == "missing_credentials"

    def test_auth_bearer_valid(self):
        am = AuthManager(keys=["secret123"], required=True)
        ok, reason = am.authenticate({"Authorization": "Bearer secret123"})
        assert ok is True
        assert reason == "authenticated"

    def test_auth_bearer_invalid(self):
        am = AuthManager(keys=["secret123"], required=True)
        ok, reason = am.authenticate({"Authorization": "Bearer wrongkey"})
        assert ok is False
        assert reason == "invalid_api_key"

    def test_auth_x_api_key(self):
        am = AuthManager(keys=["mykey"], required=True)
        ok, reason = am.authenticate({"X-API-Key": "mykey"})
        assert ok is True

    def test_auth_env_key(self):
        with patch.dict(os.environ, {"NCL_API_KEY": "env_secret"}):
            am = AuthManager(required=True)
            ok, _ = am.authenticate({"Authorization": "Bearer env_secret"})
            assert ok is True


# ── Config Loading Tests ─────────────────────────────────────

class TestLoadConfig:
    def test_load_config_returns_dict(self):
        cfg = load_config()
        assert isinstance(cfg, dict)
        assert "relay" in cfg
        assert "access" in cfg

    def test_config_has_defaults(self):
        cfg = load_config()
        assert cfg["relay"]["path"] == "/event"
        assert "rate_limiting" in cfg["access"]

    def test_config_rate_limits(self):
        cfg = load_config()
        rl = cfg["access"]["rate_limiting"]
        assert rl["events_per_minute"] > 0
        assert rl["api_calls_per_minute"] > 0


# ── Sample Event Payloads ────────────────────────────────────

def make_valid_event():
    return {
        "schema_version": "ncl.event.v1",
        "event_id": "test-001",
        "event_type": "ncl.test.event",
        "occurred_at": "2026-02-18T10:00:00Z",
        "source": {"device": "mac", "origin": "test"},
        "privacy": {"level": "P3"},
        "payload": {"key": "value"}
    }


class TestEventPayloads:
    def test_valid_event_structure(self):
        event = make_valid_event()
        assert "event_id" in event
        assert "event_type" in event
        assert "occurred_at" in event

    def test_event_json_roundtrip(self):
        event = make_valid_event()
        raw = json.dumps(event)
        parsed = json.loads(raw)
        assert parsed == event
