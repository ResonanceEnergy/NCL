"""
LLMClientAdapter — duck-typed shim wrapping ``runtime.llm.chat`` so the
swarm subsystem (orchestrator + task_graph + agent_base + specialist
agents) can use the W8-A6 facade without depending on the deprecated
``runtime.swarm.llm_router.LLMRouter``.

W10C-15 (2026-05-24)
--------------------
SwarmOrchestrator + brain.py historically instantiated
``LLMRouter(config=...)`` and passed it through to every nested
component. ``LLMRouter`` is scheduled for deletion 2026-06-23 (30-day
clean window after W8-A6). To unblock that deletion without touching
every nested call site, this adapter exposes the same public surface
the orchestrator already uses:

    - ``async call(backend, prompt, max_tokens, temperature, system_prompt)``
      → returns an ``LLMResponse``-shaped object (``content``, ``model``,
      ``tokens_in``, ``tokens_out``, ``cost_cents``, ``latency_ms``)
    - ``call_count`` property — total successful calls
    - ``total_cost_cents`` property — running sum of cost_cents across calls
    - ``async close()`` — no-op (the facade owns its own httpx client)

Internally every call funnels through ``runtime.llm.chat()`` which owns:
    * model lookup + provider dispatch
    * budget gate via ``runtime.cost_tracker``
    * per-provider circuit breaker
    * retry-with-jitter
    * cost recording (after the call lands)
    * Anthropic Citations passthrough (unused here — swarm doesn't pass
      ``documents`` blocks)

We do NOT replicate the LLMRouter fallback chain (claude → ollama, etc.).
The new ``runtime.llm`` facade has its own circuit breaker; if the
primary provider is failing, callers should pick a different model
explicitly. The orchestrator only uses one backend ("claude") so this
loss is theoretical.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..llm import chat as _chat
from ..llm.errors import LLMError


logger = logging.getLogger(__name__)


# ── Backend → canonical model id ──────────────────────────────────────
# The swarm passes backend names ("claude", "grok", ...) the same way
# LLMRouter did. Translate to canonical model ids in MODEL_REGISTRY.
_BACKEND_TO_MODEL: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "grok": "grok-3",
    "gemini": "gemini-2.5-pro",
    "gpt": "gpt-4o",
    "perplexity": "sonar-pro",
    "ollama": "qwen3:32b",
}


# ── Backend → cost-tracker budget key ─────────────────────────────────
# Mirrors Provider enum values in runtime/llm/models.py. Ollama is local
# (free) but we still pass a key for telemetry symmetry.
_BACKEND_TO_BUDGET: dict[str, str] = {
    "claude": "anthropic",
    "grok": "xai",
    "gemini": "google",
    "gpt": "openai",
    "perplexity": "perplexity",
    "ollama": "ollama",
}


@dataclass(frozen=True)
class _LLMResponse:
    """Shape-compatible with ``runtime.swarm.llm_router.LLMResponse``.

    Defined here (not imported from llm_router) so this adapter has zero
    dependency on the deprecated module. Field names + types match
    exactly so existing call sites read the same attributes.
    """

    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_cents: float
    latency_ms: int


class LLMClientAdapter:
    """Drop-in replacement for ``LLMRouter`` that delegates to ``runtime.llm.chat``.

    The orchestrator, task graph builder, and every specialist agent
    expect a router-shaped object. This adapter satisfies that contract
    without holding any HTTP state of its own — the facade owns the
    httpx client, budget gate, breaker, and retry.

    Config keys are accepted for API symmetry with ``LLMRouter`` but most
    are ignored: the facade reads API keys from the environment
    (ANTHROPIC_API_KEY, XAI_API_KEY, …). We do still accept ``config``
    so brain.py's existing instantiation pattern continues to work
    without surgery on the call site.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._call_count: int = 0
        self._total_cost_cents: float = 0.0

    # ── Read-only stats (orchestrator.get_stats reads these) ──────────

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def total_cost_cents(self) -> float:
        return self._total_cost_cents

    # ── The call site ─────────────────────────────────────────────────

    async def call(
        self,
        backend: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> _LLMResponse:
        """Route to ``runtime.llm.chat`` and return an LLMResponse-shaped object.

        Args:
            backend: One of "claude", "grok", "gemini", "gpt", "perplexity",
                "ollama". Unknown backends fall back to "claude" with a
                warning.
            prompt: User prompt text. Wrapped as a single user message.
            max_tokens: Output token cap.
            temperature: Sampling temperature.
            system_prompt: Optional system instruction.

        Raises:
            LLMError (and subclasses) on facade failures. The caller's
            retry / fallback policy is gone — the facade handles its own
            retries internally.
        """
        model = _BACKEND_TO_MODEL.get(backend)
        if model is None:
            logger.warning(
                "LLMClientAdapter: unknown backend %r, defaulting to claude",
                backend,
            )
            backend = "claude"
            model = _BACKEND_TO_MODEL["claude"]

        budget_key = _BACKEND_TO_BUDGET.get(backend, "default")

        result = await _chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            budget_key=budget_key,
        )

        cost_cents = round(result.cost_usd * 100.0, 6)
        # Stats are updated unsynchronised — the orchestrator only reads
        # them for /stats reporting. Concurrent ``call()`` invocations may
        # race here but the worst case is a single missed increment, not
        # a torn read. Matches the pre-existing LLMRouter behaviour
        # closely enough (LLMRouter used a lock; we drop that to avoid a
        # second source of contention, since the facade itself is the
        # bottleneck).
        self._call_count += 1
        self._total_cost_cents += cost_cents

        return _LLMResponse(
            content=result.text,
            model=result.model,
            tokens_in=result.usage_input_tokens,
            tokens_out=result.usage_output_tokens,
            cost_cents=cost_cents,
            latency_ms=result.latency_ms,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def close(self) -> None:
        """No-op. The ``runtime.llm`` facade owns its own httpx client."""
        # Intentionally do NOT call ``runtime.llm.aclose()`` here — the
        # facade's client is process-wide and shared with every other
        # subsystem (council_runner, awarebot scorers, etc.). Closing it
        # would tear down their HTTP connections too.
        return None


__all__ = [
    "LLMClientAdapter",
    "LLMError",
]
