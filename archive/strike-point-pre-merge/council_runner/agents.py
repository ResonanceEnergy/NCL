"""Council Runner v1 Agents — Planner, Skeptic, Risk.

Three specialized agents run in parallel, each with a distinct system prompt
and reasoning lens. Results merge into consensus with recorded provenance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional, Any

import httpx

from .models import (
    AgentRole,
    AgentConfig,
    AgentOutput,
    ConsensusResult,
    CouncilRunRecord,
    ReplayConfig,
)

log = logging.getLogger("ncl.council_runner.agents")

# Shared HTTP client — reused across all model calls to avoid connection pool exhaustion.
_shared_http_client: Optional[httpx.AsyncClient] = None
_http_client_lock: Optional[asyncio.Lock] = None


def _get_http_lock() -> asyncio.Lock:
    global _http_client_lock
    if _http_client_lock is None:
        _http_client_lock = asyncio.Lock()
    return _http_client_lock


async def _get_http_client() -> httpx.AsyncClient:
    """Return (and lazily create) the shared httpx client for council_runner."""
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        async with _get_http_lock():
            if _shared_http_client is None or _shared_http_client.is_closed:
                _shared_http_client = httpx.AsyncClient(timeout=90.0)
    return _shared_http_client


async def close_council_runner_client() -> None:
    """Close the shared HTTP client. Call on application shutdown."""
    global _shared_http_client
    if _shared_http_client is not None:
        await _shared_http_client.aclose()
        _shared_http_client = None


# ─────────────────────────────────────────────────────────────────────────────
# Agent Configuration
# ─────────────────────────────────────────────────────────────────────────────


def get_agent_configs() -> dict[AgentRole, AgentConfig]:
    """Return the three agent configurations for the council."""

    return {
        AgentRole.PLANNER: AgentConfig(
            role=AgentRole.PLANNER,
            system_prompt=(
                "You are the Planner agent in the NCL Council. Your role is to create "
                "actionable strategic plans. Given a topic or prompt, produce: "
                "1) A clear objective statement, 2) Step-by-step execution plan, "
                "3) Resource requirements, 4) Timeline estimates, 5) Success criteria. "
                "Be specific and actionable. Output JSON with keys: objective, steps, "
                "resources, timeline, success_criteria, confidence, key_points."
            ),
            model_preference="claude",
            temperature=0.3,
            max_tokens=4096,
        ),
        AgentRole.SKEPTIC: AgentConfig(
            role=AgentRole.SKEPTIC,
            system_prompt=(
                "You are the Skeptic agent in the NCL Council. Your role is to challenge "
                "assumptions, identify weaknesses, and stress-test proposals. Given a topic "
                "or prompt, produce: 1) Assumptions being made, 2) Potential failure modes, "
                "3) Counter-arguments, 4) What's being overlooked, 5) Alternative interpretations. "
                "Be constructively critical. Output JSON with keys: assumptions, failure_modes, "
                "counter_arguments, overlooked, alternatives, confidence, dissent_notes."
            ),
            model_preference="grok",
            temperature=0.5,
            max_tokens=4096,
        ),
        AgentRole.RISK: AgentConfig(
            role=AgentRole.RISK,
            system_prompt=(
                "You are the Risk Assessment agent in the NCL Council. Your role is to evaluate "
                "risks, quantify exposure, and recommend mitigations. Given a topic or prompt, "
                "produce: 1) Risk inventory (each with likelihood 1-5 and impact 1-5), "
                "2) Overall risk score, 3) Mitigation strategies, 4) Monitoring triggers "
                "(what to watch for), 5) Worst-case scenario analysis. Output JSON with keys: "
                "risks (list of {name, likelihood, impact, mitigation}), overall_risk_score, "
                "monitoring_triggers, worst_case, confidence, risk_flags."
            ),
            model_preference="grok",
            temperature=0.4,
            max_tokens=4096,
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Model Calling (Claude → Grok → Ollama Fallback)
# ─────────────────────────────────────────────────────────────────────────────


async def _call_model(
    prompt: str,
    system_prompt: str,
    model_preference: str,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    replay_seed: Optional[str] = None,
) -> tuple[str, str]:
    """
    Call an LLM with fallback chain: Claude → Grok → Ollama.

    Returns: (response_text, model_used)
    """
    http_client = await _get_http_client()

    # Try Claude first
    if model_preference in ("claude", "default"):
        try:
            response = await _call_claude(
                http_client, prompt, system_prompt, temperature, max_tokens
            )
            return response, "claude-sonnet-4-20250514"
        except Exception as e:
            log.warning(f"Claude call failed, trying Grok: {e}")

    # Try Grok second
    if model_preference in ("grok", "default"):
        try:
            response = await _call_grok(
                http_client, prompt, system_prompt, temperature, max_tokens
            )
            return response, "grok-3"
        except Exception as e:
            log.warning(f"Grok call failed, trying Ollama: {e}")

    # Try Ollama last (local fallback)
    try:
        response = await _call_ollama(
            http_client, prompt, system_prompt, temperature, max_tokens
        )
        return response, "qwen3:32b"
    except Exception as e:
        log.error(f"All model calls failed: {e}")
        raise


async def _call_claude(
    http_client: httpx.AsyncClient,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Call Claude API."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    from ..cost_tracker import check_budget, record_cost
    if not await check_budget("anthropic", 0.25):
        raise RuntimeError("Anthropic daily budget exceeded")

    response = await http_client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()

    usage = data.get("usage", {})
    input_t = usage.get("input_tokens", 0)
    output_t = usage.get("output_tokens", 0)
    cost = (input_t / 1000 * 0.003) + (output_t / 1000 * 0.015)
    await record_cost("anthropic", cost, "council_runner",
                      f"claude-sonnet in={input_t} out={output_t}",
                      model="claude-sonnet-4-20250514", input_tokens=input_t, output_tokens=output_t)

    return data["content"][0]["text"]


async def _call_grok(
    http_client: httpx.AsyncClient,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Call Grok API (via xAI)."""
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY not set")

    from ..cost_tracker import check_budget, record_cost
    if not await check_budget("xai", 0.10):
        raise RuntimeError("xAI daily budget exceeded")

    response = await http_client.post(
        "https://api.x.ai/v1/chat/completions",
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        json={
            "model": "grok-3",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()

    usage = data.get("usage", {})
    input_t = usage.get("prompt_tokens", 0)
    output_t = usage.get("completion_tokens", 0)
    cost = (input_t / 1000 * 0.005) + (output_t / 1000 * 0.015)
    await record_cost("xai", cost, "council_runner",
                      f"grok-3 in={input_t} out={output_t}",
                      model="grok-3", input_tokens=input_t, output_tokens=output_t)

    return data["choices"][0]["message"]["content"]


async def _call_ollama(
    http_client: httpx.AsyncClient,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Call Ollama local API."""
    ollama_host = os.getenv("OLLAMA_HOST", "localhost:11434")

    response = await http_client.post(
        f"http://{ollama_host}/api/generate",
        json={
            "model": "qwen3:32b",
            "prompt": f"{system_prompt}\n\n{prompt}",
            "temperature": temperature,
            "stream": False,
        },
    )
    response.raise_for_status()
    data = response.json()
    return data.get("response", "")


# ─────────────────────────────────────────────────────────────────────────────
# Agent Execution
# ─────────────────────────────────────────────────────────────────────────────


async def run_agent(
    config: AgentConfig,
    prompt: str,
    context: Optional[dict] = None,
    replay_seed: Optional[str] = None,
) -> AgentOutput:
    """
    Execute a single agent (Planner, Skeptic, or Risk).

    Calls the LLM, parses JSON response, extracts structured outputs,
    and records metadata (duration, model used, token count).
    """
    start_time = time.time()

    try:
        # Build the full prompt with context if provided
        full_prompt = prompt
        if context:
            full_prompt = f"CONTEXT:\n{json.dumps(context, indent=2)}\n\nPROMPT:\n{prompt}"

        # Call the model
        response_text, model_used = await _call_model(
            full_prompt,
            config.system_prompt,
            config.model_preference,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            replay_seed=replay_seed,
        )

        # Attempt to extract JSON from response
        parsed_output = {}
        try:
            # Look for JSON block in response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_text = response_text[json_start:json_end]
                parsed_output = json.loads(json_text)
        except (json.JSONDecodeError, ValueError):
            log.warning(
                f"Could not parse JSON from {config.role.value} agent response"
            )

        # Extract standard fields from parsed output
        key_points = parsed_output.get("key_points", [])
        if isinstance(key_points, str):
            key_points = [key_points]

        dissent_notes = parsed_output.get("dissent_notes", [])
        if isinstance(dissent_notes, str):
            dissent_notes = [dissent_notes]

        risk_flags = parsed_output.get("risk_flags", [])
        if isinstance(risk_flags, str):
            risk_flags = [risk_flags]

        confidence = float(parsed_output.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence / 100.0 if confidence > 1 else confidence))

        duration_ms = int((time.time() - start_time) * 1000)

        return AgentOutput(
            role=config.role,
            response_text=response_text,
            confidence=confidence,
            key_points=key_points,
            dissent_notes=dissent_notes,
            risks_identified=risk_flags,
            duration_ms=duration_ms,
            model_used=model_used,
            token_count=len(response_text.split()),  # Rough estimate
        )

    except Exception as e:
        log.error(f"Agent {config.role.value} failed: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Parallel Council Execution
# ─────────────────────────────────────────────────────────────────────────────


def _generate_replay_seed(prompt: str, timestamp: Optional[str] = None) -> str:
    """Generate a deterministic seed for replay."""
    import hashlib

    seed_input = f"{prompt}:{timestamp or ''}"
    return hashlib.sha256(seed_input.encode()).hexdigest()[:16]


def _synthesize_consensus(outputs: list[AgentOutput]) -> ConsensusResult:
    """
    Merge three agent outputs into consensus result.

    Finds agreement, dissent, risk flags, and generates consensus score.
    """
    all_key_points = []
    all_dissent = []
    all_risks = []
    confidences = []

    for output in outputs:
        all_key_points.extend(output.key_points)
        all_dissent.extend(output.dissent_notes)
        all_risks.extend(output.risks_identified)
        confidences.append(output.confidence)

    # Find agreement: points appearing in 2+ agents
    point_counts = {}
    for point in all_key_points:
        point_counts[point] = point_counts.get(point, 0) + 1

    agreement_areas = [point for point, count in point_counts.items() if count >= 2]
    dissent_areas = list(set(all_dissent))  # Deduplicate
    risk_flags = list(set(all_risks))  # Deduplicate

    # Consensus score based on confidence overlap
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
    agreement_ratio = len(agreement_areas) / max(len(all_key_points), 1)
    consensus_score = int((avg_confidence * 0.6 + agreement_ratio * 0.4) * 100)

    # Build consensus text from agreement areas
    consensus_text = "Consensus areas: " + "; ".join(agreement_areas) if agreement_areas else "Limited agreement"

    # Recommendations: merge from all outputs (simplified)
    recommendations = []
    for output in outputs:
        if output.role == AgentRole.PLANNER:
            # Extract from planner's steps
            try:
                parsed = json.loads(
                    output.response_text[
                        output.response_text.find("{") : output.response_text.rfind("}") + 1
                    ]
                )
                if "steps" in parsed:
                    recommendations.extend(parsed["steps"][:2])
            except (json.JSONDecodeError, ValueError):
                pass

    return ConsensusResult(
        consensus_text=consensus_text,
        consensus_score=consensus_score,
        agreement_areas=agreement_areas,
        dissent_areas=dissent_areas,
        risk_flags=risk_flags,
        recommendations=recommendations,
    )


async def run_parallel_council(
    topic: str,
    prompt: str,
    context: Optional[dict] = None,
    replay_config: Optional[ReplayConfig] = None,
) -> CouncilRunRecord:
    """
    Execute all three agents in parallel.

    Runs Planner, Skeptic, and Risk concurrently via asyncio.gather(),
    merges their outputs into consensus, and records full provenance.
    """
    run_id = str(uuid.uuid4())
    start_time = time.time()

    # Generate replay seed if not replaying
    if replay_config:
        replay_seed = replay_config.replay_seed
    else:
        replay_seed = _generate_replay_seed(prompt)

    # Get agent configs
    configs = get_agent_configs()

    # Apply force_models and temperature_override if replaying
    if replay_config:
        for role_str, model in replay_config.force_models.items():
            try:
                role = AgentRole(role_str)
                configs[role].model_preference = model
            except ValueError:
                pass

        if replay_config.temperature_override is not None:
            for config in configs.values():
                config.temperature = replay_config.temperature_override

    # Run all three agents in parallel
    tasks = [
        run_agent(
            configs[role],
            prompt,
            context=context,
            replay_seed=replay_seed,
        )
        for role in [AgentRole.PLANNER, AgentRole.SKEPTIC, AgentRole.RISK]
    ]

    agent_outputs = await asyncio.gather(*tasks, return_exceptions=False)

    # Synthesize consensus
    consensus = _synthesize_consensus(agent_outputs)

    # Build provenance
    provenance = {
        "agents_run": [
            {
                "role": o.role.value,
                "model": o.model_used,
                "duration_ms": o.duration_ms,
                "token_count": o.token_count,
            }
            for o in agent_outputs
        ],
        "replay": replay_config is not None,
        "replay_seed": replay_seed,
    }

    # Build snapshot for deterministic replay
    snapshot = {
        "topic": topic,
        "prompt": prompt,
        "context": context or {},
        "seed": replay_seed,
        "models_used": {o.role.value: o.model_used for o in agent_outputs},
        "temperatures": {role.value: configs[role].temperature for role in configs},
    }

    total_duration_ms = int((time.time() - start_time) * 1000)

    return CouncilRunRecord(
        run_id=run_id,
        topic=topic,
        prompt=prompt,
        agent_outputs=agent_outputs,
        consensus=consensus,
        provenance=provenance,
        replay_seed=replay_seed,
        snapshot=snapshot,
        total_duration_ms=total_duration_ms,
    )
