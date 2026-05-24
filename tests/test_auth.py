"""
Brain Endpoint Authentication Tests — Strike Point Token Verification

Tests authentication for all NCL brain endpoints.
Covers:
- /pump endpoint requires valid bearer token
- /council/spawn endpoint requires valid bearer token
- /mandates endpoints require valid bearer token
- /health endpoint is public (no auth required)

Run:
    pytest tests/test_auth.py -v
    pytest tests/test_auth.py -v --asyncio-mode=auto
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

# Import the FastAPI app from routes module
from runtime.api import routes as routes_module
from runtime.api.routes import app


@pytest.fixture(autouse=True)
def _brain_and_token_stub(monkeypatch):
    """Auto-applied: stub brain + STRIKE_TOKEN so routes resolve without
    booting the real NCLBrain or requiring environment configuration."""
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
    monkeypatch.setattr(routes_module, "STRIKE_TOKEN", "test-strike-token-valid")
    return stub


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# All previously _OBSOLETE markers have been removed.  Tests below are now
# written against the live routes.py API surface (query-param mandates, dict
# body for /pump, etc.).


@pytest.fixture
def valid_token():
    """Return a valid strike auth token for testing."""
    return "test-strike-token-valid"


@pytest.fixture
def invalid_token():
    """Return an invalid strike auth token."""
    return "test-strike-token-invalid"


def test_health_no_auth(test_client):
    """
    Test: GET /health succeeds without authentication.

    The health endpoint should be public and not require authentication.
    This is required for health checks from external systems.
    """
    response = test_client.get("/health")

    # Should succeed regardless of auth
    assert response.status_code == 200

    data = response.json()
    assert "status" in data


def test_pump_requires_auth_missing_header(test_client):
    """
    Test: POST /pump without Authorization header returns 401.

    Missing the Authorization header entirely should result in 401 Unauthorized.
    """
    pump_payload = {
        "prompt_id": "P-001",
        "source": "grok-iphone",
        "intent": "Test intent",
        "context": {},
        "urgency": "normal",
    }

    response = test_client.post("/pump", json=pump_payload)

    # Should fail without auth header
    assert response.status_code == 401
    data = response.json()
    assert "detail" in data
    assert "Missing Authorization header" in data["detail"]


def test_pump_requires_auth_invalid_token(test_client, invalid_token):
    """
    Test: POST /pump with invalid bearer token returns 403.

    An invalid (but present) token should result in 403 Forbidden.
    """
    pump_payload = {
        "prompt_id": "P-001",
        "source": "grok-iphone",
        "intent": "Test intent",
        "context": {},
        "urgency": "normal",
    }

    headers = {"Authorization": f"Bearer {invalid_token}"}

    response = test_client.post("/pump", json=pump_payload, headers=headers)

    # Should fail with invalid token
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data
    assert "Invalid strike token" in data["detail"]


def test_pump_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: POST /pump with valid bearer token passes auth.

    /pump accepts a dict body with at least an 'intent' key.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    pump_payload = {"intent": "Test intent"}
    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.post("/pump", json=pump_payload, headers=headers)

    assert response.status_code != 401, "Should pass auth check (not 401)"
    assert response.status_code != 403, "Should pass auth check (not 403)"
    assert response.status_code in [200, 503]


def test_council_spawn_requires_auth(test_client):
    """
    Test: POST /council/spawn without token returns 401.
    """
    response = test_client.post("/council/spawn", json={"topic": "test"})
    assert response.status_code == 401
    assert "detail" in response.json()


def test_council_spawn_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: POST /council/spawn with valid bearer token passes auth.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)
    headers = {"Authorization": f"Bearer {valid_token}"}
    response = test_client.post("/council/spawn", json={"topic": "test"}, headers=headers)
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 422, 503]


def test_mandates_create_requires_auth(test_client):
    """
    Test: POST /mandates without token returns 401.

    /mandates uses query params — pass them as params, not JSON body.
    """
    response = test_client.post(
        "/mandates",
        params={
            "pillar": "ncc",
            "priority": 5,
            "title": "Test mandate",
            "objective": "Test objective",
            "success_criteria": ["criteria1"],
        },
    )
    assert response.status_code == 401
    assert "detail" in response.json()


def test_mandates_create_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: POST /mandates with valid bearer token passes auth.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)
    headers = {"Authorization": f"Bearer {valid_token}"}
    response = test_client.post(
        "/mandates",
        params={
            "pillar": "ncc",
            "priority": 5,
            "title": "Test mandate",
            "objective": "Test objective",
            "success_criteria": ["criteria1"],
        },
        headers=headers,
    )
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 422, 503]


def test_mandates_list_requires_auth(test_client):
    """
    Test: GET /mandates without token returns 401.
    """
    response = test_client.get("/mandates")
    assert response.status_code == 401
    assert "detail" in response.json()


def test_mandates_list_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: GET /mandates with valid bearer token succeeds (auth-wise).

    Valid token should pass authentication.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.get("/mandates", headers=headers)

    # Should pass auth
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 503]


def test_mandates_get_requires_auth(test_client):
    """
    Test: GET /mandates/{mandate_id} without token returns 401/403.

    Retrieving a specific mandate requires authentication.
    """
    response = test_client.get("/mandates/MND-001")

    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


def test_mandates_get_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: GET /mandates/{mandate_id} with valid token succeeds (auth-wise).

    Valid token should pass authentication.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.get("/mandates/MND-001", headers=headers)

    # Should pass auth (may be 404 if mandate doesn't exist, but not 401/403)
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 404, 503]


def test_memory_query_requires_auth(test_client):
    """
    Test: GET /memory/query without token returns 401/403.

    Memory query endpoint requires authentication.
    """
    response = test_client.get("/memory/query")

    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


def test_memory_query_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: GET /memory/query with valid token succeeds (auth-wise).

    Valid token should pass authentication.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.get("/memory/query", headers=headers)

    # Should pass auth
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 503]


def test_feedback_requires_auth(test_client):
    """
    Test: POST /feedback without token returns 401/403.

    Feedback endpoint requires authentication.
    """
    payload = {
        "report_id": "FB-001",
        "origin": "ncc",
        "content": "Test feedback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    response = test_client.post("/feedback", json=payload)

    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


def test_feedback_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: POST /feedback with valid token succeeds (auth-wise).

    Valid token should pass authentication.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    payload = {
        "report_id": "FB-001",
        "origin": "ncc",
        "content": "Test feedback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.post("/feedback", json=payload, headers=headers)

    # Should pass auth
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 503]


def test_auth_token_format_bearer(test_client, valid_token, monkeypatch):
    """
    Test: Bearer token format is properly parsed.

    The token should be extracted from "Bearer <token>" format.
    /pump accepts a dict body with at least an 'intent' key.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    pump_payload = {"intent": "Test intent"}

    # Valid: "Bearer <token>"
    headers = {"Authorization": f"Bearer {valid_token}"}
    response = test_client.post("/pump", json=pump_payload, headers=headers)
    assert response.status_code in [200, 503], "Should accept 'Bearer <token>' format"

    # Invalid: Missing "Bearer " prefix
    headers = {"Authorization": valid_token}
    response = test_client.post("/pump", json=pump_payload, headers=headers)
    assert response.status_code == 403, "Should reject token without 'Bearer' prefix"

    # Invalid: Wrong prefix
    headers = {"Authorization": f"Basic {valid_token}"}
    response = test_client.post("/pump", json=pump_payload, headers=headers)
    assert response.status_code == 403, "Should reject non-Bearer authorization schemes"


