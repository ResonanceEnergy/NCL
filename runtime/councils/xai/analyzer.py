"""
X (Twitter) Council — AI Analyzer

Takes scraped X posts from the full intelligence sweep and produces
structured insights. Handles three signal vectors:
- Account monitoring (what key people are saying)
- Keyword intelligence (what topics are trending in your domains)
- Trending analysis (what's breaking right now)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from ..shared.models import (
    CouncilReport, CouncilSource, Insight, SignalCategory, XPost,
)

log = logging.getLogger("ncl.councils.xai.analyzer")

def _get_anthropic_key() -> str:
    """Lazy-read Anthropic API key so keys set after import are picked up."""
    return os.getenv("ANTHROPIC_API_KEY", "")

def _get_xai_key() -> str:
    """Lazy-read xAI API key so keys set after import are picked up."""
    return os.getenv("XAI_API_KEY", "")


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


def _get_ollama_host() -> str:
    return _normalize_ollama_host(os.getenv("OLLAMA_HOST", "http://localhost:11434"))

ANALYSIS_MODEL = os.getenv("X_COUNCIL_MODEL", "claude-sonnet-4-6")


X_ANALYSIS_SYSTEM_PROMPT = """You are the X (Twitter) Intelligence Analyst for NARTIX — Resonance Energy studio.

Your job: analyze scraped X/Twitter posts across three vectors (tracked accounts, keyword searches, trending topics) and extract structured intelligence.

For each batch of posts, produce:
1. **Executive Summary** — 2-3 sentence overview of the intelligence landscape
2. **Key Insights** — Each must have:
   - title: concise headline
   - description: 2-3 sentences explaining the signal
   - category: one of [content, market, geopolitical, tech, music, culture, alt-science, gaming]
   - confidence: 0.0-1.0
   - tags: keywords for convergence detection
   - actionable: true/false
   - action_suggestion: what NATRIX should do (if actionable)
3. **Sentiment Landscape** — overall mood across the signals
4. **Convergence Signals** — where multiple independent sources point to the same thing
5. **Risk Alerts** — anything that might affect NARTIX operations (market, regulatory, competitive)

