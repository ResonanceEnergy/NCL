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

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
XAI_KEY = os.getenv("XAI_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


async def _call_claude(system: str, prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Call Anthropic Claude API."""
    if not ANTHROPIC_KEY:
        return ""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
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
    if not XAI_KEY:
        return ""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_KEY}",
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
        import httpx
        model = os.getenv("OLLAMA_COUNCIL_MODEL", "qwen3:32b")
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
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


async def _call_agent(agent: AgentRole, prompt: str) -> tuple[str, str]:
    """
    Call an agent using its preferred model with fallback chain.

    Returns (response_text, model_used).
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
        result = await call_fn(
            system=agent.system_prompt,
            prompt=prompt,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
        )
        if result:
            elapsed = time.monotonic() - start
            log.info(f"[{agent.name}] responded via {model_name} in {elapsed:.1f}s ({len(result)} chars)")
            return result, model_name

    log.error(f"[{agent.name}] ALL backends failed")
    return "", "none"


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

            response, model_used = await _call_agent(agent, prompt)

            output = AgentOutput(
                role=agent.role,
                model_used=model_used,
                content=response,
            )

            # Try to parse structured output
            if response:
                try:
                    json_str = response
                    if "```json" in response:
                        json_str = response.split("```json")[1].split("```")[0].strip()
                    elif "```" in response:
                        json_str = response.split("```")[1].split("```")[0].strip()
                    output.structured = json.loads(json_str)
                except (json.JSONDecodeError, IndexError):
                    pass

                # Add this agent's output to context for next agent
                accumulated_context += (
                    f"\n\n## {agent.name} Output\n\n{response}\n"
                )

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
