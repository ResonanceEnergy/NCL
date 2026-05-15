"""
YouTube Council — AI Analyzer

Takes transcribed videos and produces structured insights using
Claude, Grok, or local Ollama models. This is the "council" reasoning
layer that interprets content and extracts actionable intelligence.

Supports multi-model analysis: Claude for deep synthesis, Grok for
real-time context, Ollama for fast local processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from ..shared.models import (
    CouncilReport, CouncilSource, Insight, SignalCategory, VideoMeta, Transcript,
)

log = logging.getLogger("ncl.councils.youtube.analyzer")

# API config
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# Normalise OLLAMA_HOST: accept '11434', ':11434', '/11434', 'localhost:11434',
# 'http://localhost:11434' or full URLs and always end up with a scheme.
def _normalize_ollama_host(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "http://localhost:11434"
    if raw.startswith(("http://", "https://")):
        return raw.rstrip("/")
    raw = raw.lstrip(":/")  # strip leading ':' or '/'
    if ":" not in raw and raw.isdigit():
        # Bare port number
        raw = f"localhost:{raw}"
    return f"http://{raw}".rstrip("/")


OLLAMA_HOST = _normalize_ollama_host(os.getenv("OLLAMA_HOST", "http://localhost:11434"))

# Per-provider model names (separate so a Claude model name doesn't get sent to Grok).
# Override via env per provider.
CLAUDE_MODEL = os.getenv(
    "YT_COUNCIL_CLAUDE_MODEL",
    os.getenv("COUNCIL_CLAUDE_MODEL", "claude-sonnet-4-20250514"),
)
GROK_MODEL = os.getenv("YT_COUNCIL_GROK_MODEL", "grok-3")
OLLAMA_MODEL = os.getenv("OLLAMA_COUNCIL_MODEL", "qwen3:32b")

# Legacy single-model knob (kept for backwards-compat; routes to the right provider
# based on substring match).
ANALYSIS_MODEL = os.getenv("YT_COUNCIL_MODEL", CLAUDE_MODEL)


ANALYSIS_SYSTEM_PROMPT = """You are the YouTube Council Analyst for NARTIX — Resonance Energy studio.

Your job: analyze transcribed YouTube video content and extract structured insights.

For each video or batch of videos, produce:
1. **Executive Summary** — 2-3 sentence overview of all content processed
2. **Key Insights** — Each insight must have:
   - title: concise headline
   - description: 2-3 sentences explaining the insight
   - category: one of [content, market, geopolitical, tech, music, culture, alt-science, gaming]
   - confidence: 0.0-1.0 how confident you are in this insight
   - tags: relevant keywords for convergence detection
   - actionable: true/false — can NATRIX act on this?
   - action_suggestion: if actionable, what should be done?
3. **Cross-Video Patterns** — themes, contradictions, or convergence across videos
4. **Content Opportunities** — ideas for new content based on gaps or trends

Be specific and data-driven. Don't pad with generic observations. Every insight should pass the "so what?" test — if it doesn't lead to understanding or action, cut it.

