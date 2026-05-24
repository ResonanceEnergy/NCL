"""
NCL LLM Router Foundation (Wave 1 — Agent 06)
=============================================

A clean, greenfield ``runtime.llm`` facade for every LLM call in the brain.

Public surface
--------------
    from runtime.llm import chat, ChatResult
    from runtime.llm.errors import LLMError, BudgetExhausted, CircuitOpen
    from runtime.llm.models import MODEL_REGISTRY, Provider, ModelSpec, lookup

Goals
-----
1. One callable: ``await chat(model=..., messages=..., ...)``
2. Budget gate via ``runtime.cost_tracker`` BEFORE the call
3. Per-provider circuit breaker (refuses calls after 5 consecutive failures)
4. Retry with exponential backoff + jitter (lifted from
   ``runtime.memory.async_writer._retry_with_jitter``)
5. Anthropic Citations API passthrough when the caller provides ``documents``
6. Structured error taxonomy

Wave 2 agents will migrate existing call sites onto this. Wave 1 (this PR)
ships the foundation only — it does NOT touch any existing module.
"""

from __future__ import annotations  # noqa: I001

from .client import ChatResult, chat
from .errors import (
    BudgetExhausted,
    CircuitOpen,
    FatalAPIError,
    LLMError,
    RateLimited,
    UnknownModelError,
)
from .models import MODEL_REGISTRY, ModelSpec, Provider, lookup
from .retry import CircuitBreaker, retry_with_jitter

__all__ = [
    "chat",
    "ChatResult",
    "LLMError",
    "BudgetExhausted",
    "CircuitOpen",
    "RateLimited",
    "FatalAPIError",
    "UnknownModelError",
    "MODEL_REGISTRY",
    "ModelSpec",
    "Provider",
    "lookup",
    "CircuitBreaker",
    "retry_with_jitter",
]
