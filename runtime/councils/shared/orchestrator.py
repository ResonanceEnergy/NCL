"""
Multi-Agent Council Orchestrator — CrewAI-Style Role-Based Collaboration.

Instead of calling a single AI model for analysis, this orchestrator assigns
specialized roles to different models and coordinates their collaboration:

    1. Insight Analyst (Grok) — first-pass extraction of key signals
    2. Deep Researcher (Claude) — fact-checking, source correlation, depth
    3. Strategist (Grok) — actionable intelligence, trade signals, moves
    4. Synthesizer (Claude) — final synthesis, consensus, cross-referencing
    5. Archivist (Local/Ollama) — formatting, indexing, knowledge base entry

The orchestrator runs these agents in a pipeline with handoffs,
passing each agent's output as context to the next.

Fallback: if only one model is available, all roles collapse to that model
(degrades gracefully to the existing single-model behavior).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Callable, Awaitable

log = logging.getLogger("ncl.councils.orchestrator")


@dataclass
class AgentRole:
    """Definition of a council agent role."""
    name: str
    role: str
    goal: str
    backstory: str
    model_preference: str  # "claude", "grok", "ollama"
    system_prompt: str = ""
    temperature: float = 0.4
    max_tokens: int = 4096


@dataclass
class AgentOutput:
    """Output from a single agent's work."""
    role: str
    model_used: str
    content: str
    structured: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class OrchestratorResult:
    """Final result from the full orchestrator pipeline."""
    session_id: str
    pipeline: str  # "youtube" or "x"
    agents_run: list[AgentOutput] = field(default_factory=list)
    final_synthesis: str = ""
    insights_json: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0
    models_used: list[str] = field(default_factory=list)


# ── Agent Role Definitions ────────────────────────────────────────────────

INSIGHT_ANALYST = AgentRole(
    name="Insight Analyst",
    role="analyst",
    goal="Extract raw insights, signals, and patterns from content",
    backstory="You are a world-class intelligence analyst who spots patterns others miss.",
    model_preference="grok",
    system_prompt="""You are the Insight Analyst for NARTIX Intelligence Council.

Your job: perform first-pass extraction on the provided content.

Output a JSON array of raw insights:
[
  {
    "title": "concise headline",
    "signal": "what you observed",
    "category": "content|market|geopolitical|tech|music|culture|alt-science|gaming",
    "confidence": 0.0-1.0,
    "urgency": "low|medium|high|critical",
    "tags": ["tag1", "tag2"]
  }
]

Be aggressive with extraction. Better to surface a weak signal than miss it.
The Researcher will verify and the Strategist will prioritize.""",
    temperature=0.5,
)

DEEP_RESEARCHER = AgentRole(
    name="Deep Researcher",
    role="researcher",
    goal="Verify, deepen, and cross-reference the Analyst's findings",
    backstory="You are a meticulous researcher who validates signals and adds depth.",
    model_preference="claude",
    system_prompt="""You are the Deep Researcher for NARTIX Intelligence Council.

You receive raw insights from the Insight Analyst. Your job:
1. Verify each insight — does the source material support it?
2. Add context — what's the bigger picture?
3. Cross-reference — do multiple sources converge on the same signal?
4. Flag contradictions — where do sources disagree?
5. Rate confidence more precisely based on evidence quality

Output an updated JSON array with your amendments:
[
  {
    "title": "...",
    "signal": "...",
    "verification": "confirmed|partial|unverified|contradicted",
    "depth_note": "additional context you found",
    "cross_references": ["related signals or sources"],
    "revised_confidence": 0.0-1.0,
    "category": "...",
    "tags": ["..."]
  }
]""",
    temperature=0.3,
)

