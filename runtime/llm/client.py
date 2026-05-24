"""
LLM client facade — the single ``chat()`` entry point.

Every Wave-2 caller will go through this function. It owns:
    1. Model lookup → ``ModelSpec`` (raises ``UnknownModelError``)
    2. Per-provider circuit breaker gate (raises ``CircuitOpen``)
    3. Budget gate via ``runtime.cost_tracker`` (raises ``BudgetExhausted``)
    4. Provider dispatch (Anthropic + Ollama implemented; others stubbed)
    5. Retry + exponential backoff via ``retry_with_jitter``
    6. Anthropic Citations API passthrough
    7. Cost recording after a successful call
    8. Structured ``ChatResult`` return

The facade is provider-agnostic at the call site. Add new providers by
implementing a ``_call_<provider>()`` coroutine with the same signature
as ``_call_anthropic``.

Wave 2 migration
----------------
Existing call sites (council_runner/agents.py, awarebot/scorers, etc.)
still use ``runtime.swarm.llm_router.LLMRouter`` or raw httpx. Migrate
them by replacing the call with:

    from runtime.llm import chat
    result = await chat(
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": prompt}],
        system=system_prompt,
        budget_key="anthropic",
    )
    text = result.text

The old LLMRouter remains intact until every caller has migrated.
"""

from __future__ import annotations  # noqa: I001

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .errors import (
    BudgetExhausted,
    FatalAPIError,
    LLMError,
    MalformedResponseError,
    RateLimited,
)
from .models import ModelSpec, Provider, lookup
from .retry import CircuitBreaker, retry_with_jitter

log = logging.getLogger("ncl.llm.client")

# ── HTTP defaults ─────────────────────────────────────────────────────
_DEFAULT_TIMEOUT_S = 30.0
_OLLAMA_TIMEOUT_S = 120.0  # local inference can be slow on big models
_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# ═══════════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ChatResult:
    """Provider-agnostic chat result.

    Attributes
    ----------
    text
        Concatenated text response. For multi-block Anthropic responses
        this is the joined ``text`` blocks. For Ollama / OpenAI-shaped
        responses it's the single message content.
    citations
        Flat list of citation annotations, as produced by
        ``runtime.council_pack.citations.parse_citations``. Empty when
        the caller didn't pass ``documents`` or the model didn't cite.
    usage_input_tokens
        Provider-reported input token count. ``0`` when unavailable.
    usage_output_tokens
        Provider-reported output token count. ``0`` when unavailable.
    cost_usd
        Estimated cost in USD from ``ModelSpec.estimate_cost``.
    model
        Canonical model id (echoes the request).
    latency_ms
        Wall-clock latency of the provider call (does NOT include retry
        sleeps — measures the successful attempt only).
    raw
        Raw provider response JSON. Useful for debugging; do not rely on
        its shape in production code.
    """

    text: str
    citations: list[dict]
    usage_input_tokens: int
    usage_output_tokens: int
    cost_usd: float
    model: str
    latency_ms: int
    raw: dict = field(default_factory=dict, repr=False, compare=False)


# ═══════════════════════════════════════════════════════════════════════
# SHARED HTTP CLIENT
# ═══════════════════════════════════════════════════════════════════════


_http_client: Optional[httpx.AsyncClient] = None


async def _get_http_client() -> httpx.AsyncClient:
    """Module-level singleton httpx.AsyncClient.

    Lazily instantiated. Reused across calls so we benefit from
    connection pooling. Process-wide.
    """
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        return _http_client
    # Use the longer ollama timeout as the top-level cap; per-request
    # timeouts override on cloud calls.
    _http_client = httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_S)
    return _http_client


async def aclose() -> None:
    """Close the shared HTTP client. Idempotent."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


# ═══════════════════════════════════════════════════════════════════════
# COST-TRACKER HELPERS (defensive — never block on telemetry)
# ═══════════════════════════════════════════════════════════════════════


async def _budget_can_admit(budget_key: str, est_cost: float) -> bool:
    """Ask cost_tracker.check_budget; on import / runtime failure, ALLOW.

    Telemetry should never block real work. If the tracker isn't wired up
    yet (early-boot, unit tests, etc.) we fall through to True.
    """
    try:
        from .. import cost_tracker

        return await cost_tracker.check_budget(budget_key, est_cost)
    except Exception as exc:  # noqa: BLE001 - defensive
        log.debug("budget check failed (allowing call): %s", exc)
        return True


async def _record_cost(
    budget_key: str,
    cost_usd: float,
    *,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Fire-and-forget cost record. Swallow all errors."""
    try:
        from .. import cost_tracker

        await cost_tracker.record_cost(
            source=budget_key,
            amount_usd=cost_usd,
            category=f"llm:{model}",
            detail=f"in={tokens_in} out={tokens_out}",
        )
    except Exception as exc:  # noqa: BLE001 - defensive
        log.debug("cost record failed (non-fatal): %s", exc)


