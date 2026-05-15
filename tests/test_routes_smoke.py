"""
Smoke tests for runtime.api.routes — public endpoints + critical paths.

Goal: a minimal safety net for the ~150-endpoint FastAPI surface. Covers:
- public endpoints that must always respond (health, services, network)
- auth boundary (401 vs 403) on the highest-value strike-point endpoints
- /pump background-mode contract (the May 2026 fix — auto_flow detaches
  council pipeline and returns immediately with mode="background")

Run:
    pytest tests/test_routes_smoke.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from runtime.api import routes as routes_module
from runtime.api.routes import app
from runtime.ncl_brain.models import PumpPrompt


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def brain_stub(monkeypatch):
    """Minimal async brain stub so routes that need `brain` resolve without
    booting the real NCLBrain (council, memory, paperclip, etc.)."""
    stub = AsyncMock()
    stub.health_check = AsyncMock(
        return_value={
            "status": "healthy",
            "service": "ncl-brain",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_pct": 100.0,
            "active_mandates": 0,
            "mandates_total": 0,
            "pending_approval": 0,
            "council_sessions": 0,
            "memory_units": 0,
            "key_metric": 0,
            "key_metric_label": "active_mandates",
            "paperclip_connected": False,
            "warnings": [],
        }
    )
    stub.receive_pump_prompt = AsyncMock(
        return_value={"pump_id": "P-test", "intent": "stub", "urgency": "normal"}
    )
    monkeypatch.setattr(routes_module, "brain", stub)
    return stub


@pytest.fixture
def valid_token(monkeypatch) -> str:
    tok = "smoke-test-token-001"
    monkeypatch.setattr(routes_module, "STRIKE_TOKEN", tok)
    return tok


# ── Public endpoints ──────────────────────────────────────────────────────


def test_health_returns_200_when_brain_ready(client, brain_stub):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["service"] == "ncl-brain"


def test_health_503_when_brain_missing(client, monkeypatch):
    monkeypatch.setattr(routes_module, "brain", None)
    r = client.get("/health")
    assert r.status_code == 503


def test_services_status_shape(client):
    """`/services/status` proxies localhost checks. It must always return
    a {services, online, total} dict even when targets are down."""
    r = client.get("/services/status")
    assert r.status_code == 200
    body = r.json()
    assert "services" in body and isinstance(body["services"], list)
    assert "online" in body and isinstance(body["online"], int)
    assert "total" in body and body["total"] == len(body["services"])
    for svc in body["services"]:
        assert {"name", "port", "path", "online"} <= set(svc.keys())


def test_network_info_returns_base_url(client):
    r = client.get("/network/info")
    assert r.status_code == 200
    body = r.json()
    assert body["lan_ip"]
    assert body["base_url"].startswith("http://")
    assert body["shortcuts_setup"].startswith("http://")


# ── Auth boundary ─────────────────────────────────────────────────────────


def test_pump_missing_auth_header_is_401(client):
    r = client.post("/pump", json={"prompt": "hi"})
    assert r.status_code == 401
    assert "Missing Authorization header" in r.json()["detail"]


def test_pump_wrong_token_is_403(client, valid_token):
    r = client.post(
        "/pump",
        json={"prompt": "hi"},
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert r.status_code == 403
    assert "Invalid strike token" in r.json()["detail"]


# ── /pump background-mode contract ────────────────────────────────────────


def test_pump_auto_flow_true_returns_background_envelope_immediately(
    client, brain_stub, valid_token
):
    """
    Regression for May 2026 fix: with auto_flow=true (default), /pump must
    schedule council work in the background and return a small envelope
    containing mode="background" + status="accepted". The watcher relies on
    this 200 OK arriving in <1s so it doesn't ReadTimeout-loop.
    """
    payload = {
        "prompt_id": "P-bg-1",
        "source": "test",
        "intent": "background mode contract test",
        "context": {},
        "urgency": "normal",
    }
    r = client.post(
        "/pump",
        json=payload,
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pump_id"] == "P-bg-1"
    assert body["mode"] == "background"
    assert body["status"] == "accepted"


def test_pump_auto_flow_false_returns_brain_result_directly(
    client, brain_stub, valid_token
):
    """When auto_flow=false, /pump must NOT detach — it should await the
    brain call and return its dict verbatim. Used by dashboards that want
    synchronous storage-only semantics without council overhead."""
    payload = {
        "prompt_id": "P-sync-1",
        "source": "test",
        "intent": "synchronous mode test",
        "context": {},
        "urgency": "normal",
    }
    r = client.post(
        "/pump?auto_flow=false",
        json=payload,
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pump_id"] == "P-test"
    assert "mode" not in body
    # brain.receive_pump_prompt called with auto_flow=False
    brain_stub.receive_pump_prompt.assert_awaited()
    call_kwargs = brain_stub.receive_pump_prompt.await_args.kwargs
    assert call_kwargs.get("auto_flow") is False


def test_pump_accepts_simple_dashboard_body(client, brain_stub, valid_token):
    """The simple `{prompt: 'text'}` body shape used by the dashboard must
    be coerced into a PumpPrompt before reaching the brain."""
    r = client.post(
        "/pump?auto_flow=false",
        json={"prompt": "what is 2+2"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert r.status_code == 200
    brain_stub.receive_pump_prompt.assert_awaited()
    sent: PumpPrompt = brain_stub.receive_pump_prompt.await_args.args[0]
    assert sent.source == "command-center-dashboard"
    assert sent.intent.startswith("what is 2+2")
    assert sent.prompt_id.startswith("pump-dash-")


def test_pump_rejects_malformed_body_with_422(client, brain_stub, valid_token):
    """Non-conforming bodies must surface a 422 with a descriptive detail,
    not a 500."""
    r = client.post(
        "/pump",
        json={"prompt_id": 12345},  # source/intent missing, type wrong
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert r.status_code == 422
    assert "Invalid PumpPrompt" in r.json()["detail"]
