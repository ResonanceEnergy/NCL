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

# API config — lazy-read functions so keys set after import (e.g. by
# keychain helper) are picked up.
def _get_anthropic_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")

def _get_xai_key() -> str:
    return os.getenv("XAI_API_KEY", "")

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

SINGLE_VIDEO_SYSTEM_PROMPT = """You are the YouTube Council Analyst for NARTIX — Resonance Energy studio.

Your job: deeply analyze a SINGLE transcribed YouTube video and extract every actionable insight.

Produce:
1. **Executive Summary** — 2-3 sentence overview of the video's content and significance
2. **Key Insights** — Extract ALL meaningful insights. Each must have:
   - title: concise headline
   - description: 2-3 sentences explaining the insight
   - category: one of [content, market, geopolitical, tech, music, culture, alt-science, gaming]
   - confidence: 0.0-1.0 how confident you are in this insight
   - tags: relevant keywords for convergence detection
   - actionable: true/false — can NATRIX act on this?
   - action_suggestion: if actionable, what should be done?
3. **Key Quotes** — 2-5 notable direct quotes from the video with timestamps
4. **Content Assessment** — quality, credibility, and relevance to NATRIX operations

Be thorough — this is a deep-dive on a single video. Extract more insights than you would in a batch. Every claim, data point, prediction, and recommendation is worth capturing.

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
  "key_quotes": "string",
  "content_assessment": "string"
}"""

