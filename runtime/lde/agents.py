"""
LDE Multi-Agent Pipeline — Insight Extractor → Analyzer → Doctrine Updater.

Three specialized agents collaborate in sequence:
    1. Insight Extractor: Pulls pure trading signals from transcripts/text
    2. Sandbox Analyzer: Cross-references new insights against ALL prior data
    3. Doctrine Guardian: Updates the Living Trading Doctrine

Each agent uses Claude → Grok → Ollama fallback chain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

import httpx


log = logging.getLogger("ncl.lde.agents")

# API keys
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
XAI_KEY = os.getenv("XAI_API_KEY", "")

# Shared HTTP client for LDE agent calls — avoids connection pool exhaustion
_lde_client: Optional[httpx.AsyncClient] = None
_lde_client_lock: Optional[asyncio.Lock] = None


def _get_lde_lock() -> asyncio.Lock:
    global _lde_client_lock
    if _lde_client_lock is None:
        _lde_client_lock = asyncio.Lock()
    return _lde_client_lock


async def _get_lde_client() -> httpx.AsyncClient:
    global _lde_client
    if _lde_client is None or _lde_client.is_closed:
        async with _get_lde_lock():
            if _lde_client is None or _lde_client.is_closed:
                _lde_client = httpx.AsyncClient(timeout=300.0)
    return _lde_client


def _normalize_ollama_host(raw: str) -> str:
    """Accept '11434', ':11434', 'localhost:11434', or full URL; return scheme'd URL."""
    raw = (raw or "").strip()
    if not raw:
        return "http://localhost:11434"
    if raw.startswith(("http://", "https://")):
        return raw.rstrip("/")
    raw = raw.lstrip(":/")
    if ":" not in raw and raw.isdigit():
        raw = f"localhost:{raw}"
    return f"http://{raw}".rstrip("/")


OLLAMA_HOST = _normalize_ollama_host(os.getenv("OLLAMA_HOST", "http://localhost:11434"))


# ── System Prompts ────────────────────────────────────────────────────────

EXTRACTOR_SYSTEM = """You are the Trading Insight Extractor for the Living Doctrine Engine.

From the provided transcript or article text, extract ONLY trading-relevant insights.
Ignore hype, speculation, and noise. Pull pure signal.

For EACH insight, provide:
- title: concise headline (max 12 words)
- signal: what you specifically observed in the source
- analysis: why this matters for trading (2-3 sentences)
- category: one of [macro, company, sentiment, risk, opportunity, geopolitical, sector, technical, regulatory, correlation]
- confidence: 0-10 (10 = absolute certainty, 5 = moderate, 1 = weak signal)
- urgency: low, medium, high, critical
- tickers: relevant stock/crypto tickers (if any)
- sectors: relevant sectors (if any)
- tags: keywords for cross-referencing

Output ONLY valid JSON array:
[
  {
    "title": "...",
    "signal": "...",
    "analysis": "...",
    "category": "...",
    "confidence": 7.5,
    "urgency": "medium",
    "tickers": ["AAPL", "TSMC"],
    "sectors": ["semiconductors"],
    "tags": ["supply-chain", "chip-shortage"]
  }
]

Rules:
- Every insight must pass the "so what?" test — if it doesn't lead to trading action or understanding, cut it
- Confidence below 3 = not worth including
- Be specific: "Tech stocks may move" is garbage. "TSMC 3nm yield issues could pressure NVDA supply Q3" is signal
- Extract at minimum 3 insights, maximum 15"""  # noqa: E501

ANALYZER_SYSTEM = """You are the Sandbox Analyzer Engine for the Living Doctrine Engine.

You receive:
1. NEW insights just extracted from a fresh URL
2. The CURRENT Living Trading Doctrine (rules, signals, trends, risk thresholds)
3. Recent sandbox history (prior insights)

Your job: REEVALUATE EVERYTHING after this new input.

Produce analysis as JSON:
{
  "cross_references": [
    {
      "new_insight": "title of new insight",
      "existing_connection": "what it connects to in the doctrine",
      "relationship": "confirms|contradicts|extends|supersedes|new_angle",
      "impact": "how this changes the doctrine's understanding"
    }
  ],
  "convergence_signals": [
    "multiple independent sources pointing to the same conclusion"
  ],
  "contradictions": [
    "where new data conflicts with existing doctrine rules"
  ],
  "risk_assessment": {
    "new_risks": ["risks identified from new input"],
    "escalated_risks": ["existing risks that got worse"],
    "mitigated_risks": ["existing risks that got better"]
  },
  "market_bias_shift": "bullish|bearish|neutral|mixed (overall direction after this input)",
  "confidence_delta": "+/-N (how much overall confidence changed)",
  "summary": "2-3 sentence reevaluation summary"
}"""

