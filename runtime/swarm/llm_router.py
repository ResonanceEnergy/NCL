"""
Unified LLM Router for the NCL Agent Swarm.

Routes requests to multiple LLM backends (Claude, Grok, Gemini, GPT,
Perplexity, Ollama) with fallback chains, concurrency limits, and cost tracking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResponse:
    """Standardized response from any LLM backend."""

    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_cents: float
    latency_ms: int


# ---------------------------------------------------------------------------
# Cost tables (per 1M tokens, in cents)
# ---------------------------------------------------------------------------

_COST_TABLE: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 300.0, "output": 1500.0},
    "claude-opus-4-20250514": {"input": 1500.0, "output": 7500.0},
    "claude-3-5-haiku-20241022": {"input": 80.0, "output": 400.0},
    "grok-3": {"input": 300.0, "output": 1500.0},
    "grok-3-mini": {"input": 30.0, "output": 50.0},
    "gemini-2.5-pro": {"input": 125.0, "output": 1000.0},
    "gemini-2.5-flash": {"input": 15.0, "output": 60.0},
    "gpt-4o": {"input": 250.0, "output": 1000.0},
    "gpt-4o-mini": {"input": 15.0, "output": 60.0},
    "sonar-pro": {"input": 300.0, "output": 1500.0},
    "sonar": {"input": 100.0, "output": 100.0},
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate cost in cents for a given call."""
    costs = _COST_TABLE.get(model)
    if not costs:
        return 0.0
    input_cost = (tokens_in / 1_000_000) * costs["input"]
    output_cost = (tokens_out / 1_000_000) * costs["output"]
    return round(input_cost + output_cost, 4)


# ---------------------------------------------------------------------------
# Default fallback chains
# ---------------------------------------------------------------------------

