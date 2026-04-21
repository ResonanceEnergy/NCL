"""
War Room Analysis Bridge — Council Output → NCL Actionable Intelligence

Takes completed council reports (YouTube + X) and produces a War Room
briefing: situation report, intelligence synthesis, strategic assessment,
risks/opportunities, and binding directives.

This bridges the intelligence councils to the NCL mandate-generation
pipeline and the AAC War Room scenario engine.

Output: WAR_ROOM_BRIEFING_{date}.md + .json in council-reports/
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    CouncilReport,
    CouncilSource,
    Insight,
    SignalCategory,
    Severity,
)

log = logging.getLogger("ncl.councils.war_room_bridge")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
REPORTS_DIR = NCL_BASE / "intelligence-scan" / "council-reports"
MANDATE_INPUT_DIR = NCL_BASE / "mandate-generation" / "input"
AAC_WAR_ROOM_DIR = Path.home() / "Projects" / "AAC-v2" / "war-room" / "intelligence"


WAR_ROOM_SYSTEM_PROMPT = """You are the NARTIX War Room Commander. You receive synthesized intelligence
from the YouTube Council and X Council and produce a War Room Briefing.

Your output MUST follow this exact structure (Markdown):

# WAR ROOM BRIEFING — {date}

## 1. SitRep (Situation Report)
Current state of intelligence across all sources. What happened in the last 24h.

## 2. Intelligence Synthesis
Cross-reference YouTube and X signals. Identify convergence (same signal from both),
contradictions, and emerging patterns across sources.

## 3. Strategic Assessment
SWOT analysis of current intelligence landscape. Trend forecasts.
What is changing? What should NATRIX prepare for?

## 4. Risks & Opportunities
Rank by severity. Each entry: risk/opportunity, confidence, recommended action.

## 5. Binding Directives
Concrete, executable next steps. Each directive must be:
- Specific (who does what)
- Time-bound (by when)
- Measurable (how to verify completion)
Max 5 directives.

## 6. NCL Memory Flags
Insights that should be persisted to long-term memory. Tag each with category and confidence.

Rules:
- NO content creation suggestions (no video ideas, no post drafts)
- ONLY actionable intelligence and strategic directives
- Cite source insights by title when referencing
- Confidence scores on all assessments (0.0-1.0)
- If intelligence is thin, say so — never fabricate signal
"""


async def run_war_room_analysis(
    youtube_report: Optional[CouncilReport],
    x_report: Optional[CouncilReport],
    session_id: str,
) -> Optional[Path]:
    """
    Synthesize council reports into a War Room briefing.

    Calls the AI analysis chain (Claude → Grok → Ollama) to produce
    the briefing, then saves it and optionally feeds directives into
    mandate-generation/input/ for NCL processing.
    """
    # Build combined intelligence context
    context_parts: list[str] = []

    if youtube_report and youtube_report.insights:
        context_parts.append("=== YOUTUBE COUNCIL INTELLIGENCE ===")
        context_parts.append(f"Videos processed: {youtube_report.sources_processed}")
        context_parts.append(f"Duration: {youtube_report.total_duration_hours:.1f}h")
        context_parts.append(f"Summary: {youtube_report.summary}")
        context_parts.append("")
        for insight in youtube_report.insights:
            flag = "⚡ ACTIONABLE" if insight.actionable else ""
            context_parts.append(
                f"- [{insight.category.value}] {insight.title} "
                f"(confidence: {insight.confidence:.0%}) {flag}"
            )
            context_parts.append(f"  {insight.description[:300]}")
        context_parts.append("")

    if x_report and x_report.insights:
        context_parts.append("=== X (TWITTER) COUNCIL INTELLIGENCE ===")
        context_parts.append(f"Posts analyzed: {x_report.sources_processed}")
        context_parts.append(f"Summary: {x_report.summary}")
        context_parts.append("")
        for insight in x_report.insights:
            flag = "⚡ ACTIONABLE" if insight.actionable else ""
            context_parts.append(
                f"- [{insight.category.value}] {insight.title} "
                f"(confidence: {insight.confidence:.0%}) {flag}"
            )
            context_parts.append(f"  {insight.description[:300]}")
        context_parts.append("")

    if not context_parts:
        log.warning("No council intelligence to synthesize — skipping War Room")
        return None

    combined = "\n".join(context_parts)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Call AI for War Room synthesis
    briefing = await _call_war_room_model(combined, date_str)

    if not briefing:
        log.error("War Room analysis produced no output")
        return None

    # Save briefing
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"WAR_ROOM_BRIEFING_{date_str}-{session_id}.md"
    md_path.write_text(briefing, encoding="utf-8")
    log.info(f"War Room briefing saved → {md_path}")

    # Save JSON summary
    json_path = REPORTS_DIR / f"WAR_ROOM_BRIEFING_{date_str}-{session_id}.json"
    war_room_data = {
        "session_id": session_id,
        "date": date_str,
        "youtube_insights": len(youtube_report.insights) if youtube_report else 0,
        "x_insights": len(x_report.insights) if x_report else 0,
        "briefing_length": len(briefing),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path.write_text(json.dumps(war_room_data, indent=2))

    # Feed directives into NCL mandate input (if directives found)
    _extract_and_route_directives(briefing, session_id, date_str)

    # Forward market/geopolitical signals to AAC War Room
    _route_to_aac_war_room(youtube_report, x_report, session_id, date_str)

    return md_path


async def _call_war_room_model(context: str, date_str: str) -> Optional[str]:
    """Call AI model for War Room synthesis. Same fallback chain as analyzers."""
    prompt = f"Produce a War Room Briefing for {date_str}.\n\n{context}"

    # Try Claude → Grok → Ollama (same pattern as council analyzers)
    result = await _try_anthropic(prompt)
    if result:
        return result

    result = await _try_xai(prompt)
    if result:
        return result

    result = await _try_ollama(prompt)
    if result:
        return result

    log.error("All AI backends failed for War Room analysis")
    return None


async def _try_anthropic(prompt: str) -> Optional[str]:
    """Try Anthropic Claude API."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4000,
                    "system": WAR_ROOM_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
    except Exception as e:
        log.warning(f"Anthropic War Room call failed: {e}")
        return None


