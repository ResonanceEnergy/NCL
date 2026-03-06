#!/usr/bin/env python3
"""
Tests for NCL Relay Server — auth, rate limiting, event processing,
payload size enforcement, and TLS support.
"""
import http.client
import json
import os
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / 'ncl_agency_runtime' / 'runtime'))

from ncl_agency_runtime.runtime.relay_server import (
    MAX_REQUEST_BYTES,
    AuthManager,
    Handler,
    RateLimiter,
    load_config,
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
        ok, _reason = am.authenticate({"X-API-Key": "mykey"})
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


# ── Integration Tests (live HTTP server) ─────────────────────

def _start_test_server(auth_required=False, api_keys=None, events_per_minute=60, api_calls_per_minute=30, tmp_path=None):
    """Spin up a real HTTPServer on a free port for integration tests."""
    cfg = {
        "event_log_dir": str(tmp_path / "events"),
        "quarantine_dir": str(tmp_path / "quarantine"),
        "relay": {"path": "/event"},
    }
    rate_limiter = RateLimiter(events_per_minute=events_per_minute, api_calls_per_minute=api_calls_per_minute)
    auth = AuthManager(keys=api_keys or [], required=auth_required)
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.cfg = cfg  # type: ignore[attr-defined]
    httpd.rate_limiter = rate_limiter  # type: ignore[attr-defined]
    httpd.auth = auth  # type: ignore[attr-defined]
    httpd.seen_event_ids = set()  # type: ignore[attr-defined]
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def _post_event(port, event, headers=None):
    """POST JSON to the relay and return (status, body_dict)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = json.dumps(event).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn.request("POST", "/event", body=body, headers=hdrs)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    status = resp.status
    conn.close()
    return status, data


def _get(port, path, headers=None):
    """GET from the relay and return (status, body_dict)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    status = resp.status
    conn.close()
    return status, data


class TestRelayAuthEnforcement:
    """Integration tests: auth is enforced on POST and GET."""

    def test_post_rejected_without_key(self, tmp_path):
        httpd, port = _start_test_server(auth_required=True, api_keys=["secret"], tmp_path=tmp_path)
        try:
            status, body = _post_event(port, make_valid_event())
            assert status == 401
            assert body["error"] == "unauthorized"
        finally:
            httpd.shutdown()

    def test_post_accepted_with_bearer(self, tmp_path):
        httpd, port = _start_test_server(auth_required=True, api_keys=["secret"], tmp_path=tmp_path)
        try:
            status, body = _post_event(port, make_valid_event(), {"Authorization": "Bearer secret"})
            assert status == 200
            assert body["ok"] is True
        finally:
            httpd.shutdown()

    def test_post_accepted_with_x_api_key(self, tmp_path):
        httpd, port = _start_test_server(auth_required=True, api_keys=["mykey"], tmp_path=tmp_path)
        try:
            status, body = _post_event(port, make_valid_event(), {"X-API-Key": "mykey"})
            assert status == 200
            assert body["ok"] is True
        finally:
            httpd.shutdown()

    def test_get_health_rejected_without_key(self, tmp_path):
        httpd, port = _start_test_server(auth_required=True, api_keys=["secret"], tmp_path=tmp_path)
        try:
            status, _body = _get(port, "/health")
            assert status == 401
        finally:
            httpd.shutdown()

    def test_get_health_accepted_with_key(self, tmp_path):
        httpd, port = _start_test_server(auth_required=True, api_keys=["secret"], tmp_path=tmp_path)
        try:
            status, body = _get(port, "/health", {"Authorization": "Bearer secret"})
            assert status == 200
            assert body["status"] == "healthy"
        finally:
            httpd.shutdown()


class TestRelayRateLimiting:
    """Integration tests: rate limiter returns 429 when exhausted."""

    def test_post_rate_limited(self, tmp_path):
        httpd, port = _start_test_server(events_per_minute=2, tmp_path=tmp_path)
        try:
            # First two should succeed
            for _ in range(2):
                status, _ = _post_event(port, make_valid_event())
                assert status == 200
            # Third should be rate-limited
            status, body = _post_event(port, make_valid_event())
            assert status == 429
            assert body["error"] == "rate_limited"
        finally:
            httpd.shutdown()

    def test_get_rate_limited(self, tmp_path):
        httpd, port = _start_test_server(api_calls_per_minute=2, tmp_path=tmp_path)
        try:
            for _ in range(2):
                status, _ = _get(port, "/health")
                assert status == 200
            status, _body = _get(port, "/health")
            assert status == 429
        finally:
            httpd.shutdown()


class TestRelayPayloadSize:
    """Integration tests: oversized payloads are rejected."""

    def test_oversized_payload_rejected(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            # Send a Content-Length that exceeds the limit but only send a small body
            # The server checks Content-Length before reading, so it responds 413
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/event", body=b"{}", headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_REQUEST_BYTES + 1),
            })
            resp = conn.getresponse()
            assert resp.status == 413
            data = json.loads(resp.read().decode("utf-8"))
            assert data["error"] == "payload_too_large"
            conn.close()
        finally:
            httpd.shutdown()

    def test_large_but_within_limit_accepted(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            event = make_valid_event()
            # Stay under the limit
            event["payload"]["data"] = "X" * 1000
            status, body = _post_event(port, event)
            assert status == 200
            assert body["ok"] is True
        finally:
            httpd.shutdown()


class TestRelayE2E:
    """End-to-end tests: event flow, quarantine, 404."""

    def test_valid_event_stored(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            status, body = _post_event(port, make_valid_event())
            assert status == 200
            assert body["ok"] is True
            assert "stored" in body
        finally:
            httpd.shutdown()

    def test_bad_json_returns_400(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = b"not valid json {{"
            conn.request("POST", "/event", body=body, headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            })
            resp = conn.getresponse()
            assert resp.status == 400
            data = json.loads(resp.read().decode("utf-8"))
            assert data["error"] == "bad_json"
            conn.close()
        finally:
            httpd.shutdown()

    def test_wrong_path_returns_404(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            status, body = _post_event(port, make_valid_event())
            # First request succeeds — verifies server is running
            assert status == 200
            # Now try wrong path
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body_bytes = json.dumps(make_valid_event()).encode("utf-8")
            conn.request("POST", "/wrong", body=body_bytes, headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body_bytes)),
            })
            resp = conn.getresponse()
            assert resp.status == 404
            conn.close()
        finally:
            httpd.shutdown()

    def test_invalid_event_quarantined(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            # Missing required fields
            bad_event = {"payload": "missing stuff"}
            status, body = _post_event(port, bad_event)
            assert status == 422
            assert "quarantined" in body
        finally:
            httpd.shutdown()

    def test_health_endpoint(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            status, body = _get(port, "/health")
            assert status == 200
            assert body["status"] == "healthy"
            assert "timestamp" in body
        finally:
            httpd.shutdown()

    def test_get_unknown_path_returns_404(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            status, _body = _get(port, "/nonexistent")
            assert status == 404
        finally:
            httpd.shutdown()


class TestMaxRequestBytesConstant:
    """Verify the constant is sensible."""

    def test_max_bytes_is_one_mib(self):
        assert MAX_REQUEST_BYTES == 1_048_576


# ── Batch Endpoint Tests ─────────────────────────────────────

class TestRelayBatchEndpoint:
    """Integration tests for POST /event/batch."""

    def test_batch_stores_multiple_events(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            events = [make_valid_event() for _ in range(3)]
            for i, e in enumerate(events):
                e["event_id"] = f"batch-{i}"
            batch = {"events": events}
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps(batch).encode("utf-8")
            conn.request("POST", "/event/batch", body=body, headers={
                "Content-Type": "application/json", "Content-Length": str(len(body))
            })
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["stored"] == 3
            assert data["total"] == 3
            conn.close()
        finally:
            httpd.shutdown()

    def test_batch_partial_valid(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            events = [make_valid_event(), {"payload": "invalid"}]
            events[0]["event_id"] = "partial-0"
            batch = {"events": events}
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps(batch).encode("utf-8")
            conn.request("POST", "/event/batch", body=body, headers={
                "Content-Type": "application/json", "Content-Length": str(len(body))
            })
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["stored"] == 1
            assert data["total"] == 2
            conn.close()
        finally:
            httpd.shutdown()

    def test_batch_missing_events_key(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps({"data": []}).encode("utf-8")
            conn.request("POST", "/event/batch", body=body, headers={
                "Content-Type": "application/json", "Content-Length": str(len(body))
            })
            resp = conn.getresponse()
            assert resp.status == 400
            conn.close()
        finally:
            httpd.shutdown()

    def test_batch_empty_events(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            batch = {"events": []}
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps(batch).encode("utf-8")
            conn.request("POST", "/event/batch", body=body, headers={
                "Content-Type": "application/json", "Content-Length": str(len(body))
            })
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["stored"] == 0
            assert data["total"] == 0
            conn.close()
        finally:
            httpd.shutdown()


# ── Idempotency Tests ────────────────────────────────────────

class TestRelayIdempotency:
    """Integration tests for event_id deduplication."""

    def test_duplicate_event_id_not_stored_twice(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            event = make_valid_event()
            event["event_id"] = "dedup-001"
            # First post
            status1, body1 = _post_event(port, event)
            assert status1 == 200
            assert body1["ok"] is True
            assert "stored" in body1
            # Second post with same event_id
            status2, body2 = _post_event(port, event)
            assert status2 == 200
            assert body2["status"] == "duplicate"
        finally:
            httpd.shutdown()

    def test_different_event_ids_both_stored(self, tmp_path):
        httpd, port = _start_test_server(tmp_path=tmp_path)
        try:
            e1 = make_valid_event()
            e1["event_id"] = "unique-001"
            e2 = make_valid_event()
            e2["event_id"] = "unique-002"
            status1, body1 = _post_event(port, e1)
            status2, body2 = _post_event(port, e2)
            assert status1 == 200
            assert status2 == 200
            assert "stored" in body1
            assert "stored" in body2
        finally:
            httpd.shutdown()