STRATEGIST = AgentRole(
    name="Strategist",
    role="strategist",
    goal="Identify actionable intelligence and strategic implications",
    backstory="You are a bold strategist who turns signal into action.",
    model_preference="grok",
    system_prompt="""You are the Strategist for NARTIX Intelligence Council.

You receive verified insights from the Researcher. Your job:
1. Prioritize — which insights matter most RIGHT NOW?
2. Identify actions — what should NATRIX do about each one?
3. Assess risk — what are the downside scenarios?
4. Find opportunities — what advantages can be seized?
5. Time-bound — when must action be taken?

Output:
{
  "priority_insights": [
    {
      "title": "...",
      "action": "specific recommended action",
      "urgency": "immediate|this_week|this_month",
      "risk_if_ignored": "what happens if we don't act",
      "opportunity_value": "low|medium|high|critical",
      "confidence": 0.0-1.0
    }
  ],
  "strategic_assessment": "2-3 sentence overall assessment",
  "top_risk": "single biggest risk identified",
  "top_opportunity": "single biggest opportunity identified"
}""",
    temperature=0.5,
)

SYNTHESIZER = AgentRole(
    name="Synthesizer",
    role="synthesizer",
    goal="Produce final coherent synthesis from all agent outputs",
    backstory="You weave multiple perspectives into clear, actionable intelligence.",
    model_preference="claude",
    system_prompt="""You are the Synthesizer for NARTIX Intelligence Council.

You receive outputs from the Analyst, Researcher, and Strategist.
Your job: produce the FINAL council output.

Output JSON matching this schema:
{
  "summary": "2-3 sentence executive summary",
  "insights": [
    {
      "title": "...",
      "description": "2-3 sentences",
      "category": "content|market|geopolitical|tech|music|culture|alt-science|gaming",
      "confidence": 0.0-1.0,
      "tags": ["..."],
      "actionable": true/false,
      "action_suggestion": "..."
    }
  ],
  "cross_patterns": "themes across all sources",
  "convergence": "where independent signals agree",
  "dissent": "where agents disagreed and why"
}

Quality bar: every insight must pass the "so what?" test.
If it doesn't lead to understanding or action, cut it.""",
    temperature=0.3,
)


# ── API Backends ──────────────────────────────────────────────────────────

# Keys are read fresh inside each function to support rotation without restart.
# Do NOT cache them at module level.

import httpx as _httpx

# Shared HTTP clients — lazily created on first use so they are instantiated
# inside a running event loop.  Call close_shared_clients() on shutdown.
_claude_client: Optional[_httpx.AsyncClient] = None
_grok_client: Optional[_httpx.AsyncClient] = None
_ollama_client: Optional[_httpx.AsyncClient] = None
_client_lock: asyncio.Lock | None = None  # bootstrapped on first access


def _get_client_lock() -> asyncio.Lock:
    """Return (and lazily create) the module-level asyncio lock."""
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def _get_claude_client() -> _httpx.AsyncClient:
    global _claude_client
    if _claude_client is None:
        async with _get_client_lock():
            if _claude_client is None:
                _claude_client = _httpx.AsyncClient(timeout=120.0)
    return _claude_client


async def _get_grok_client() -> _httpx.AsyncClient:
    global _grok_client
    if _grok_client is None:
        async with _get_client_lock():
            if _grok_client is None:
                _grok_client = _httpx.AsyncClient(timeout=120.0)
    return _grok_client


async def _get_ollama_client() -> _httpx.AsyncClient:
    global _ollama_client
    if _ollama_client is None:
        async with _get_client_lock():
            if _ollama_client is None:
                _ollama_client = _httpx.AsyncClient(timeout=300.0)
    return _ollama_client


async def close_shared_clients() -> None:
    """Close all shared HTTP clients. Call this on application shutdown."""
    global _claude_client, _grok_client, _ollama_client
    if _claude_client is not None:
        await _claude_client.aclose()
        _claude_client = None
    if _grok_client is not None:
        await _grok_client.aclose()
        _grok_client = None
    if _ollama_client is not None:
        await _ollama_client.aclose()
        _ollama_client = None