ROLLUP_SYSTEM_PROMPT = """You are the YouTube Council Analyst for NARTIX — Resonance Energy studio.

You have already analyzed each video individually. Now synthesize cross-video patterns.

Given summaries and insights from multiple individual video analyses, produce:
1. **Executive Summary** — 2-3 sentence overview of ALL content processed in this session
2. **Cross-Video Patterns** — themes, contradictions, or convergence across videos
3. **Content Opportunities** — ideas for NATRIX content based on gaps or trends
4. **Convergence Signals** — where 2+ videos agree on a trend, prediction, or shift

Output your analysis as JSON:
{
  "summary": "string",
  "cross_video_patterns": "string",
  "content_opportunities": "string",
  "convergence_signals": "string"
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

    # Build the analysis prompt with all transcripts.
    # Dynamically allocate transcript budget based on video count to stay
    # within ~150K chars total prompt (safe for 200K-token context models).
    # Old value was 8,000 chars — that lost 50-70% of most videos.
    TOTAL_TRANSCRIPT_BUDGET = 150_000  # chars across all videos
    n_videos = len(transcribed)
    per_video_budget = max(12_000, TOTAL_TRANSCRIPT_BUDGET // max(n_videos, 1))

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
        text = transcript.timestamped_text
        prompt_parts.append(f"\n### Transcript:\n{text[:per_video_budget]}")
        if len(text) > per_video_budget:
            prompt_parts.append(f"\n[...transcript truncated at {per_video_budget} chars, {len(transcript.segments)} total segments...]")

    user_prompt = (
        f"Analyze the following {len(transcribed)} YouTube videos "
        f"({total_duration / 3600:.1f} hours total content):\n"
        + "\n".join(prompt_parts)
    )

    # Call the AI model
    raw_response = await _call_model(user_prompt)

    # Guard: if all model providers failed, don't save a garbage report
    if not raw_response:
        log.warning(
            "All AI providers returned empty responses — skipping report generation "
            f"for session {session_id} ({len(transcribed)} videos)"
        )
        return CouncilReport(
            council_type=CouncilSource.YOUTUBE,
            session_id=session_id,
            sources_processed=len(transcribed),
            total_duration_hours=total_duration / 3600,
            summary="Analysis failed — all AI providers returned empty responses.",
            videos=videos,
        )

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


async def analyze_single_video(
    video_info: dict,
    transcript: Transcript,
    session_id: str,
) -> CouncilReport:
    """
    Run deep council analysis on a SINGLE video.

    Uses a focused prompt that extracts more insights per video than the
    batch analyzer. Each video gets its own CouncilReport.
    """
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

    # Full transcript budget for a single video — no splitting needed
    text = transcript.timestamped_text
    per_video_budget = 150_000  # full budget for one video

    prompt_parts = [
        f"## Video: {vid.title}",
        f"Channel: {vid.channel} | Duration: {vid.duration_seconds // 60}m | Views: {vid.view_count:,}",
        f"URL: {vid.url}",
    ]
    if vid.description:
        prompt_parts.append(f"Description: {vid.description[:500]}")
    prompt_parts.append(f"\n### Transcript:\n{text[:per_video_budget]}")
    if len(text) > per_video_budget:
        prompt_parts.append(f"\n[...transcript truncated at {per_video_budget} chars, {len(transcript.segments)} total segments...]")

    user_prompt = (
        f"Analyze this YouTube video in depth "
        f"({transcript.duration_seconds / 3600:.1f} hours of content):\n"
        + "\n".join(prompt_parts)
    )

    raw_response = await _call_model(user_prompt, system_prompt=SINGLE_VIDEO_SYSTEM_PROMPT)

    # Guard: if all model providers failed, don't save a garbage report
    if not raw_response:
        log.warning(
            f"All AI providers returned empty responses — skipping report for "
            f"'{vid.title}' (session {session_id})"
        )
        return CouncilReport(
            council_type=CouncilSource.YOUTUBE,
            session_id=session_id,
            sources_processed=1,
            total_duration_hours=transcript.duration_seconds / 3600,
            summary=f"Analysis failed for '{vid.title}' — all AI providers returned empty responses.",
            videos=[vid],
        )

    insights, summary, raw_analysis = _parse_single_video_analysis(raw_response, vid.video_id)

    report = CouncilReport(
        council_type=CouncilSource.YOUTUBE,
        session_id=session_id,
        sources_processed=1,
        total_duration_hours=transcript.duration_seconds / 3600,
        insights=insights,
        summary=summary,
        raw_analysis=raw_analysis,
        videos=[vid],
    )

    log.info(
        f"Single-video analysis complete: '{vid.title}' — "
        f"{len(insights)} insights ({transcript.duration_seconds / 60:.0f}m)"
    )
    return report


async def synthesize_rollup(
    per_video_reports: list[CouncilReport],
    session_id: str,
) -> CouncilReport:
    """
    Synthesize a cross-video rollup from individual per-video reports.

    Merges all insights and videos, then runs one more AI call focused on
    cross-video pattern detection and content opportunities.
    """
    if not per_video_reports:
        return CouncilReport(
            council_type=CouncilSource.YOUTUBE,
            session_id=session_id,
            summary="No videos available for rollup.",
        )

    # Merge all insights and videos
    all_insights: list[Insight] = []
    all_videos: list[VideoMeta] = []
    total_duration = 0.0

    prompt_parts = []
    for report in per_video_reports:
        all_insights.extend(report.insights)
        all_videos.extend(report.videos)
        total_duration += report.total_duration_hours

        # Build per-video summary for rollup prompt
        vid_title = report.videos[0].title if report.videos else "Unknown"
        vid_channel = report.videos[0].channel if report.videos else "Unknown"
        insight_titles = [i.title for i in report.insights]
        prompt_parts.append(
            f"## {vid_title} ({vid_channel})\n"
            f"Summary: {report.summary}\n"
            f"Insights: {'; '.join(insight_titles)}\n"
        )

    user_prompt = (
        f"Synthesize cross-video patterns from {len(per_video_reports)} individually-analyzed "
        f"YouTube videos ({total_duration:.1f} hours total):\n\n"
        + "\n".join(prompt_parts)
    )

    raw_response = await _call_model(user_prompt, system_prompt=ROLLUP_SYSTEM_PROMPT)

    # Guard: if all model providers failed, return merged insights without rollup synthesis
    if not raw_response:
        log.warning(
            "All AI providers returned empty responses — skipping rollup synthesis, "
            "returning merged per-video insights only"
        )
        return CouncilReport(
            council_type=CouncilSource.YOUTUBE,
            session_id=session_id,
            sources_processed=len(per_video_reports),
            total_duration_hours=total_duration,
            insights=all_insights,
            summary="Rollup synthesis failed — all AI providers returned empty responses.",
            videos=all_videos,
        )

    # Parse rollup — simpler structure (no per-video insights)
    rollup_summary = ""
    raw_analysis = ""
    try:
        json_str = raw_response
        if "```json" in raw_response:
            json_str = raw_response.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_response:
            json_str = raw_response.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
        rollup_summary = data.get("summary", "")
        parts = []
        if data.get("cross_video_patterns"):
            parts.append(f"## Cross-Video Patterns\n\n{data['cross_video_patterns']}")
        if data.get("content_opportunities"):
            parts.append(f"## Content Opportunities\n\n{data['content_opportunities']}")
        if data.get("convergence_signals"):
            parts.append(f"## Convergence Signals\n\n{data['convergence_signals']}")
        raw_analysis = "\n\n".join(parts)
    except (json.JSONDecodeError, Exception) as e:
        log.warning(f"Rollup JSON parse failed: {e} — using raw text")
        rollup_summary = raw_response[:500]
        raw_analysis = raw_response

    rollup = CouncilReport(
        council_type=CouncilSource.YOUTUBE,
        session_id=session_id,
        sources_processed=len(per_video_reports),
        total_duration_hours=total_duration,
        insights=all_insights,
        summary=rollup_summary,
        raw_analysis=raw_analysis,
        videos=all_videos,
    )

    log.info(
        f"Rollup synthesis complete: {len(per_video_reports)} videos, "
        f"{len(all_insights)} total insights, {total_duration:.1f}h"
    )
    return rollup


async def _call_model(user_prompt: str, system_prompt: str = ANALYSIS_SYSTEM_PROMPT) -> str:
    """Call AI model(s) with provider fallback chain.

    Order: Anthropic Claude → xAI Grok → local Ollama. Each provider is only
    attempted if its credential is present. Returns the first non-empty
    response. Empty string only if every provider fails.
    """
    last_error: Optional[Exception] = None

    if _get_anthropic_key():
        try:
            text = await _call_anthropic(user_prompt, system_prompt)
            if text:
                return text
        except Exception as e:
            last_error = e
            log.warning(f"Anthropic provider failed, falling through: {e}")

    if _get_xai_key():
        try:
            text = await _call_xai(user_prompt, system_prompt)
            if text:
                return text
        except Exception as e:
            last_error = e
            log.warning(f"xAI provider failed, falling through: {e}")

    try:
        text = await _call_ollama(user_prompt, system_prompt)
        if text:
            return text
    except Exception as e:
        last_error = e
        log.error(f"Ollama provider failed: {e}")

    log.error(
        f"All YouTube council providers failed (last error: {last_error}). "
        f"Check ANTHROPIC_API_KEY/XAI_API_KEY/OLLAMA_HOST."
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


async def _call_anthropic(prompt: str, system_prompt: str = ANALYSIS_SYSTEM_PROMPT) -> str:
    """Call Anthropic Claude API."""
    from ...cost_tracker import check_budget, record_cost

    # Budget check
    if not await check_budget("anthropic", 0.25):
        raise RuntimeError("Anthropic daily budget exceeded")

    try:
        client = await _get_yt_client()
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _get_anthropic_key(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data["content"][0]["text"]

        # Record actual cost from usage data
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cost = (input_tokens / 1000 * 0.003) + (output_tokens / 1000 * 0.015)
        await record_cost(
            "anthropic", cost, "ytc_analysis",
            f"model={CLAUDE_MODEL} in={input_tokens} out={output_tokens}",
            model=CLAUDE_MODEL, input_tokens=input_tokens, output_tokens=output_tokens,
        )

        log.info(f"Anthropic ({CLAUDE_MODEL}) response: {len(text)} chars, ${cost:.4f}")
        return text
    except Exception as e:
        log.error(f"Anthropic API ({CLAUDE_MODEL}) failed: {e}")
        raise


async def _call_xai(prompt: str, system_prompt: str = ANALYSIS_SYSTEM_PROMPT) -> str:
    """Call xAI Grok API (OpenAI-compatible)."""
    from ...cost_tracker import check_budget, record_cost

    if not await check_budget("xai", 0.10):
        raise RuntimeError("xAI daily budget exceeded")

    try:
        client = await _get_yt_client()
        response = await client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_get_xai_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 4096,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]

        # Record cost from usage
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = (input_tokens / 1000 * 0.005) + (output_tokens / 1000 * 0.015)
        await record_cost(
            "xai", cost, "ytc_analysis",
            f"model={GROK_MODEL} in={input_tokens} out={output_tokens}",
            model=GROK_MODEL, input_tokens=input_tokens, output_tokens=output_tokens,
        )

        log.info(f"xAI ({GROK_MODEL}) response: {len(text)} chars, ${cost:.4f}")
        return text
    except Exception as e:
        log.error(f"xAI API ({GROK_MODEL}) failed: {e}")
        raise


async def _call_ollama(prompt: str, system_prompt: str = ANALYSIS_SYSTEM_PROMPT) -> str:
    """Call Ollama local model via /api/generate (consistent with rest of codebase)."""
    model = OLLAMA_MODEL
    try:
        client = await _get_yt_client()
        response = await client.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "system": system_prompt,
                "prompt": prompt,
                "stream": False,
            },
            timeout=300.0,
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("response", "")
        log.info(f"Ollama ({model} @ {OLLAMA_HOST}) response: {len(text)} chars")
        return text
    except Exception as e:
        log.error(f"Ollama ({model} @ {OLLAMA_HOST}) failed: {e}")
        raise


def _parse_single_video_analysis(raw: str, video_id: str) -> tuple[list[Insight], str, str]:
    """Parse AI response for a single-video analysis. Links insights to video_id."""
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
        log.warning("Could not parse JSON from single-video response — using raw text")
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
            source_refs=[video_id],  # Link insight to this specific video
            actionable=bool(item.get("actionable", False)),
            action_suggestion=item.get("action_suggestion", ""),
        ))

    summary = data.get("summary", "")
    raw_analysis = ""
    key_quotes = data.get("key_quotes", "")
    content_assessment = data.get("content_assessment", "")
    if key_quotes:
        raw_analysis += f"## Key Quotes\n\n{key_quotes}\n\n"
    if content_assessment:
        raw_analysis += f"## Content Assessment\n\n{content_assessment}\n\n"

    return insights, summary, raw_analysis


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
    cross_patterns = data.get("cross_video_patterns", "")
    content_opps = data.get("content_opportunities", "")

    raw_analysis = ""
    if cross_patterns:
        raw_analysis += f"## Cross-Video Patterns\n\n{cross_patterns}\n\n"
    if content_opps:
        raw_analysis += f"## Content Opportunities\n\n{content_opps}\n\n"

    return insights, summary, raw_analysis