def test_auth_case_sensitivity(test_client, valid_token, monkeypatch):
    """
    Test: Token comparison is case-sensitive.

    Token values are cryptographic and should be compared with constant-time equality.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    pump_payload = {"intent": "Test intent"}

    # Valid token should work
    headers = {"Authorization": f"Bearer {valid_token}"}
    response = test_client.post("/pump", json=pump_payload, headers=headers)
    assert response.status_code in [200, 503]

    # Token with different case should fail
    wrong_case_token = valid_token.upper() if valid_token.islower() else valid_token.lower()
    if wrong_case_token != valid_token:
        headers = {"Authorization": f"Bearer {wrong_case_token}"}
        response = test_client.post("/pump", json=pump_payload, headers=headers)
        assert response.status_code == 403, "Should reject case-variant tokens"


def test_pump_approval_requires_auth(test_client):
    """
    Test: POST /pump/approve/{pump_id} requires authentication.

    Approval endpoint is a critical control point and must require auth.
    """
    response = test_client.post("/pump/approve/P-001")

    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


def test_pump_approval_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: POST /pump/approve/{pump_id} with valid token succeeds (auth-wise).

    Valid token should pass authentication.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.post("/pump/approve/P-001", headers=headers)

    # Should pass auth (may be 404 if pump doesn't exist, but not 401/403)
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 404, 503]


def test_pump_reject_requires_auth(test_client):
    """
    Test: POST /pump/reject/{pump_id} requires authentication.

    Rejection endpoint must require authentication.
    """
    response = test_client.post("/pump/reject/P-001")

    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


def test_pump_reject_valid_auth(test_client, valid_token, monkeypatch):
    """
    Test: POST /pump/reject/{pump_id} with valid token succeeds (auth-wise).

    Valid token should pass authentication.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", valid_token)

    headers = {"Authorization": f"Bearer {valid_token}"}

    response = test_client.post("/pump/reject/P-001", headers=headers)

    # Should pass auth (may be 404 if pump doesn't exist, but not 401/403)
    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code in [200, 404, 503]