DOCTRINE_UPDATER_SYSTEM = """You are the Living Doctrine Guardian.

You maintain the Living Trading Doctrine — the single source of truth that evolves with every input.

You receive:
1. The CURRENT doctrine state
2. New insights
3. The Analyzer's reevaluation

Your job: produce SPECIFIC updates to the doctrine. Output JSON:
{
  "new_rules": [
    {
      "title": "rule headline",
      "description": "full rule + rationale",
      "category": "macro|company|sentiment|risk|opportunity|geopolitical|sector|technical|regulatory|correlation",
      "strength": 0-10,
      "tickers": [],
      "action": "what to do based on this rule",
      "expires_at": "YYYY-MM-DD or null"
    }
  ],
  "updated_rules": [
    {
      "rule_id": "existing rule ID to update",
      "changes": {"strength": 8, "description": "updated description"},
      "reason": "why this rule changed"
    }
  ],
  "suspended_rules": [
    {"rule_id": "...", "reason": "why this rule is no longer valid"}
  ],
  "new_signals": [
    {
      "name": "signal name",
      "description": "...",
      "category": "...",
      "direction": "bullish|bearish|neutral",
      "strength": 0-10,
      "tickers": []
    }
  ],
  "new_trends": [
    {
      "name": "trend name",
      "description": "...",
      "category": "...",
      "direction": "emerging|accelerating|peaking|declining|reversing",
      "confidence": 0-10,
      "tickers": [],
      "sectors": [],
      "watch_triggers": ["condition that should trigger action"]
    }
  ],
  "risk_threshold_updates": [
    {"name": "...", "category": "...", "current_level": 7.0, "alert_level": 8.0, "description": "..."}
  ],
  "market_bias": "bullish|bearish|neutral|mixed",
  "confidence_score": 0-10,
  "top_tickers": ["most important tickers right now"],
  "doctrine_summary": "1-2 sentence summary of how the doctrine evolved"
}

Rules:
- NEVER remove history — only add or update
- Rules with 3+ contradicting insights should be SUSPENDED, not deleted
- Confidence must be evidence-based, not vibes
- Every rule needs an ACTION (what to do)
- Be conservative with CRITICAL urgency — only true market-moving events"""  # noqa: E501


# ── API Call Infrastructure ───────────────────────────────────────────────


async def _call_model(
    system: str, prompt: str, temperature: float = 0.3, max_tokens: int = 4096
) -> tuple[str, str]:
    """Call AI model with Claude → Grok → Ollama fallback. Returns (response, model_name)."""

    # Try Claude
    if ANTHROPIC_KEY:
        result = await _call_claude(system, prompt, temperature, max_tokens)
        if result:
            return result, "claude"

    # Try Grok
    if XAI_KEY:
        result = await _call_grok(system, prompt, temperature, max_tokens)
        if result:
            return result, "grok"

    # Try Ollama
    result = await _call_ollama(system, prompt, temperature, max_tokens)
    if result:
        return result, "ollama"

    return "", "none"


async def _call_claude(system: str, prompt: str, temp: float, max_tok: int) -> str:
    """LDE Claude call. W6-D: routed through runtime.llm facade.

    Returns the model's text on success, "" on any error (caller falls
    through to Grok then Ollama). The empty-string-on-error contract is
    preserved verbatim — every existing fallback chain still works.
    """
    try:
        from ..llm import chat as _llm_chat

        result = await _llm_chat(
            model=os.getenv("LDE_CLAUDE_MODEL", "claude-sonnet-4-20250514"),
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=max_tok,
            temperature=temp,
            budget_key="anthropic",
            timeout_s=180.0,
        )
        return result.text or ""
    except Exception as e:
        log.warning(f"Claude failed: {e}")
        return ""


async def _call_grok(system: str, prompt: str, temp: float, max_tok: int) -> str:
    try:
        client = await _get_lde_client()
        resp = await client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {XAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("LDE_GROK_MODEL", "grok-4"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tok,
                "temperature": temp,
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"Grok failed: {e}")
        return ""


async def _call_ollama(system: str, prompt: str, temp: float, max_tok: int) -> str:
    try:
        model = os.getenv("LDE_OLLAMA_MODEL", "qwen3:32b")
        client = await _get_lde_client()
        resp = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": temp, "num_predict": max_tok},
            },
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        log.warning(f"Ollama failed: {e}")
        return ""


