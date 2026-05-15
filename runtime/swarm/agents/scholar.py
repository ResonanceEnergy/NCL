"""
Scholar Agent — Deep Research.

Uses Perplexity for web-grounded research with citations, then Claude
for synthesis into structured research briefs.
"""

from __future__ import annotations

import logging
import time
import traceback

from . import register_agent
from ..agent_base import SwarmAgent
from ..models import SubtaskNode, TaskResult

logger = logging.getLogger("ncl.swarm.scholar")


@register_agent("scholar")
class ScholarAgent(SwarmAgent):
    """
    Deep research agent that produces comprehensive, citation-backed
    research briefs covering literature review, market research,
    competitive analysis, and technical deep-dives.
    """

    async def execute(self, task: SubtaskNode) -> TaskResult:
        start_ms = int(time.time() * 1000)
        self._start_task(task)
        total_cost = 0.0

        try:
            # --- Parse input ---
            question = task.input_data.get("question") or task.input_data.get("query", task.title)
            scope = task.input_data.get("scope", "comprehensive")
            max_sources = task.input_data.get("max_sources", 10)
            focus_areas = task.input_data.get("focus_areas", [])

            focus_str = (
                f"\nFocus specifically on: {', '.join(focus_areas)}"
                if focus_areas
                else ""
            )

            # --- Phase 1: Perplexity for web-grounded research ---
            research_prompt = (
                f"Research the following question thoroughly with citations:\n\n"
                f"Question: {question}\n"
                f"Scope: {scope}{focus_str}\n\n"
                f"Provide up to {max_sources} distinct sources. For each key claim, "
                f"include the source URL or reference. Structure your response as:\n"
                f"1. Key Findings (bullet points with citations)\n"
                f"2. Supporting Evidence\n"
                f"3. Contrarian Views / Limitations\n"
                f"4. Source List"
            )

            logger.info("Scholar researching: %s", question[:80])
            research_response = await self.call_llm(
                prompt=research_prompt,
                model_preference="perplexity",
                max_tokens=4096,
                temperature=0.3,
            )
            total_cost += research_response.cost_cents

            await self.checkpoint({
                "phase": "research_complete",
                "sources_gathered": True,
            })

            # --- Phase 2: Claude for synthesis ---
            synthesis_prompt = (
                f"You are a senior research analyst. Synthesize the following raw research "
                f"into a structured research brief.\n\n"
                f"Original Question: {question}\n\n"
                f"Raw Research Data:\n{research_response.content}\n\n"
                f"Produce a structured brief with:\n"
                f"## Executive Summary\n"
                f"(2-3 sentences capturing the key answer)\n\n"
                f"## Key Findings\n"
                f"(Numbered findings with confidence level: HIGH/MEDIUM/LOW)\n\n"
                f"## Analysis\n"
                f"(Deeper explanation connecting the findings)\n\n"
                f"## Limitations & Gaps\n"
                f"(What we don't know or couldn't verify)\n\n"
                f"## Sources\n"
                f"(Formatted citation list)\n\n"
                f"Be precise, avoid speculation beyond what sources support."
            )

            synthesis_response = await self.call_llm(
                prompt=synthesis_prompt,
                model_preference="claude",
                max_tokens=4096,
                temperature=0.4,
            )
            total_cost += synthesis_response.cost_cents

            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=synthesis_response.content,
                confidence=0.85,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=["research_brief"],
            )

        except Exception as exc:
            logger.error("Scholar agent failed: %s", exc, exc_info=True)
            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=f"ERROR: {exc}\n{traceback.format_exc()}",
                confidence=0.0,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=[],
            )
