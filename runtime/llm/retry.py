"""
Retry + circuit-breaker primitives for the LLM facade.

Lifted (with generalization) from
``runtime.memory.async_writer._retry_with_jitter``. The original lived inside
the memory subsystem and was tightly coupled to Sonnet enrichment. This
version is provider-agnostic and pairs with a per-provider
``CircuitBreaker``.

Public API
----------
- ``retry_with_jitter(coro_factory, attempts, base_delays, label)`` —
  exponential backoff with ±25% jitter, fatal-HTTP short-circuit, returns
  the wrapped coroutine's result.
- ``CircuitBreaker(provider, fail_threshold, recovery_seconds)`` —
  per-provider breaker. ``check()`` raises ``CircuitOpen`` when tripped;
  ``record_success()`` / ``record_failure()`` drive the state.

The breaker maintains a process-wide registry (``CircuitBreaker._registry``)
so independent callers see the same state for a given provider name.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, TypeVar

from .errors import CircuitOpen, FatalAPIError, RateLimited

log = logging.getLogger("ncl.llm.retry")

T = TypeVar("T")

# HTTP status taxonomy (matches async_writer)
_RETRYABLE_HTTP = frozenset({429, 502, 503, 504, 529})
_FATAL_HTTP = frozenset({401, 403, 404})


def _status_of(exc: BaseException) -> int | None:
    """Best-effort extract an HTTP status code from an exception."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if status is not None:
            return int(status)
    inline = getattr(exc, "status_code", None)
    if inline is not None:
        try:
            return int(inline)
        except (TypeError, ValueError):
            return None
    if isinstance(exc, FatalAPIError):
        return exc.status
    if isinstance(exc, RateLimited):
        return 429
    return None


async def retry_with_jitter(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delays: tuple[float, ...] = (2.0, 5.0, 15.0),
    label: str = "llm_call",
) -> T:
    """Call ``coro_factory()`` with exponential backoff retries.

    Parameters
    ----------
    coro_factory
        A zero-arg callable returning a fresh coroutine. Invoked once per
        attempt — never reuse a coroutine object across attempts.
    attempts
        Total number of attempts INCLUDING the first. Defaults to 3.
    base_delays
        Base delays (seconds) between attempts. The N-th retry sleeps for
        ``base_delays[N-1] * uniform(0.75, 1.25)``. Defaults to (2, 5, 15).
        Must have at least ``attempts - 1`` entries.
    label
        Logging label.

    Returns
    -------
    Whatever ``coro_factory()`` returns on the first successful attempt.

    Raises
    ------
    The last exception if all attempts fail. ``FatalAPIError`` (or any
    other exception whose HTTP status is in {401,403,404}) short-circuits
    and is re-raised immediately — retrying a fatal error makes the
    problem worse (burns budget on a doomed call).
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if len(base_delays) < attempts - 1:
        # Pad with the last delay so misconfigured callers don't IndexError.
        last = base_delays[-1] if base_delays else 5.0
        base_delays = base_delays + tuple(
            last for _ in range(attempts - 1 - len(base_delays))
        )

    last_exc: BaseException | None = None
    for attempt in range(attempts):
        if attempt > 0:
            base = base_delays[attempt - 1]
            jitter = base * random.uniform(0.75, 1.25)
            await asyncio.sleep(jitter)
        try:
            return await coro_factory()
        except BaseException as exc:  # noqa: BLE001 - retry policy gate
            last_exc = exc
            status = _status_of(exc)
            if status in _FATAL_HTTP or isinstance(exc, FatalAPIError):
                log.warning(
                    "[%s] fatal HTTP %s — no retry (%s)",
                    label, status, type(exc).__name__,
                )
                raise
            if attempt < attempts - 1:
                if status in _RETRYABLE_HTTP:
                    log.info(
                        "[%s] transient HTTP %s — retry %d/%d",
                        label, status, attempt + 1, attempts - 1,
                    )
                else:
                    log.debug(
                        "[%s] transient '%s' — retry %d/%d",
                        label, type(exc).__name__, attempt + 1, attempts - 1,
                    )
                continue
            # Out of attempts
            log.warning(
                "[%s] exhausted %d attempts — last error: %s",
                label, attempts, str(exc)[:200],
            )
            raise
    # Should be unreachable, but be safe.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{label}: retry_with_jitter exhausted without exception")


class CircuitBreaker:
    """Per-provider circuit breaker.

    State machine
    -------------
    - CLOSED   — calls pass through. Consecutive failures increment a counter.
    - OPEN     — after ``fail_threshold`` consecutive failures, refuse calls
                 for ``recovery_seconds``. ``check()`` raises ``CircuitOpen``.
    - HALF_OPEN — after the cooldown expires, the next call is allowed
                 through. Success → CLOSED. Failure → OPEN again (fresh
                 cooldown).

    Process-wide registry
    ---------------------
    ``CircuitBreaker.for_provider(name)`` returns a singleton per provider
    name, so independent callers share state. Direct ``CircuitBreaker(...)``
    instantiation bypasses the registry (intended for tests).
    """

    _registry: dict[str, "CircuitBreaker"] = {}

    def __init__(
        self,
        provider: str,
        fail_threshold: int = 5,
        recovery_seconds: float = 300.0,
    ) -> None:
        self.provider = provider
        self.fail_threshold = max(1, fail_threshold)
        self.recovery_seconds = max(0.0, recovery_seconds)
        self._consecutive_failures = 0
        self._opened_at: float | None = None  # None when CLOSED or HALF_OPEN

    # ── Registry accessor ────────────────────────────────────────────
    @classmethod
    def for_provider(
        cls,
        provider: str,
        fail_threshold: int = 5,
        recovery_seconds: float = 300.0,
    ) -> "CircuitBreaker":
        """Return (or create) the singleton breaker for ``provider``."""
        existing = cls._registry.get(provider)
        if existing is not None:
            return existing
        breaker = cls(provider, fail_threshold, recovery_seconds)
        cls._registry[provider] = breaker
        return breaker

    @classmethod
    def reset_registry(cls) -> None:
        """Test helper — drop all registered breakers."""
        cls._registry.clear()

    # ── State machine ────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.recovery_seconds:
            # Cooldown expired — transition to HALF_OPEN by clearing
            # _opened_at. The next call is allowed through.
            self._opened_at = None
            return False
        return True

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def check(self) -> None:
        """Raise ``CircuitOpen`` if the breaker is currently open."""
        if self.is_open:
            opened_at = self._opened_at or time.monotonic()
            until_monotonic = opened_at + self.recovery_seconds
            # Convert monotonic deadline to a wall-clock-ish "until" for the
            # exception payload. We use wall time so callers can serialize.
            until_wall = time.time() + (until_monotonic - time.monotonic())
            raise CircuitOpen(self.provider, until_wall)

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.fail_threshold:
            self._opened_at = time.monotonic()
            log.warning(
                "[circuit:%s] OPEN after %d consecutive failures "
                "(cooldown=%.0fs)",
                self.provider, self._consecutive_failures, self.recovery_seconds,
            )


__all__ = [
    "retry_with_jitter",
    "CircuitBreaker",
]