def _parse_json_response(raw: str) -> Any:
    """Extract JSON from an AI model response (handles markdown fences)."""
    if not raw:
        return None
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array or object in the text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start_idx = text.find(start_char)
            end_idx = text.rfind(end_char)
            if start_idx >= 0 and end_idx > start_idx:
                try:
                    return json.loads(text[start_idx : end_idx + 1])
                except json.JSONDecodeError:
                    continue
        log.warning(f"Could not parse JSON from response ({len(raw)} chars)")
        return None


# ── Agent Functions ───────────────────────────────────────────────────────


async def extract_insights(
    text: str,
    url: str,
    source_type: str = "",
) -> list[dict]:
    """
    Agent 1: Insight Extractor.

    Takes raw text (transcript/article) and extracts trading insights.
    """
    start = time.monotonic()

    prompt = (
        f"Source URL: {url}\n"
        f"Source type: {source_type}\n\n"
        f"Content to analyze:\n{text[:15000]}"
    )
    if len(text) > 15000:
        prompt += f"\n\n[...truncated, {len(text)} total chars...]"

    response, model = await _call_model(EXTRACTOR_SYSTEM, prompt, temperature=0.4)
    elapsed = time.monotonic() - start

    insights = _parse_json_response(response)
    if not isinstance(insights, list):
        insights = []

    log.info(f"[Extractor] {len(insights)} insights via {model} in {elapsed:.1f}s")
    return insights


async def analyze_against_sandbox(
    new_insights: list[dict],
    doctrine: dict,
    recent_history: list[dict] | None = None,
) -> dict:
    """
    Agent 2: Sandbox Analyzer.

    Cross-references new insights against the full doctrine and history.
    """
    start = time.monotonic()

    # Build context
    prompt_parts = [
        "## NEW INSIGHTS (just extracted)\n",
        json.dumps(new_insights, indent=2, default=str),
        "\n\n## CURRENT LIVING DOCTRINE\n",
        json.dumps(
            {
                "core_rules": doctrine.get("core_rules", [])[:20],
                "active_signals": doctrine.get("active_signals", [])[:15],
                "monitored_trends": doctrine.get("monitored_trends", [])[:10],
                "risk_thresholds": doctrine.get("risk_thresholds", []),
                "market_bias": doctrine.get("market_bias", "neutral"),
                "confidence_score": doctrine.get("confidence_score", 5.0),
                "urls_processed": doctrine.get("urls_processed", 0),
            },
            indent=2,
            default=str,
        ),
    ]

    if recent_history:
        prompt_parts.append("\n\n## RECENT SANDBOX HISTORY (last 5 inputs)\n")
        for entry in recent_history[-5:]:
            prompt_parts.append(
                f"- [{entry.get('processed_at', '?')}] {entry.get('source_url', '?')}: "
                f"{len(entry.get('insights', []))} insights"
            )

    prompt = "\n".join(prompt_parts)
    response, model = await _call_model(ANALYZER_SYSTEM, prompt, temperature=0.3)
    elapsed = time.monotonic() - start

    analysis = _parse_json_response(response)
    if not isinstance(analysis, dict):
        analysis = {
            "summary": response[:500] if response else "Analysis failed",
            "cross_references": [],
        }

    log.info(
        f"[Analyzer] via {model} in {elapsed:.1f}s — bias: {analysis.get('market_bias_shift', '?')}"
    )
    return analysis


async def update_doctrine(
    doctrine: dict,
    new_insights: list[dict],
    analysis: dict,
) -> dict:
    """
    Agent 3: Doctrine Guardian.

    Produces specific updates to apply to the Living Doctrine.
    """
    start = time.monotonic()

    prompt = (
        f"## CURRENT DOCTRINE STATE\n"
        f"{json.dumps(doctrine, indent=2, default=str)}\n\n"
        f"## NEW INSIGHTS\n"
        f"{json.dumps(new_insights, indent=2, default=str)}\n\n"
        f"## ANALYZER REEVALUATION\n"
        f"{json.dumps(analysis, indent=2, default=str)}\n\n"
        f"Produce your doctrine updates now."
    )

    response, model = await _call_model(
        DOCTRINE_UPDATER_SYSTEM, prompt, temperature=0.3, max_tokens=6000
    )
    elapsed = time.monotonic() - start

    updates = _parse_json_response(response)
    if not isinstance(updates, dict):
        updates = {
            "doctrine_summary": response[:500] if response else "Update failed",
            "new_rules": [],
        }

    log.info(
        f"[Doctrine Guardian] via {model} in {elapsed:.1f}s — "
        f"{len(updates.get('new_rules', []))} new rules, "
        f"{len(updates.get('new_signals', []))} new signals, "
        f"{len(updates.get('new_trends', []))} new trends"
    )
    return updates