# ═══════════════════════════════════════════════════════════════════════
# HTTP STATUS → STRUCTURED ERROR
# ═══════════════════════════════════════════════════════════════════════


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    """Translate a non-2xx response into the right structured error.

    - 429              → ``RateLimited`` (retryable)
    - 401 / 403 / 404  → ``FatalAPIError`` (NOT retryable)
    - other non-2xx    → ``httpx.HTTPStatusError`` (retryable by default)
    """
    status = resp.status_code
    if 200 <= status < 300:
        return
    body_preview = ""
    try:
        body_preview = resp.text[:500]
    except Exception:
        pass
    if status == 429:
        retry_after = None
        try:
            retry_after = float(resp.headers.get("retry-after") or 0) or None
        except (TypeError, ValueError):
            retry_after = None
        raise RateLimited(provider, retry_after)
    if status in (401, 403, 404):
        raise FatalAPIError(status, body_preview)
    # Bubble up as httpx error so retry_with_jitter sees the status.
    resp.raise_for_status()


# ═══════════════════════════════════════════════════════════════════════
# ANTHROPIC
# ═══════════════════════════════════════════════════════════════════════


# Allowed Anthropic content-block types. Anything outside this set is
# treated as suspicious (could be a MITM injection or a corrupted upstream).
_ANTHROPIC_ALLOWED_BLOCK_TYPES = frozenset({"text", "tool_use", "document", "thinking"})


def _validate_anthropic_response(data: Any) -> None:
    """Validate the shape of an Anthropic Messages API response.

    Defensive schema check — the LLM facade trusts NOTHING about the
    upstream payload until this function returns. A MITM, a corrupted
    proxy, or a provider regression could inject blocks that our
    downstream code would otherwise read with ``data.get("content", [])``
    and concatenate as plain text.

    Rules enforced
    --------------
    1. ``data`` must be a ``dict``.
    2. ``data["content"]`` must exist and be a ``list``.
    3. Each block must be a ``dict`` with a ``type`` field whose value is
       one of ``{"text", "tool_use", "document", "thinking"}``.
    4. ``text`` blocks must have a string ``text`` field.
    5. When a ``text`` block carries ``citations`` annotations, that field
       must be a ``list`` (Anthropic's schema; we never want a single
       dict masquerading as a citation list).

    Raises
    ------
    MalformedResponseError
        On any rule violation. ``raw`` carries a JSON-text preview
        (capped at 500 chars in the exception).
    """
    import json

    def _raw_preview() -> str:
        try:
            return json.dumps(data, default=str)
        except Exception:  # noqa: BLE001 - defensive
            return repr(data)

    if not isinstance(data, dict):
        raise MalformedResponseError(
            "anthropic",
            f"response is not a dict (got {type(data).__name__})",
            raw=_raw_preview(),
        )
    if "content" not in data:
        raise MalformedResponseError(
            "anthropic",
            "missing 'content' key",
            raw=_raw_preview(),
        )
    content = data["content"]
    if not isinstance(content, list):
        raise MalformedResponseError(
            "anthropic",
            f"'content' is not a list (got {type(content).__name__})",
            raw=_raw_preview(),
        )
    for i, block in enumerate(content):
        if not isinstance(block, dict):
            raise MalformedResponseError(
                "anthropic",
                f"content[{i}] is not a dict (got {type(block).__name__})",
                raw=_raw_preview(),
            )
        if "type" not in block:
            raise MalformedResponseError(
                "anthropic",
                f"content[{i}] missing 'type'",
                raw=_raw_preview(),
            )
        btype = block["type"]
        if btype not in _ANTHROPIC_ALLOWED_BLOCK_TYPES:
            raise MalformedResponseError(
                "anthropic",
                f"content[{i}] has unknown type {btype!r}",
                raw=_raw_preview(),
            )
        if btype == "text":
            if "text" not in block or not isinstance(block.get("text"), str):
                raise MalformedResponseError(
                    "anthropic",
                    f"content[{i}] (text block) missing string 'text' field",
                    raw=_raw_preview(),
                )
            if "citations" in block and not isinstance(block["citations"], list):
                raise MalformedResponseError(
                    "anthropic",
                    f"content[{i}].citations is not a list "
                    f"(got {type(block['citations']).__name__})",
                    raw=_raw_preview(),
                )


