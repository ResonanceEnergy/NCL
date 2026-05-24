"""
Smoke + behavior tests for ``runtime.llm`` (Wave 1 — Agent 06).

Network is fully mocked — these tests never make a real API call. We mock
the shared httpx.AsyncClient by monkey-patching ``_get_http_client`` to
return a stub that records the request body and returns a fake response.

What we verify
--------------
1. Unknown model id raises ``UnknownModelError``.
2. Circuit breaker opens after 5 consecutive failures.
3. Budget gate raises ``BudgetExhausted`` BEFORE the provider call fires.
4. Anthropic Citations documents are passed through in the request body.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import pytest

from runtime.llm import chat
from runtime.llm import client as client_mod
from runtime.llm.errors import (
    BudgetExhausted,
    CircuitOpen,
    UnknownModelError,
)
from runtime.llm.retry import CircuitBreaker


# ── Fakes ────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_body: dict | None = None,
        text: str = "",
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or "fake-error-body"
        self.headers = headers or {}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if 200 <= self.status_code < 300:
            return
        import httpx

        raise httpx.HTTPStatusError(
            f"HTTP {self.status_code}",
            request=httpx.Request("POST", "http://fake"),
            response=httpx.Response(self.status_code),
        )


class _FakeClient:
    """Records every .post() call. Configurable response per instance."""

    is_closed = False

    def __init__(self, response_factory):
        self.calls: list[dict] = []
        self._response_factory = response_factory

    async def post(self, url, *, headers=None, json=None, timeout=None):
        self.calls.append(
            {"url": url, "headers": headers or {}, "json": json or {}, "timeout": timeout}
        )
        return self._response_factory()

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_breakers():
    """Each test gets a clean breaker registry."""
    CircuitBreaker.reset_registry()
    yield
    CircuitBreaker.reset_registry()


@pytest.fixture(autouse=True)
def _no_real_cost_tracker(monkeypatch):
    """Default: budget always admits, cost recording is a no-op.

    Specific tests override these.
    """

    async def _allow(*_a, **_k):
        return True

    async def _noop_record(*_a, **_k):
        return None

    monkeypatch.setattr(client_mod, "_budget_can_admit", _allow)
    monkeypatch.setattr(client_mod, "_record_cost", _noop_record)


def _install_fake_http(monkeypatch, response_factory) -> _FakeClient:
    """Replace the module-level http client with a fake. Returns the fake."""
    fake = _FakeClient(response_factory)

    async def _factory():
        return fake

    monkeypatch.setattr(client_mod, "_get_http_client", _factory)
    return fake


# ── Test 1: unknown model ────────────────────────────────────────────────


def test_unknown_model_raises_UnknownModelError():  # noqa: N802
    async def _go():
        await chat(
            model="not-a-real-model",
            messages=[{"role": "user", "content": "hi"}],
        )

    with pytest.raises(UnknownModelError) as ei:
        asyncio.run(_go())
    assert "not-a-real-model" in str(ei.value)


# ── Test 2: circuit breaker opens after N failures ───────────────────────


def test_circuit_breaker_opens_after_5_consecutive_failures(monkeypatch):
    """Force the provider to always raise; after fail_threshold attempts
    the breaker should be OPEN and subsequent calls raise CircuitOpen
    BEFORE the provider call fires.
    """
    # Stub provider call: always raises a non-retryable, non-fatal exception
    # to keep retries from masking the failure count.
    call_count = {"n": 0}

    async def _failing_handler(**_kwargs):
        call_count["n"] += 1
        raise RuntimeError("simulated provider failure")

    monkeypatch.setitem(
        client_mod._PROVIDER_DISPATCH,
        client_mod.Provider.ANTHROPIC,
        _failing_handler,
    )

    # Use a small threshold so the test is fast.
    breaker = CircuitBreaker.for_provider("anthropic", fail_threshold=5, recovery_seconds=300.0)

    async def _one():
        return await chat(
            model="claude-haiku-4-5",
            messages=[{"role": "user", "content": "hi"}],
            budget_key="anthropic",
        )

    # Five attempts — each runs the retry loop, exhausts retries, records
    # 1 failure on the breaker. After 5, breaker should be open.
    for _ in range(5):
        with pytest.raises(Exception):
            asyncio.run(_one())

    assert (
        breaker.consecutive_failures >= 5
    ), f"expected >=5 failures, got {breaker.consecutive_failures}"
    assert breaker.is_open, "breaker should be OPEN after 5 failures"

    # Next call should be refused BEFORE the handler runs.
    handler_calls_before = call_count["n"]
    with pytest.raises(CircuitOpen) as ei:
        asyncio.run(_one())
    assert "anthropic" in str(ei.value)
    assert (
        call_count["n"] == handler_calls_before
    ), "handler must NOT be invoked when circuit is open"


# ── Test 3: budget gate raises before call ───────────────────────────────


def test_budget_exhausted_raises_before_call(monkeypatch):
    """If cost_tracker.check_budget returns False the chat() call must
    raise BudgetExhausted BEFORE invoking the provider handler.
    """

    async def _deny(*_a, **_k):
        return False

    monkeypatch.setattr(client_mod, "_budget_can_admit", _deny)

    handler_invoked = {"n": 0}

    async def _handler(**_kwargs):
        handler_invoked["n"] += 1
        raise AssertionError("provider handler must NOT be invoked")

    monkeypatch.setitem(
        client_mod._PROVIDER_DISPATCH,
        client_mod.Provider.ANTHROPIC,
        _handler,
    )

    async def _go():
        return await chat(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "hi"}],
            budget_key="anthropic",
        )

    with pytest.raises(BudgetExhausted) as ei:
        asyncio.run(_go())
    assert ei.value.source == "anthropic"
    assert ei.value.est_cost > 0
    assert handler_invoked["n"] == 0


# ── Test 4: Anthropic citation docs are passed through ───────────────────


def test_anthropic_citations_documents_passed_through(monkeypatch):
    """When the caller provides ``documents`` and the model supports
    citations, the document blocks must appear in the request body's
    ``messages[0].content`` array.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")

    def _ok_response():
        return _FakeResponse(
            status_code=200,
            json_body={
                "content": [{"type": "text", "text": "answer with citation [1]"}],
                "usage": {"input_tokens": 42, "output_tokens": 8},
            },
        )

    fake = _install_fake_http(monkeypatch, _ok_response)

    docs = [
        {
            "type": "document",
            "source": {
                "type": "content",
                "content": [{"type": "text", "text": "evidence body"}],
            },
            "title": "unit-123",
            "context": "authority:NATRIX",
            "citations": {"enabled": True},
        }
    ]

    async def _go():
        return await chat(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "What does the doc say?"}],
            documents=docs,
            budget_key="anthropic",
        )

    result = asyncio.run(_go())

    assert result.text == "answer with citation [1]"
    assert result.usage_input_tokens == 42
    assert result.usage_output_tokens == 8
    assert result.model == "claude-sonnet-4-20250514"
    # cost_usd should be > 0 with non-zero tokens against a paid model
    assert result.cost_usd > 0.0

    # Inspect the request body that was actually sent
    assert len(fake.calls) == 1, "exactly one provider call expected"
    body = fake.calls[0]["json"]
    assert body["model"] == "claude-sonnet-4-20250514"

    msgs = body["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    assert isinstance(
        content, list
    ), "user content must be a content-block list when documents are passed"
    # First block must be the document we passed in
    assert content[0]["type"] == "document"
    assert content[0]["citations"] == {"enabled": True}
    assert content[0]["title"] == "unit-123"
    # User's text follows the doc blocks
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "What does the doc say?"