_DEFAULT_FALLBACKS: dict[str, list[str]] = {
    "claude": ["claude-sonnet-4-20250514", "ollama:qwen3:32b"],
    "grok": ["grok-3", "grok-3-mini", "ollama:qwen3:32b"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash", "ollama:qwen3:32b"],
    "gpt": ["gpt-4o", "gpt-4o-mini", "ollama:qwen3:32b"],
    "perplexity": ["sonar-pro", "sonar"],
    "ollama": ["ollama:qwen3:32b"],
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """
    Routes LLM calls to the appropriate backend with fallback and concurrency control.

    Config keys:
        anthropic_api_key, xai_api_key, google_api_key, openai_api_key,
        perplexity_api_key, ollama_host
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._cloud_semaphore = asyncio.Semaphore(4)
        self._ollama_semaphore = asyncio.Semaphore(2)
        self._total_cost_cents: float = 0.0
        self._call_count: int = 0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    @property
    def total_cost_cents(self) -> float:
        return self._total_cost_cents

    @property
    def call_count(self) -> int:
        return self._call_count

    async def call(
        self,
        backend: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """
        Route a prompt to the specified backend with automatic fallback.

        Args:
            backend: One of "claude", "grok", "gemini", "gpt", "perplexity", "ollama".
            prompt: User/task prompt text.
            max_tokens: Maximum response tokens.
            temperature: Sampling temperature.
            system_prompt: Optional system instruction.

        Returns:
            LLMResponse from the first backend that succeeds.

        Raises:
            RuntimeError: If all backends in the fallback chain fail.
        """
        chain = _DEFAULT_FALLBACKS.get(backend, [f"{backend}"])
        last_error: Exception | None = None

        for model_id in chain:
            try:
                response = await self._dispatch(
                    model_id=model_id,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt,
                )
                self._total_cost_cents += response.cost_cents
                self._call_count += 1
                return response
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed for %s: %s — trying next in chain",
                    model_id,
                    str(exc)[:200],
                )

        raise RuntimeError(
            f"All backends in chain {chain} failed for '{backend}'. "
            f"Last error: {last_error}"
        )

    async def _dispatch(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        """Dispatch to the correct backend based on model_id prefix."""
        if model_id.startswith("ollama:"):
            return await self._call_ollama(
                model_id.removeprefix("ollama:"), prompt, max_tokens, temperature, system_prompt
            )
        elif model_id.startswith("claude"):
            return await self._call_anthropic(model_id, prompt, max_tokens, temperature, system_prompt)
        elif model_id.startswith("grok"):
            return await self._call_xai(model_id, prompt, max_tokens, temperature, system_prompt)
        elif model_id.startswith("gemini"):
            return await self._call_google(model_id, prompt, max_tokens, temperature, system_prompt)
        elif model_id.startswith("gpt"):
            return await self._call_openai(model_id, prompt, max_tokens, temperature, system_prompt)
        elif model_id.startswith("sonar"):
            return await self._call_perplexity(model_id, prompt, max_tokens, temperature, system_prompt)
        else:
            raise ValueError(f"Unknown model_id: {model_id}")

    # ------------------------------------------------------------------
    # Anthropic (Claude)
    # ------------------------------------------------------------------

    async def _call_anthropic(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        api_key = self._config.get("anthropic_api_key")
        if not api_key:
            raise ValueError("anthropic_api_key not configured")

        messages = [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with self._cloud_semaphore:
            client = await self._get_client()
            start = time.perf_counter_ns()
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
            )
            latency_ms = (time.perf_counter_ns() - start) // 1_000_000

        resp.raise_for_status()
        data = resp.json()
        content = "".join(
            block["text"] for block in data.get("content", []) if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=_estimate_cost(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # xAI (Grok)
    # ------------------------------------------------------------------

    async def _call_xai(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        api_key = self._config.get("xai_api_key")
        if not api_key:
            raise ValueError("xai_api_key not configured")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with self._cloud_semaphore:
            client = await self._get_client()
            start = time.perf_counter_ns()
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            latency_ms = (time.perf_counter_ns() - start) // 1_000_000

        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=_estimate_cost(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Google (Gemini)
    # ------------------------------------------------------------------

    async def _call_google(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        api_key = self._config.get("google_api_key")
        if not api_key:
            raise ValueError("google_api_key not configured")

        contents = [{"parts": [{"text": prompt}], "role": "user"}]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
            f":generateContent?key={api_key}"
        )

        async with self._cloud_semaphore:
            client = await self._get_client()
            start = time.perf_counter_ns()
            resp = await client.post(url, json=body)
            latency_ms = (time.perf_counter_ns() - start) // 1_000_000

        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [{}])
        content = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts)

        usage_meta = data.get("usageMetadata", {})
        tokens_in = usage_meta.get("promptTokenCount", 0)
        tokens_out = usage_meta.get("candidatesTokenCount", 0)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=_estimate_cost(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # OpenAI (GPT)
    # ------------------------------------------------------------------

    async def _call_openai(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        api_key = self._config.get("openai_api_key")
        if not api_key:
            raise ValueError("openai_api_key not configured")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with self._cloud_semaphore:
            client = await self._get_client()
            start = time.perf_counter_ns()
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            latency_ms = (time.perf_counter_ns() - start) // 1_000_000

        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=_estimate_cost(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Perplexity
    # ------------------------------------------------------------------

    async def _call_perplexity(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        api_key = self._config.get("perplexity_api_key")
        if not api_key:
            raise ValueError("perplexity_api_key not configured")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with self._cloud_semaphore:
            client = await self._get_client()
            start = time.perf_counter_ns()
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            latency_ms = (time.perf_counter_ns() - start) // 1_000_000

        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=_estimate_cost(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Ollama (local)
    # ------------------------------------------------------------------

    async def _call_ollama(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> LLMResponse:
        host = self._config.get("ollama_host", "http://localhost:11434")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with self._ollama_semaphore:
            client = await self._get_client()
            start = time.perf_counter_ns()
            resp = await client.post(
                f"{host}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            latency_ms = (time.perf_counter_ns() - start) // 1_000_000

        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        tokens_in = data.get("prompt_eval_count", 0)
        tokens_out = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            model=f"ollama:{model}",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=0.0,  # Local inference is free
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        logger.info(
            "LLMRouter closed: %d calls, %.2f¢ total cost",
            self._call_count,
            self._total_cost_cents,
        )