def _build_anthropic_user_content(
    messages: list[dict],
    documents: Optional[list[dict]],
    spec: ModelSpec,
) -> list[dict]:
    """Build the Anthropic messages array.

    If ``documents`` is provided AND the model supports citations, we
    inject the document blocks into the FIRST user message's ``content``
    array (followed by the user's text). Subsequent user/assistant turns
    are passed through unmodified.

    The ``documents`` shape must match
    ``runtime.council_pack.citations.build_citation_documents`` output
    (i.e. ``type=document`` blocks with ``citations.enabled=True``).
    """
    if not messages:
        raise LLMError("anthropic: messages must be non-empty")

    out: list[dict] = []
    first_user_consumed = False
    use_docs = bool(documents) and spec.supports_citations

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            # System messages go in the top-level `system` field, not the
            # messages array. Skip here; the caller passes `system=` kwarg
            # OR they put a system role in messages — we drop the latter
            # silently because Anthropic rejects role=system in messages.
            continue
        content = msg.get("content", "")
        if role == "user" and not first_user_consumed and use_docs:
            blocks: list[dict] = list(documents or [])
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                blocks.extend(content)
            else:
                blocks.append({"type": "text", "text": str(content)})
            out.append({"role": "user", "content": blocks})
            first_user_consumed = True
        else:
            out.append({"role": role, "content": content})
            if role == "user":
                first_user_consumed = True
    if not out:
        raise LLMError("anthropic: messages contained no non-system turns")
    return out