Output your analysis as JSON matching this exact schema:
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
  "cross_video_patterns": "string",
  "content_opportunities": "string"
}"""


async def analyze_videos(
    transcribed: list[tuple[dict, Transcript]],
    session_id: str,
) -> CouncilReport:
    """
    Run council analysis on transcribed videos.

    Sends transcripts to the configured AI model for structured analysis,
    then packages results into a CouncilReport.
    """
    if not transcribed:
        log.warning("No transcribed videos to analyze")
        return CouncilReport(
            council_type=CouncilSource.YOUTUBE,
            session_id=session_id,
            summary="No videos available for analysis.",
        )

    # Build the analysis prompt with all transcripts
    prompt_parts = []
    videos: list[VideoMeta] = []
    total_duration = 0.0

    for video_info, transcript in transcribed:
        vid = VideoMeta(
            video_id=video_info.get("video_id", ""),
            title=video_info.get("title", "Untitled"),
            channel=video_info.get("channel", "Unknown"),
            channel_id=video_info.get("channel_id", ""),
            upload_date=video_info.get("upload_date", ""),
            duration_seconds=video_info.get("duration", 0),
            url=video_info.get("url", ""),
            description=video_info.get("description", ""),
            view_count=video_info.get("view_count", 0),
            like_count=video_info.get("like_count", 0),
            tags=video_info.get("tags", []),
            thumbnail_url=video_info.get("thumbnail", ""),
        )
        videos.append(vid)
        total_duration += transcript.duration_seconds

        # Build per-video section
        prompt_parts.append(f"\n## Video: {vid.title}")
        prompt_parts.append(f"Channel: {vid.channel} | Duration: {vid.duration_seconds // 60}m | Views: {vid.view_count:,}")
        prompt_parts.append(f"URL: {vid.url}")
        if vid.description:
            prompt_parts.append(f"Description: {vid.description[:300]}")
        prompt_parts.append(f"\n### Transcript:\n{transcript.timestamped_text[:8000]}")
        if len(transcript.timestamped_text) > 8000:
            prompt_parts.append(f"\n[...transcript truncated, {len(transcript.segments)} total segments...]")

    user_prompt = (
        f"Analyze the following {len(transcribed)} YouTube videos "
        f"({total_duration / 3600:.1f} hours total content):\n"
        + "\n".join(prompt_parts)
    )

    # Call the AI model
    raw_response = await _call_model(user_prompt)

    # Parse structured response
    insights, summary, raw_analysis = _parse_analysis(raw_response)

    report = CouncilReport(
        council_type=CouncilSource.YOUTUBE,
        session_id=session_id,
        sources_processed=len(transcribed),
        total_duration_hours=total_duration / 3600,
        insights=insights,
        summary=summary,
        raw_analysis=raw_analysis,
        videos=videos,
    )

    log.info(
        f"YouTube Council analysis complete: {len(insights)} insights "
        f"from {len(transcribed)} videos ({total_duration / 3600:.1f}h)"
    )
    return report


async def _call_model(user_prompt: str) -> str:
    """Call AI model(s) with provider fallback chain.

    Order: Anthropic Claude → xAI Grok → local Ollama. Each provider is only
    attempted if its credential is present. Returns the first non-empty
    response. Empty string only if every provider fails.
    """
    last_error: Optional[Exception] = None

    if ANTHROPIC_API_KEY:
        try:
            text = await _call_anthropic(user_prompt)
            if text:
                return text
        except Exception as e:
            last_error = e
            log.warning(f"Anthropic provider failed, falling through: {e}")

    if XAI_API_KEY:
        try:
            text = await _call_xai(user_prompt)
            if text:
                return text
        except Exception as e:
            last_error = e
            log.warning(f"xAI provider failed, falling through: {e}")

    try:
        text = await _call_ollama(user_prompt)
        if text:
            return text
    except Exception as e:
        last_error = e
        log.error(f"Ollama provider failed: {e}")

    log.error(
        f"All YouTube council providers failed (last error: {last_error}). "
        f"Check ANTHROPIC_API_KEY/XAI_API_KEY/OLLAMA_HOST=({OLLAMA_HOST})."
    )
    return ""


# Shared HTTP client for YouTube analyzer — avoids connection pool exhaustion
_yt_client: Optional["httpx.AsyncClient"] = None
_yt_client_lock: Optional["asyncio.Lock"] = None


def _get_yt_lock():
    global _yt_client_lock
    if _yt_client_lock is None:
        import asyncio
        _yt_client_lock = asyncio.Lock()
    return _yt_client_lock


async def _get_yt_client():
    global _yt_client
    import httpx
    import asyncio
    if _yt_client is None or _yt_client.is_closed:
        async with _get_yt_lock():
            if _yt_client is None or _yt_client.is_closed:
                _yt_client = httpx.AsyncClient(timeout=300.0)
    return _yt_client


async def _call_anthropic(prompt: str) -> str:
    """Call Anthropic Claude API."""
    try:
        client = await _get_yt_client()
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 4096,
                "system": ANALYSIS_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data["content"][0]["text"]
        log.info(f"Anthropic ({CLAUDE_MODEL}) response: {len(text)} chars")
        return text
    except Exception as e:
        log.error(f"Anthropic API ({CLAUDE_MODEL}) failed: {e}")
        raise


async def _call_xai(prompt: str) -> str:
    """Call xAI Grok API (OpenAI-compatible)."""
    try:
        client = await _get_yt_client()
        response = await client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROK_MODEL,
                "messages": [
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 4096,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        log.info(f"xAI ({GROK_MODEL}) response: {len(text)} chars")
        return text
    except Exception as e:
        log.error(f"xAI API ({GROK_MODEL}) failed: {e}")
        raise


async def _call_ollama(prompt: str) -> str:
    """Call Ollama local model."""
    model = OLLAMA_MODEL
    try:
        client = await _get_yt_client()
        response = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=300.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("message", {}).get("content", "")
        log.info(f"Ollama ({model} @ {OLLAMA_HOST}) response: {len(text)} chars")
        return text
    except Exception as e:
        log.error(f"Ollama ({model} @ {OLLAMA_HOST}) failed: {e}")
        raise


def _parse_analysis(raw: str) -> tuple[list[Insight], str, str]:
    """Parse AI model response into structured insights."""
    if not raw:
        return [], "Analysis failed — no model response.", ""

    # Try to extract JSON from the response
    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        log.warning("Could not parse JSON from model response — using raw text")
        return [], raw[:500], raw

    insights: list[Insight] = []
    for item in data.get("insights", []):
        try:
            cat = SignalCategory(item.get("category", "content"))
        except ValueError:
            cat = SignalCategory.CONTENT

        insights.append(Insight(
            title=item.get("title", "Untitled"),
            description=item.get("description", ""),
            category=cat,
            confidence=float(item.get("confidence", 0.5)),
            tags=item.get("tags", []),
            actionable=bool(item.get("actionable", False)),
            action_suggestion=item.get("action_suggestion", ""),
        ))

    summary = data.get("summary", "")
    cross_patterns = data.get("cross_video_patterns", "")
    content_opps = data.get("content_opportunities", "")

    raw_analysis = ""
    if cross_patterns:
        raw_analysis += f"## Cross-Video Patterns\n\n{cross_patterns}\n\n"
    if content_opps:
        raw_analysis += f"## Content Opportunities\n\n{content_opps}\n\n"

    return insights, summary, raw_analysis