async def _try_xai(prompt: str) -> Optional[str]:
    """Try xAI Grok API."""
    api_key = os.getenv("XAI_API_KEY", "")
    if not api_key:
        return None

    try:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-4",
                    "messages": [
                        {"role": "system", "content": WAR_ROOM_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 4000,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"xAI War Room call failed: {e}")
        return None


async def _try_ollama(prompt: str) -> Optional[str]:
    """Try local Ollama."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen3:32b",
                    "prompt": f"{WAR_ROOM_SYSTEM_PROMPT}\n\n{prompt}",
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 4000},
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
    except Exception as e:
        log.warning(f"Ollama War Room call failed: {e}")
        return None


def _extract_and_route_directives(
    briefing: str,
    session_id: str,
    date_str: str,
) -> None:
    """
    Extract binding directives from War Room briefing and save as
    a pump-prompt-formatted JSON in mandate-generation/input/ for
    NCL processing on the next mandate cycle.
    """
    # Look for the directives section
    directives_text = ""
    in_directives = False
    for line in briefing.split("\n"):
        if "Binding Directives" in line or "## 5." in line:
            in_directives = True
            continue
        if in_directives and line.startswith("## "):
            break
        if in_directives:
            directives_text += line + "\n"

    directives_text = directives_text.strip()
    if not directives_text:
        log.info("No directives extracted from War Room briefing")
        return

    # Save as NCL input for mandate generation
    MANDATE_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_file = MANDATE_INPUT_DIR / f"RLY-WAR-ROOM-{date_str}-{session_id}.json"
    mandate_input = {
        "source": "war_room_council",
        "type": "directive_relay",
        "session_id": session_id,
        "date": date_str,
        "directives": directives_text,
        "priority": "P2",
        "requires_approval": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    input_file.write_text(json.dumps(mandate_input, indent=2))
    log.info(f"War Room directives routed to mandate input → {input_file.name}")


def _route_to_aac_war_room(
    youtube_report: Optional[CouncilReport],
    x_report: Optional[CouncilReport],
    session_id: str,
    date_str: str,
) -> None:
    """
    Forward market and geopolitical signals to AAC War Room scenario engine.

    Only high-confidence market/geopolitical insights get forwarded.
    """
    relevant_insights: list[dict] = []

    for report in [youtube_report, x_report]:
        if not report:
            continue
        for insight in report.insights:
            if insight.category in (SignalCategory.MARKET, SignalCategory.GEOPOLITICAL):
                if insight.confidence >= 0.7:
                    relevant_insights.append({
                        "source": report.council_type.value,
                        "title": insight.title,
                        "description": insight.description[:500],
                        "category": insight.category.value,
                        "confidence": insight.confidence,
                        "actionable": insight.actionable,
                        "action": insight.action_suggestion,
                        "tags": insight.tags,
                    })

    if not relevant_insights:
        log.info("No market/geopolitical signals to route to AAC War Room")
        return

    # Save to AAC intelligence directory (if it exists)
    if AAC_WAR_ROOM_DIR.exists():
        aac_file = AAC_WAR_ROOM_DIR / f"council-intel-{date_str}-{session_id}.json"
        aac_file.write_text(json.dumps({
            "source": "ncl_intelligence_councils",
            "session_id": session_id,
            "date": date_str,
            "signals": relevant_insights,
            "signal_count": len(relevant_insights),
        }, indent=2))
        log.info(f"Routed {len(relevant_insights)} signals to AAC War Room → {aac_file.name}")
    else:
        log.info(f"AAC War Room dir not found ({AAC_WAR_ROOM_DIR}) — skipping AAC routing")
        # Still save locally so it can be picked up later
        local_path = REPORTS_DIR / f"aac-relay-{date_str}-{session_id}.json"
        local_path.write_text(json.dumps({
            "pending_relay": True,
            "target": "AAC War Room",
            "signals": relevant_insights,
        }, indent=2))
        log.info(f"Saved AAC relay locally → {local_path.name}")