async def _call_anthropic(
    *,
    spec: ModelSpec,
    messages: list[dict],
    system: Optional[str],
    max_tokens: int,
    temperature: float,
    documents: Optional[list[dict]],
    timeout_s: float,
) -> tuple[str, list[dict], int, int, dict]:
    """Anthropic Messages API call.

    Returns ``(text, citations, in_tokens, out_tokens, raw_json)``.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # Treat as fatal — no point retrying.
        raise FatalAPIError(401, "ANTHROPIC_API_KEY not set")

    body: dict[str, Any] = {
        "model": spec.name,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": _build_anthropic_user_content(messages, documents, spec),
    }
    if system:
        body["system"] = system

    client = await _get_http_client()
    resp = await client.post(
        _ANTHROPIC_ENDPOINT,
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json=body,
        timeout=timeout_s,
    )
    _raise_for_status(resp, Provider.ANTHROPIC.value)
    data = resp.json()
    _validate_anthropic_response(data)

    # Concatenate text blocks
    text_parts: list[str] = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text") or "")
    text = "".join(text_parts)

    # Citation annotations — defer parsing to council_pack.citations
    citations: list[dict] = []
    if documents and spec.supports_citations:
        try:
            from ..council_pack.citations import parse_citations

            citations = parse_citations(data)
        except Exception as exc:  # noqa: BLE001 - defensive
            log.debug("parse_citations failed: %s", exc)
            citations = []

    usage = data.get("usage", {}) or {}
    in_tokens = int(usage.get("input_tokens", 0) or 0)
    out_tokens = int(usage.get("output_tokens", 0) or 0)
    return text, citations, in_tokens, out_tokens, data


# ═══════════════════════════════════════════════════════════════════════
# OLLAMA (local, free)
# ═══════════════════════════════════════════════════════════════════════


async def _call_ollama(
    *,
    spec: ModelSpec,
    messages: list[dict],
    system: Optional[str],
    max_tokens: int,
    temperature: float,
    documents: Optional[list[dict]],
    timeout_s: float,
) -> tuple[str, list[dict], int, int, dict]:
    """Ollama /api/chat call. Local — no API key, no cost."""
    # Ollama doesn't support citations; documents would be ignored. We
    # silently drop them rather than 400 on a feature mismatch.
    out_messages: list[dict] = []
    if system:
        out_messages.append({"role": "system", "content": system})
    for msg in messages:
        role = msg.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        # Ollama expects content as a string. Flatten block-shaped content
        # if any slipped in.
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        out_messages.append({"role": role, "content": content})

    client = await _get_http_client()
    resp = await client.post(
        f"{_OLLAMA_HOST.rstrip('/')}/api/chat",
        json={
            "model": spec.name,
            "messages": out_messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        },
        timeout=timeout_s,
    )
    _raise_for_status(resp, Provider.OLLAMA.value)
    data = resp.json()
    text = (data.get("message") or {}).get("content") or ""
    in_tokens = int(data.get("prompt_eval_count", 0) or 0)
    out_tokens = int(data.get("eval_count", 0) or 0)
    return text, [], in_tokens, out_tokens, data


# ═══════════════════════════════════════════════════════════════════════
# OPENAI-SHAPED PROVIDERS (xAI, OpenAI, Perplexity)
# ═══════════════════════════════════════════════════════════════════════
#
# Three providers share the OpenAI ``/v1/chat/completions`` request/response
# shape: xAI (api.x.ai), OpenAI (api.openai.com), and Perplexity
# (api.perplexity.ai). One helper handles all three.


_PROVIDER_ENDPOINTS: dict[Provider, str] = {
    Provider.XAI: "https://api.x.ai/v1/chat/completions",
    Provider.OPENAI: "https://api.openai.com/v1/chat/completions",
    Provider.PERPLEXITY: "https://api.perplexity.ai/chat/completions",
}

_PROVIDER_ENV_KEYS: dict[Provider, str] = {
    Provider.XAI: "XAI_API_KEY",
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.PERPLEXITY: "PERPLEXITY_API_KEY",
    Provider.GOOGLE: "GOOGLE_API_KEY",
}


def _openai_shape_messages(messages: list[dict], system: Optional[str]) -> list[dict]:
    """Flatten messages to the OpenAI/xAI/Perplexity wire shape.

    - System prompt (from kwarg) is prepended as a ``role=system`` message.
    - In-message ``system`` roles are passed through verbatim.
    - Block-shaped content (Anthropic citations) is flattened to text
      because these providers don't support citations.
    """
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for msg in messages:
        role = msg.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        out.append({"role": role, "content": content})
    return out


async def _call_openai_shape(
    provider: Provider,
    *,
    spec: ModelSpec,
    messages: list[dict],
    system: Optional[str],
    max_tokens: int,
    temperature: float,
    documents: Optional[list[dict]],  # noqa: ARG001 - intentionally ignored
    timeout_s: float,
) -> tuple[str, list[dict], int, int, dict]:
    """Shared implementation for xAI / OpenAI / Perplexity.

    Citations (``documents``) are silently dropped — only Anthropic
    supports them today. Returns ``(text, [], in_tok, out_tok, raw)``.
    """
    env_key = _PROVIDER_ENV_KEYS[provider]
    api_key = os.getenv(env_key)
    if not api_key:
        raise FatalAPIError(401, f"{env_key} not set")

    endpoint = _PROVIDER_ENDPOINTS[provider]
    client = await _get_http_client()
    resp = await client.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": spec.name,
            "messages": _openai_shape_messages(messages, system),
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout_s,
    )
    _raise_for_status(resp, provider.value)
    data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise MalformedResponseError(
            provider.value,
            f"no choices in response (keys={list(data.keys())})",
            raw=str(data)[:500],
        )
    msg = choices[0].get("message") or {}
    text = msg.get("content") or ""

    usage = data.get("usage") or {}
    in_tokens = int(usage.get("prompt_tokens", 0) or 0)
    out_tokens = int(usage.get("completion_tokens", 0) or 0)
    return text, [], in_tokens, out_tokens, data


async def _call_xai(**kw: Any) -> tuple[str, list[dict], int, int, dict]:
    return await _call_openai_shape(Provider.XAI, **kw)


async def _call_openai(**kw: Any) -> tuple[str, list[dict], int, int, dict]:
    return await _call_openai_shape(Provider.OPENAI, **kw)


async def _call_perplexity(**kw: Any) -> tuple[str, list[dict], int, int, dict]:
    return await _call_openai_shape(Provider.PERPLEXITY, **kw)


# ═══════════════════════════════════════════════════════════════════════
# GOOGLE GEMINI (generateContent)
# ═══════════════════════════════════════════════════════════════════════


async def _call_google(
    *,
    spec: ModelSpec,
    messages: list[dict],
    system: Optional[str],
    max_tokens: int,
    temperature: float,
    documents: Optional[list[dict]],  # noqa: ARG001 - ignored (no citations)
    timeout_s: float,
) -> tuple[str, list[dict], int, int, dict]:
    """Google generativelanguage v1beta call (Gemini)."""
    api_key = os.getenv(_PROVIDER_ENV_KEYS[Provider.GOOGLE]) or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise FatalAPIError(401, "GOOGLE_API_KEY / GEMINI_API_KEY not set")

    # Flatten messages into Gemini's `contents` shape.
    # Gemini uses role names "user" and "model" (not "assistant").
    # We map assistant→model and concatenate any system kwarg in front of
    # the first user message (Gemini v1beta accepts system_instruction
    # but older callers were passing system via prompt prepend — preserve
    # that lossless behaviour).
    contents: list[dict] = []
    pending_system = system or None
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            # Coalesce in-message system into pending_system
            sys_text = msg.get("content", "")
            if isinstance(sys_text, list):
                sys_text = "\n".join(
                    b.get("text", "")
                    for b in sys_text
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            pending_system = (pending_system + "\n\n" + sys_text) if pending_system else sys_text
            continue
        if role not in {"user", "assistant"}:
            continue
        text_content = msg.get("content", "")
        if isinstance(text_content, list):
            text_content = "\n".join(
                b.get("text", "")
                for b in text_content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if pending_system and role == "user":
            text_content = pending_system + "\n\n" + str(text_content)
            pending_system = None
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": str(text_content)}]})

    if not contents:
        raise LLMError("google: messages contained no user/assistant turns")

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    client = await _get_http_client()
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{spec.name}:generateContent"
    )
    resp = await client.post(
        endpoint,
        params={"key": api_key},
        json=body,
        timeout=timeout_s,
    )
    _raise_for_status(resp, Provider.GOOGLE.value)
    data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise MalformedResponseError(
            Provider.GOOGLE.value,
            f"no candidates (keys={list(data.keys())})",
            raw=str(data)[:500],
        )
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    text = "".join(text_parts)

    usage = data.get("usageMetadata") or {}
    in_tokens = int(usage.get("promptTokenCount", 0) or 0)
    out_tokens = int(usage.get("candidatesTokenCount", 0) or 0)
    return text, [], in_tokens, out_tokens, data


# ═══════════════════════════════════════════════════════════════════════
# DISPATCH
# ═══════════════════════════════════════════════════════════════════════


_PROVIDER_DISPATCH: dict[Provider, Any] = {
    Provider.ANTHROPIC: _call_anthropic,
    Provider.OLLAMA: _call_ollama,
    Provider.XAI: _call_xai,
    Provider.OPENAI: _call_openai,
    Provider.GOOGLE: _call_google,
    Provider.PERPLEXITY: _call_perplexity,
}


# ═══════════════════════════════════════════════════════════════════════
# THE FACADE
# ═══════════════════════════════════════════════════════════════════════


async def chat(
    *,
    model: str,
    messages: list[dict],
    system: Optional[str] = None,
    max_tokens: int = 1200,
    temperature: float = 0.7,
    documents: Optional[list[dict]] = None,
    citation_documents: Optional[list[dict]] = None,
    budget_key: str = "default",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> ChatResult:
    """Send a chat-style request to an LLM and return a ``ChatResult``.

    Parameters
    ----------
    model
        Canonical model id (must be in ``MODEL_REGISTRY``).
    messages
        List of ``{"role": "user"|"assistant"|"system", "content": ...}``
        dicts. Role ``system`` may appear in this list but is dropped
        from the wire (use the ``system`` kwarg instead — every provider
        treats system prompts as a top-level field).
    system
        Optional system prompt. Prepended to the request.
    max_tokens
        Cap on output tokens. Defaults to 1200.
    temperature
        Sampling temperature. Defaults to 0.7.
    documents
        Optional list of Anthropic Citations document blocks
        (see ``runtime.council_pack.citations.build_citation_documents``).
        Passed through only when the model's ``supports_citations`` is True.
        Silently dropped otherwise.
    budget_key
        ``cost_tracker`` source key for budget gating and cost recording.
        Defaults to ``"default"`` — callers SHOULD pass the provider key
        (e.g. ``"anthropic"``, ``"xai"``).
    timeout_s
        Per-request HTTP timeout. Defaults to 30s.

    Returns
    -------
    ChatResult

    Raises
    ------
    UnknownModelError
        If ``model`` is not in ``MODEL_REGISTRY``.
    BudgetExhausted
        If the cost_tracker budget for ``budget_key`` is exhausted.
    CircuitOpen
        If the provider's circuit breaker is currently open.
    FatalAPIError
        On 401 / 403 / 404 from the provider.
    LLMError
        On other unrecoverable conditions.
    """
    spec = lookup(model)
    # Accept either `documents` (legacy kwarg) or `citation_documents`
    # (W8-A6 canonical kwarg). They're synonyms; if both are given, the
    # newer name wins.
    if citation_documents is not None:
        documents = citation_documents
    breaker = CircuitBreaker.for_provider(spec.provider.value)
    breaker.check()

    # Crude pre-call estimate — assume we'll burn ``max_tokens`` of input
    # AND ``max_tokens`` of output. Conservative; real cost is typically
    # smaller. Free providers (Ollama) skip the budget gate entirely.
    est_cost = 0.0
    if spec.input_per_mtok > 0.0 or spec.output_per_mtok > 0.0:
        est_cost = spec.estimate_cost(max_tokens, max_tokens)
        if not await _budget_can_admit(budget_key, est_cost):
            raise BudgetExhausted(budget_key, est_cost)

    handler = _PROVIDER_DISPATCH.get(spec.provider)
    if handler is None:
        raise LLMError(f"no dispatch for provider {spec.provider!r}")

    async def _attempt() -> tuple[str, list[dict], int, int, dict, int]:
        t0 = time.perf_counter_ns()
        try:
            text, citations, in_tok, out_tok, raw = await handler(
                spec=spec,
                messages=messages,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                documents=documents,
                timeout_s=timeout_s,
            )
        except FatalAPIError as fexc:
            breaker.record_failure()
            # Fatal-skip + ntfy: surface 401/403/404 to NATRIX once per
            # (provider,status) per hour via the deduped AlertDispatcher.
            try:
                from ..notifications.alert_dispatch import enqueue_alert

                enqueue_alert(
                    title=f"LLM {spec.provider.value} fatal HTTP {fexc.status}",
                    body=(f"model={spec.name} budget_key={budget_key} " f"body={fexc.body[:200]}"),
                    priority="4",
                    tags="warning,robot",
                    dedup_key=f"llm-fatal:{spec.provider.value}:{fexc.status}",
                    source="llm_facade",
                )
            except Exception as exc:  # noqa: BLE001 - alerting must never block
                log.debug("alert dispatch failed (non-fatal): %s", exc)
            raise
        except RateLimited:
            breaker.record_failure()
            raise
        except Exception:
            breaker.record_failure()
            raise
        latency_ms = (time.perf_counter_ns() - t0) // 1_000_000
        return text, citations, in_tok, out_tok, raw, int(latency_ms)

    text, citations, in_tok, out_tok, raw, latency_ms = await retry_with_jitter(
        _attempt,
        attempts=3,
        base_delays=(2.0, 5.0, 15.0),
        label=f"llm:{spec.provider.value}:{spec.name}",
    )

    # Reset breaker on success
    breaker.record_success()

    # Actual cost (token-accurate) — recorded AFTER the call
    cost_usd = spec.estimate_cost(in_tok, out_tok)
    if cost_usd > 0.0:
        await _record_cost(
            budget_key,
            cost_usd,
            model=spec.name,
            tokens_in=in_tok,
            tokens_out=out_tok,
        )

    return ChatResult(
        text=text,
        citations=citations,
        usage_input_tokens=in_tok,
        usage_output_tokens=out_tok,
        cost_usd=cost_usd,
        model=spec.name,
        latency_ms=latency_ms,
        raw=raw,
    )


__all__ = [
    "chat",
    "ChatResult",
    "aclose",
]
