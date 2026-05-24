"""
Structured error taxonomy for the LLM facade.

All errors in this module inherit from ``LLMError``. Callers can match on
the base class for blanket handling, or on the specific subclass for
nuanced retry / fallback policies.

Subclasses
----------
- ``BudgetExhausted`` — cost_tracker.can_admit() returned False. Not retryable.
- ``CircuitOpen``     — per-provider circuit is open. Caller may try another provider.
- ``RateLimited``     — provider returned 429. Retryable (handled internally).
- ``FatalAPIError``   — 401/403/404 from provider. Configuration bug. Not retryable.
- ``UnknownModelError`` — model id is not in ``MODEL_REGISTRY``.
"""

from __future__ import annotations

from typing import Optional


class LLMError(Exception):
    """Base class for all LLM-facade errors."""


class UnknownModelError(LLMError, KeyError):
    """Raised when a caller passes a model id not in ``MODEL_REGISTRY``.

    Subclasses ``KeyError`` for backwards compat with ``MODEL_REGISTRY[k]``
    lookup patterns, but also catchable as ``LLMError``.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"Unknown model id: {model!r}")


class BudgetExhausted(LLMError):  # noqa: N818
    """Raised when the cost_tracker budget for this source is exhausted.

    Carries the source key and the estimated cost so the caller can decide
    whether to retry against a cheaper provider, queue, or drop.
    """

    def __init__(self, source: str, est_cost: float) -> None:
        self.source = source
        self.est_cost = est_cost
        super().__init__(f"Budget exhausted for source={source!r} " f"(est_cost=${est_cost:.4f})")


class CircuitOpen(LLMError):  # noqa: N818
    """Raised when a provider's circuit breaker is open.

    Carries the provider name and the UTC unix timestamp at which the
    circuit will close again (best-effort estimate).
    """

    def __init__(self, provider: str, until: float) -> None:
        self.provider = provider
        self.until = until
        super().__init__(f"Circuit OPEN for provider={provider!r} until ts={until:.0f}")


class RateLimited(LLMError):  # noqa: N818
    """Provider returned HTTP 429.

    Retryable. The retry wrapper will catch this and back off. If retries
    are exhausted the wrapper re-raises so the caller sees it.
    """

    def __init__(self, provider: str, retry_after: Optional[float] = None) -> None:
        self.provider = provider
        self.retry_after = retry_after
        msg = f"Rate limited by {provider!r}"
        if retry_after is not None:
            msg += f" (retry_after={retry_after:.1f}s)"
        super().__init__(msg)


class FatalAPIError(LLMError):
    """Non-retryable HTTP error from a provider (401/403/404).

    Indicates a configuration bug (bad API key, wrong model id, etc.).
    Retrying makes the problem worse — these are bubbled up immediately.
    """

    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self.body = body[:500]
        super().__init__(f"Fatal API error (status={status}): {self.body!s}")


class MalformedResponseError(LLMError):
    """Provider returned a response that doesn't match the expected schema."""

    def __init__(self, provider: str, reason: str, raw: str = ""):
        super().__init__(f"malformed {provider} response: {reason}")
        self.provider = provider
        self.reason = reason
        self.raw = raw[:500]  # cap raw payload in error


__all__ = [
    "LLMError",
    "UnknownModelError",
    "BudgetExhausted",
    "CircuitOpen",
    "RateLimited",
    "FatalAPIError",
    "MalformedResponseError",
]