async def _call_claude(system: str, prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Call Anthropic Claude API."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        return ""
    try:
        client = await _get_claude_client()
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": os.getenv("COUNCIL_CLAUDE_MODEL", "claude-sonnet-4-6"),
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as e:
        log.warning(f"Claude call failed: {e}")
        return ""


async def _call_grok(system: str, prompt: str, temperature: float = 0.5, max_tokens: int = 4096) -> str:
    """Call xAI Grok API."""
    xai_key = os.getenv("XAI_API_KEY", "")
    if not xai_key:
        return ""
    try:
        client = await _get_grok_client()
        resp = await client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {xai_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("COUNCIL_GROK_MODEL", "grok-4"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"Grok call failed: {e}")
        return ""


async def _call_ollama(system: str, prompt: str, temperature: float = 0.4, max_tokens: int = 4096) -> str:
    """Call local Ollama."""
    try:
        model = os.getenv("OLLAMA_COUNCIL_MODEL", "qwen3:32b")
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        client = await _get_ollama_client()
        resp = await client.post(
            f"{ollama_host}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        log.warning(f"Ollama call failed: {e}")
        return ""


_MEMBER_RESPONSE_TIMEOUT = 30.0   # seconds per backend attempt (per spec)
_AGENT_TOTAL_TIMEOUT = 120.0      # total budget for all backend fallbacks


async def _call_agent(
    agent: AgentRole,
    prompt: str,
    per_agent_timeout: float = _AGENT_TOTAL_TIMEOUT,
) -> tuple[str, str]:
    """
    Call an agent using its preferred model with fallback chain.

    Each individual backend call is capped at _MEMBER_RESPONSE_TIMEOUT (30s).
    The overall agent (all fallbacks combined) is capped at per_agent_timeout.
    If a member times out or errors, the next backend is tried automatically.

    Args:
        agent: AgentRole definition.
        prompt: Full prompt (source material + accumulated context).
        per_agent_timeout: Wall-clock seconds before the entire agent
            (including all backend fallbacks) is abandoned.

    Returns:
        (response_text, model_used) — ("", "none") if all backends fail.
    """
    import time
    start = time.monotonic()

    # Build preference-ordered backend list
    backends: list[tuple[str, Callable[..., Awaitable[str]]]] = []
    if agent.model_preference == "grok":
        backends = [("grok", _call_grok), ("claude", _call_claude), ("ollama", _call_ollama)]
    elif agent.model_preference == "claude":
        backends = [("claude", _call_claude), ("grok", _call_grok), ("ollama", _call_ollama)]
    else:
        backends = [("ollama", _call_ollama), ("claude", _call_claude), ("grok", _call_grok)]

    for model_name, call_fn in backends:
        # Respect overall per-agent timeout — skip backend if time is already up.
        elapsed = time.monotonic() - start
        if elapsed >= per_agent_timeout:
            log.warning(
                "[%s] per-agent timeout (%.1fs) reached — skipping remaining backends",
                agent.name,
                per_agent_timeout,
            )
            break

        remaining = per_agent_timeout - elapsed
        # Cap each individual backend at _MEMBER_RESPONSE_TIMEOUT (30s)
        backend_timeout = min(remaining, _MEMBER_RESPONSE_TIMEOUT)
        try:
            result = await asyncio.wait_for(
                call_fn(
                    system=agent.system_prompt,
                    prompt=prompt,
                    temperature=agent.temperature,
                    max_tokens=agent.max_tokens,
                ),
                timeout=backend_timeout,
            )
        except asyncio.TimeoutError:
            log.warning(
                "[%s] %s timed out after %.1fs — trying next backend",
                agent.name,
                model_name,
                backend_timeout,
            )
            continue
        except Exception as e:
            log.warning(
                "[%s] %s raised an error: %s — trying next backend",
                agent.name,
                model_name,
                e,
            )
            continue

        if result:
            total_elapsed = time.monotonic() - start
            log.info(
                "[%s] responded via %s in %.1fs (%d chars)",
                agent.name,
                model_name,
                total_elapsed,
                len(result),
            )
            return result, model_name

    log.error("[%s] ALL backends failed or timed out", agent.name)
    return "", "none"


# ── JSON Extraction Helper ────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any] | list:
    """
    Robustly extract a JSON object or array from LLM output.

    Strategy:
    1. Try parsing the raw text directly.
    2. Find the first '{' or '[' and match braces/brackets to locate the
       JSON substring (handles nested code fences that break split-based approaches).
    3. Return {} on failure.
    """
    stripped = text.strip()

    # Fast path — entire response is valid JSON
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Find first { or [ and attempt to match balanced braces
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = stripped.find(start_char)
        if start_idx == -1:
            continue
        depth = 0
        in_string = False
        escape_next = False
        for i in range(start_idx, len(stripped)):
            ch = stripped[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    candidate = stripped[start_idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        break  # Try next start_char type
        # If we didn't return, try next type

    return {}


# ── Context Size Management ──────────────────────────────────────────────

# Maximum accumulated context size in characters (configurable via env).
_MAX_CONTEXT_CHARS = int(os.environ.get("NCL_ORCHESTRATOR_MAX_CONTEXT", "51200"))  # ~50KB


def _truncate_context(context: str, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    """
    Truncate accumulated context to stay within max_chars.

    Keeps the first section (source material header) and the most recent
    agent outputs, trimming from the middle.
    """
    if len(context) <= max_chars:
        return context

    # Keep first 20% (source material) and last 80% (recent agent outputs)
    head_budget = max_chars // 5
    tail_budget = max_chars - head_budget - 50  # 50 chars for separator

    head = context[:head_budget]
    tail = context[-tail_budget:]
    return head + "\n\n[...context truncated...]\n\n" + tail


# ── Orchestrator Pipeline ─────────────────────────────────────────────────


class CouncilOrchestrator:
    """
    Coordinates multi-agent council analysis pipeline.

    Pipeline: Analyst → Researcher → Strategist → Synthesizer
    Each agent receives the source material + all preceding agent outputs.
    """

    def __init__(self) -> None:
        self.agents = [INSIGHT_ANALYST, DEEP_RESEARCHER, STRATEGIST, SYNTHESIZER]

    async def run(
        self,
        source_material: str,
        session_id: str,
        pipeline: str = "youtube",
    ) -> OrchestratorResult:
        """
        Run the full multi-agent pipeline on source material.

        Args:
            source_material: The content to analyze (transcripts, posts, etc.)
            session_id: Unique session identifier
            pipeline: "youtube" or "x"

        Returns:
            OrchestratorResult with all agent outputs and final synthesis
        """
        import time
        start = time.monotonic()

        result = OrchestratorResult(session_id=session_id, pipeline=pipeline)
        accumulated_context = f"## Source Material\n\n{source_material}\n"

        for agent in self.agents:
            log.info(f"Running agent: {agent.name} ({agent.role})")

            prompt = (
                f"{accumulated_context}\n\n"
                f"--- Your role: {agent.name} ---\n"
                f"Goal: {agent.goal}\n\n"
                f"Produce your output now."
            )

            try:
                response, model_used = await _call_agent(agent, prompt)
            except Exception as e:
                log.error(
                    "Unexpected error from agent %s: %s — continuing pipeline",
                    agent.name,
                    e,
                )
                response, model_used = "", "none"

            output = AgentOutput(
                role=agent.role,
                model_used=model_used,
                content=response,
            )

            # Try to parse structured output
            if response:
                output.structured = _extract_json(response)

                # Add this agent's output to context for next agent
                accumulated_context += (
                    f"\n\n## {agent.name} Output\n\n{response}\n"
                )
                # Prevent unbounded growth
                accumulated_context = _truncate_context(accumulated_context)

            result.agents_run.append(output)
            if model_used != "none":
                result.models_used.append(model_used)

        # Extract final synthesis from the Synthesizer's output
        if result.agents_run:
            synthesizer_output = result.agents_run[-1]
            result.final_synthesis = synthesizer_output.content
            if synthesizer_output.structured:
                result.insights_json = synthesizer_output.structured.get("insights", [])

        result.duration_seconds = time.monotonic() - start
        log.info(
            f"Council orchestrator complete: {len(result.agents_run)} agents, "
            f"{len(result.insights_json)} insights, "
            f"{result.duration_seconds:.1f}s total"
        )
        return result


# ── Convenience function ──────────────────────────────────────────────────

async def run_multi_agent_analysis(
    source_material: str,
    session_id: str,
    pipeline: str = "youtube",
) -> OrchestratorResult:
    """One-liner to run the full orchestrator pipeline."""
    orchestrator = CouncilOrchestrator()
    return await orchestrator.run(source_material, session_id, pipeline)