Focus on signal, not noise. A post with 50 likes from an expert matters more than a viral meme. Look for:
- Information asymmetry (what do insiders know that the market doesn't?)
- Narrative shifts (is the conversation changing direction?)
- Actionable intelligence (trade signals, content opportunities, partnership leads)

Output as JSON:
{
  "summary": "string",
  "insights": [
    {
      "title": "string",
      "description": "string",
      "category": "content|market|geopolitical|tech|music|culture|alt-science|gaming",
      "confidence": 0.85,
      "tags": ["tag1", "tag2"],
      "actionable": true,
      "action_suggestion": "string or empty"
    }
  ],
  "sentiment_landscape": "string",
  "convergence_signals": "string",
  "risk_alerts": "string"
}"""


async def analyze_posts(
    sweep_results: dict[str, list[XPost]],
    session_id: str,
) -> CouncilReport:
    """
    Run council analysis on scraped X posts.

    Args:
        sweep_results: Dict with keys 'accounts', 'keywords', 'trending'
        session_id: Unique session identifier
    """
    all_posts: list[XPost] = []
    for posts in sweep_results.values():
        all_posts.extend(posts)

    # Count synthetic (Grok-generated) posts for confidence adjustment
    synthetic_count = sum(1 for p in all_posts if p.synthetic)
    real_count = len(all_posts) - synthetic_count
    if synthetic_count > 0:
        log.info(
            f"Post mix: {real_count} real + {synthetic_count} synthetic (Grok-generated). "
            f"Synthetic data will reduce insight confidence scores."
        )

    if not all_posts:
        log.warning("No posts to analyze")
        return CouncilReport(
            council_type=CouncilSource.X_TWITTER,
            session_id=session_id,
            summary="No X posts collected for analysis.",
        )

    # Build analysis prompt organized by vector
    prompt_parts = [
        f"Analyze the following X/Twitter intelligence sweep ({len(all_posts)} total posts):\n"
    ]

    # Vector 1: Tracked accounts
    account_posts = sweep_results.get("accounts", [])
    if account_posts:
        prompt_parts.append(f"\n## VECTOR 1: Tracked Accounts ({len(account_posts)} posts)\n")
        by_author: dict[str, list[XPost]] = {}
        for p in account_posts:
            by_author.setdefault(p.author_handle, []).append(p)
        for handle, posts in sorted(by_author.items()):
            prompt_parts.append(f"\n### @{handle} ({len(posts)} posts)")
            for p in posts[:10]:
                engagement = p.like_count + p.retweet_count
                prompt_parts.append(f"- [{p.created_at[:16]}] {p.text[:300]} (engagement: {engagement})")

    # Vector 2: Keyword search results
    keyword_posts = sweep_results.get("keywords", [])
    if keyword_posts:
        prompt_parts.append(f"\n## VECTOR 2: Keyword Intelligence ({len(keyword_posts)} posts)\n")
        for p in keyword_posts[:30]:
            engagement = p.like_count + p.retweet_count
            prompt_parts.append(f"- @{p.author_handle}: {p.text[:300]} (engagement: {engagement})")

    # Vector 3: Trending
    trending_posts = sweep_results.get("trending", [])
    if trending_posts:
        prompt_parts.append(f"\n## VECTOR 3: Trending Topics ({len(trending_posts)} posts)\n")
        for p in trending_posts[:20]:
            engagement = p.like_count + p.retweet_count
            prompt_parts.append(f"- @{p.author_handle}: {p.text[:300]} (engagement: {engagement})")

    user_prompt = "\n".join(prompt_parts)

    # Call AI model
    raw_response = await _call_model(user_prompt)

    # Parse
    insights, summary, raw_analysis = _parse_analysis(raw_response)

    # Penalize confidence when insights are derived from synthetic (Grok-generated) data.
    # 100% synthetic => 0.6x confidence cap; mixed => proportional reduction.
    if synthetic_count > 0 and all_posts:
        synthetic_ratio = synthetic_count / len(all_posts)
        confidence_penalty = 1.0 - (0.4 * synthetic_ratio)  # 0.6 at 100% synthetic
        for insight in insights:
            original = insight.confidence
            insight.confidence = round(min(insight.confidence, insight.confidence * confidence_penalty), 2)
            if insight.confidence != original:
                if "synthetic_data" not in insight.tags:
                    insight.tags.append("synthetic_data")
        log.info(
            f"Applied synthetic confidence penalty: {confidence_penalty:.2f}x "
            f"({synthetic_ratio:.0%} synthetic ratio)"
        )

    report = CouncilReport(
        council_type=CouncilSource.X_TWITTER,
        session_id=session_id,
        sources_processed=len(all_posts),
        insights=insights,
        summary=summary,
        raw_analysis=raw_analysis,
        posts=all_posts,
    )

    log.info(f"X Council analysis complete: {len(insights)} insights from {len(all_posts)} posts")
    return report


_analyzer_client: "httpx.AsyncClient | None" = None
_analyzer_client_lock: "asyncio.Lock | None" = None


def _get_analyzer_lock():
    global _analyzer_client_lock
    if _analyzer_client_lock is None:
        import asyncio
        _analyzer_client_lock = asyncio.Lock()
    return _analyzer_client_lock


async def _get_analyzer_client():
    """Shared HTTP client for X analyzer — avoids connection pool exhaustion."""
    global _analyzer_client
    import httpx
    import asyncio
    if _analyzer_client is None or _analyzer_client.is_closed:
        async with _get_analyzer_lock():
            if _analyzer_client is None or _analyzer_client.is_closed:
                _analyzer_client = httpx.AsyncClient(timeout=300.0)
    return _analyzer_client


async def _call_model(user_prompt: str) -> str:
    """Call configured AI model for X analysis."""
    client = await _get_analyzer_client()

    # Anthropic Claude
    anthropic_key = _get_anthropic_key()
    xai_key = _get_xai_key()
    if anthropic_key and "claude" in ANALYSIS_MODEL.lower():
        try:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANALYSIS_MODEL,
                    "max_tokens": 4096,
                    "system": X_ANALYSIS_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()

            # Track cost
            try:
                from ...cost_tracker import record_cost
                usage = data.get("usage", {})
                input_t = usage.get("input_tokens", 0)
                output_t = usage.get("output_tokens", 0)
                cost_usd = (input_t * 3.0 + output_t * 15.0) / 1_000_000
                await record_cost("anthropic", cost_usd, "x_analysis",
                                  f"x council analysis in={input_t} out={output_t}")
            except Exception:
                pass

            return data["content"][0]["text"]
        except Exception as e:
            log.warning(f"Anthropic failed: {e}")

    # xAI Grok
    if xai_key:
        try:
            model = ANALYSIS_MODEL if "grok" in ANALYSIS_MODEL.lower() else "grok-4"
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {xai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": X_ANALYSIS_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 4096,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()

            # Track cost
            try:
                from ...cost_tracker import record_cost
                usage = data.get("usage", {})
                input_t = usage.get("prompt_tokens", 0)
                output_t = usage.get("completion_tokens", 0)
                cost_usd = (input_t * 2.0 + output_t * 10.0) / 1_000_000
                await record_cost("xai", cost_usd, "x_analysis",
                                  f"grok x council analysis in={input_t} out={output_t}")
            except Exception:
                pass

            return data["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning(f"xAI failed: {e}")

    # Ollama fallback
    try:
        model = os.getenv("OLLAMA_COUNCIL_MODEL", "qwen3:32b")
        resp = await client.post(
            f"{_get_ollama_host()}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": X_ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        log.error(f"All models failed: {e}")
        return ""


def _parse_analysis(raw: str) -> tuple[list[Insight], str, str]:
    """Parse AI response into structured insights."""
    if not raw:
        return [], "Analysis failed — no model response.", ""

    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        log.warning("Could not parse JSON — using raw text")
        return [], raw[:500], raw

    insights: list[Insight] = []
    for item in data.get("insights", []):
        try:
            cat = SignalCategory(item.get("category", "content"))
        except ValueError:
            cat = SignalCategory.CONTENT

        raw_conf = float(item.get("confidence", 0.5))
        insights.append(Insight(
            title=item.get("title", "Untitled"),
            description=item.get("description", ""),
            category=cat,
            confidence=max(0.0, min(1.0, raw_conf)),
            tags=item.get("tags", []),
            actionable=bool(item.get("actionable", False)),
            action_suggestion=item.get("action_suggestion", ""),
        ))

    summary = data.get("summary", "")
    raw_analysis = ""
    for key in ["sentiment_landscape", "convergence_signals", "risk_alerts"]:
        val = data.get(key, "")
        if val:
            header = key.replace("_", " ").title()
            raw_analysis += f"## {header}\n\n{val}\n\n"

    return insights, summary, raw_analysis
