"""
LLM-based Memory Importance Scorer
====================================

Evaluates each memory unit at write time using a fast LLM (Claude Haiku)
to assign a 1-10 importance score. This front-loads quality assessment
and makes decay more meaningful.

Scoring criteria:
    10: Critical decisions, emergencies, explicit user commands to remember
    8-9: Key decisions, strong preferences, important commitments
    6-7: Useful facts, moderate insights, actionable observations
    4-5: General context, routine observations, background info
    2-3: Transient details, casual mentions, low-signal noise
    1: Pure noise, duplicate information, irrelevant chatter

Falls back to rule-based scoring if the LLM call fails or is unavailable.
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

log = logging.getLogger("ncl.memory.importance_scorer")

# Rule-based scoring patterns (fallback)
_RULE_PATTERNS = [
    # Score 9-10: Explicit remember commands, critical alerts
    (10, [r"remember that", r"don't forget", r"critical:", r"EMERGENCY", r"urgent alert"]),
    (9, [r"decided to", r"committed to", r"approved:", r"final decision"]),
    # Score 7-8: Key facts, decisions
    (8, [r"preference:", r"always use", r"never use", r"important:", r"key finding"]),
    (7, [r"action item", r"deadline:", r"milestone:", r"agreed on", r"consensus:"]),
    # Score 5-6: Useful context
    (6, [r"meeting note", r"discussed:", r"proposed:", r"considering"]),
    (5, [r"update:", r"status:", r"progress:", r"observed:"]),
    # Score 3-4: Background
    (4, [r"mentioned:", r"fyi:", r"note:", r"reference:"]),
    (3, [r"chatter", r"aside:", r"btw"]),
]


def rule_based_score(content: str, source: str = "", tags: list[str] = None) -> float:
    """
    Fast rule-based importance scoring (no LLM needed).

    Returns importance on 1-10 scale.
    """
    content_lower = content.lower()
    tags = tags or []

    # Check patterns from highest to lowest
    for score, patterns in _RULE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, content_lower):
                return float(score)

    # Source-based heuristics
    source_lower = source.lower()
    if "council" in source_lower:
        return 7.0  # Council outputs are generally important
    if "prediction" in source_lower:
        return 6.5
    if "awarebot" in source_lower and any(t in ["critical", "high_priority"] for t in tags):
        return 7.5
    if "awarebot" in source_lower:
        return 5.0
    if "journal" in source_lower:
        return 6.0
    if "user" in source_lower or "natrix" in source_lower:
        return 8.0  # User-provided info is high priority

    return 5.0  # Default: moderate importance


async def llm_importance_score(
    content: str,
    source: str = "",
    tags: list[str] = None,
    timeout: float = 5.0,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[float]:
    """
    Use Claude Haiku to evaluate memory importance on a 1-10 scale.

    Returns None if the LLM call fails (caller should fall back to rule-based).

    Args:
        content: Memory content to evaluate
        source: Source label
        tags: Associated tags
        timeout: Max seconds to wait for LLM response
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.debug("No ANTHROPIC_API_KEY — skipping LLM importance scoring")
        return None

    tags = tags or []

    prompt = f"""Rate the importance of this memory on a scale of 1-10 for a business intelligence system.

Scoring guide:
- 10: Critical decisions, emergencies, explicit commands to remember
- 8-9: Key decisions, strong preferences, important commitments
- 6-7: Useful facts, moderate insights, actionable observations
- 4-5: General context, routine observations
- 2-3: Transient details, low-signal
- 1: Noise, duplicates, irrelevant

Memory:
Source: {source}
Tags: {', '.join(tags[:5])}
Content: {content[:500]}

Respond with ONLY a JSON object: {{"score": N, "type": "episodic|semantic|decision|preference|signal|procedural"}}"""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if resp.status_code != 200:
                log.debug(f"LLM importance scoring HTTP {resp.status_code}")
                return None

            data = resp.json()

            # Track cost
            try:
                from ..cost_tracker import record_cost
                usage = data.get("usage", {})
                input_t = usage.get("input_tokens", 0)
                output_t = usage.get("output_tokens", 0)
                cost_usd = (input_t * 3.00 + output_t * 15.00) / 1_000_000  # Sonnet pricing
                await record_cost("anthropic", cost_usd, "memory_scoring",
                                  f"importance scoring in={input_t} out={output_t}")
            except Exception:
                pass  # Cost tracking should never break the primary flow

            text = data.get("content", [{}])[0].get("text", "")

            # Parse JSON response
            # Strip markdown fences if present
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*", "", text)

            parsed = json.loads(text.strip())
            score = float(parsed.get("score", 5))
            return max(1.0, min(10.0, score))

    except asyncio.TimeoutError:
        log.debug("LLM importance scoring timed out")
        return None
    except Exception as e:
        log.debug(f"LLM importance scoring failed: {e}")
        return None


async def score_memory(
    content: str,
    source: str = "",
    tags: list[str] = None,
    use_llm: bool = True,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """
    Score a memory unit's importance using LLM with rule-based fallback.

    Returns:
        Dict with 'llm_score' (Optional[float]), 'rule_score' (float),
        'final_score' (float on 0-100 scale), and 'memory_type' (str)
    """
    tags = tags or []
    rule_score = rule_based_score(content, source, tags)

    llm_score = None
    memory_type = "episodic"  # default

    if use_llm:
        result = await llm_importance_score(content, source, tags, model=model)
        if result is not None:
            llm_score = result

    # Determine final score (0-100 scale)
    if llm_score is not None:
        # LLM score (1-10) converted to 0-100, weighted 70% LLM / 30% rule
        final = (llm_score * 10 * 0.7) + (rule_score * 10 * 0.3)
    else:
        # Rule-based only: convert 1-10 to 0-100
        final = rule_score * 10

    # Infer memory type from content if LLM didn't provide it
    content_lower = content.lower()
    if any(kw in content_lower for kw in ["decided", "decision", "approved", "committed"]):
        memory_type = "decision"
    elif any(kw in content_lower for kw in ["prefer", "always", "never", "like", "dislike"]):
        memory_type = "preference"
    elif any(kw in content_lower for kw in ["procedure", "workflow", "how to", "step 1"]):
        memory_type = "procedural"
    elif any(kw in content_lower for kw in ["alert", "signal", "trend", "spike", "breaking"]):
        memory_type = "signal"
    elif any(kw in content_lower for kw in ["fact:", "definition:", "means:", "is a"]):
        memory_type = "semantic"

    return {
        "llm_score": llm_score,
        "rule_score": rule_score,
        "final_score": max(0.0, min(100.0, final)),
        "memory_type": memory_type,
    }
