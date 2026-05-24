"""
LLM model registry — canonical id → ModelSpec.

The registry is the single source of truth for:
    - which provider serves a model
    - the model's context window (tokens)
    - per-million-token input and output cost (USD)
    - whether the model supports the Anthropic Citations API

Callers always pass the *canonical id* (e.g. ``"claude-sonnet-4-20250514"``,
``"grok-3"``, ``"llama3.1:8b"``) — never a nickname or alias. If you need an
alias, add it as a separate registry entry that points at the same ModelSpec.

Cost tables
-----------
Per-million-token USD prices, sourced from each provider's pricing page as
of 2026-05-23. Update here when prices change. The single source-of-truth
location prevents cost-table drift across modules.

Adding a new model
------------------
1. Choose a canonical id (use the provider's official model id verbatim).
2. Append a ``MODEL_REGISTRY[<id>] = ModelSpec(...)`` line.
3. Wire dispatch in ``runtime.llm.client`` if it's a new provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import UnknownModelError


# StrEnum was added in Python 3.11. Fall back to str-mixin Enum on 3.10.
try:
    from enum import StrEnum  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Python 3.10 compat
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class Provider(StrEnum):
    """Canonical provider keys.

    The string value is also the ``cost_tracker`` budget source key
    (e.g. ``Provider.ANTHROPIC == "anthropic"``).
    """

    ANTHROPIC = "anthropic"
    XAI = "xai"
    OPENAI = "openai"
    GOOGLE = "google"
    PERPLEXITY = "perplexity"
    OLLAMA = "ollama"
    COHERE = "cohere"


@dataclass(frozen=True)
class ModelSpec:
    """Static metadata about a model.

    Attributes
    ----------
    name
        Canonical model id (provider's official id, verbatim).
    provider
        Which ``Provider`` serves this model.
    context_window
        Max input + output token capacity.
    input_per_mtok
        Input cost in USD per 1,000,000 tokens.
    output_per_mtok
        Output cost in USD per 1,000,000 tokens.
    supports_citations
        True iff this model supports Anthropic's Citations API (only
        Claude models do today).
    """

    name: str
    provider: Provider
    context_window: int
    input_per_mtok: float
    output_per_mtok: float
    supports_citations: bool = False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Return USD cost estimate for the given token usage."""
        in_cost = (input_tokens / 1_000_000.0) * self.input_per_mtok
        out_cost = (output_tokens / 1_000_000.0) * self.output_per_mtok
        return round(in_cost + out_cost, 6)


# ── Registry ──────────────────────────────────────────────────────────
# Canonical id → ModelSpec. Add new entries below; don't remove existing
# entries until every caller has migrated off them.

MODEL_REGISTRY: dict[str, ModelSpec] = {
    # ── Anthropic ────────────────────────────────────────────────────
    "claude-sonnet-4-20250514": ModelSpec(
        name="claude-sonnet-4-20250514",
        provider=Provider.ANTHROPIC,
        context_window=200_000,
        input_per_mtok=3.00,
        output_per_mtok=15.00,
        supports_citations=True,
    ),
    "claude-opus-4-20250514": ModelSpec(
        name="claude-opus-4-20250514",
        provider=Provider.ANTHROPIC,
        context_window=200_000,
        input_per_mtok=15.00,
        output_per_mtok=75.00,
        supports_citations=True,
    ),
    "claude-haiku-4-5": ModelSpec(
        name="claude-haiku-4-5",
        provider=Provider.ANTHROPIC,
        context_window=200_000,
        input_per_mtok=0.80,
        output_per_mtok=4.00,
        supports_citations=True,
    ),
    # Long-form id used by some callers (e.g. calendar todo_generator).
    # Same pricing/capabilities as ``claude-haiku-4-5``.
    "claude-haiku-4-5-20251001": ModelSpec(
        name="claude-haiku-4-5-20251001",
        provider=Provider.ANTHROPIC,
        context_window=200_000,
        input_per_mtok=0.80,
        output_per_mtok=4.00,
        supports_citations=True,
    ),
    "claude-3-5-haiku-20241022": ModelSpec(
        name="claude-3-5-haiku-20241022",
        provider=Provider.ANTHROPIC,
        context_window=200_000,
        input_per_mtok=0.80,
        output_per_mtok=4.00,
        supports_citations=True,
    ),
    # ── xAI ───────────────────────────────────────────────────────────
    "grok-3": ModelSpec(
        name="grok-3",
        provider=Provider.XAI,
        context_window=131_072,
        input_per_mtok=3.00,
        output_per_mtok=15.00,
    ),
    "grok-3-mini": ModelSpec(
        name="grok-3-mini",
        provider=Provider.XAI,
        context_window=131_072,
        input_per_mtok=0.30,
        output_per_mtok=0.50,
    ),
    # ── OpenAI ────────────────────────────────────────────────────────
    "gpt-4o": ModelSpec(
        name="gpt-4o",
        provider=Provider.OPENAI,
        context_window=128_000,
        input_per_mtok=2.50,
        output_per_mtok=10.00,
    ),
    "gpt-4o-mini": ModelSpec(
        name="gpt-4o-mini",
        provider=Provider.OPENAI,
        context_window=128_000,
        input_per_mtok=0.15,
        output_per_mtok=0.60,
    ),
    # ── Google ────────────────────────────────────────────────────────
    "gemini-2.0-flash": ModelSpec(
        name="gemini-2.0-flash",
        provider=Provider.GOOGLE,
        context_window=1_000_000,
        input_per_mtok=0.10,
        output_per_mtok=0.40,
    ),
    "gemini-2.5-pro": ModelSpec(
        name="gemini-2.5-pro",
        provider=Provider.GOOGLE,
        context_window=2_000_000,
        input_per_mtok=1.25,
        output_per_mtok=10.00,
    ),
    "gemini-2.5-flash": ModelSpec(
        name="gemini-2.5-flash",
        provider=Provider.GOOGLE,
        context_window=1_000_000,
        input_per_mtok=0.15,
        output_per_mtok=0.60,
    ),
    # ── Perplexity ────────────────────────────────────────────────────
    "sonar-medium": ModelSpec(
        name="sonar-medium",
        provider=Provider.PERPLEXITY,
        context_window=32_000,
        input_per_mtok=1.00,
        output_per_mtok=1.00,
    ),
    "sonar-pro": ModelSpec(
        name="sonar-pro",
        provider=Provider.PERPLEXITY,
        context_window=200_000,
        input_per_mtok=3.00,
        output_per_mtok=15.00,
    ),
    # ── Ollama (local, free) ──────────────────────────────────────────
    "llama3.1:8b": ModelSpec(
        name="llama3.1:8b",
        provider=Provider.OLLAMA,
        context_window=131_072,
        input_per_mtok=0.0,
        output_per_mtok=0.0,
    ),
    "qwen3:32b": ModelSpec(
        name="qwen3:32b",
        provider=Provider.OLLAMA,
        context_window=32_768,
        input_per_mtok=0.0,
        output_per_mtok=0.0,
    ),
}


def lookup(model: str) -> ModelSpec:
    """Return the ``ModelSpec`` for ``model`` or raise ``UnknownModelError``.

    Use this instead of ``MODEL_REGISTRY[model]`` so that downstream code
    can ``except UnknownModelError`` cleanly.
    """
    try:
        return MODEL_REGISTRY[model]
    except KeyError:
        raise UnknownModelError(model) from None


__all__ = [
    "Provider",
    "ModelSpec",
    "MODEL_REGISTRY",
    "lookup",
]
