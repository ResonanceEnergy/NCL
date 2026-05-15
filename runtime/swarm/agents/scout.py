"""
Scout Agent — Real-time Intelligence.

Uses Grok for real-time data and Perplexity for verification.
Produces intelligence briefings on breaking news, trends, and market signals.
"""

from __future__ import annotations

import logging
import time
import traceback

from . import register_agent
from ..agent_base import SwarmAgent
from ..models import SubtaskNode, TaskResult

logger = logging.getLogger("ncl.swarm.scout")


@register_agent("scout")
class ScoutAgent(SwarmAgent):
    """
    Real-time intelligence agent that monitors breaking developments,
    detects trends, and correlates market signals using Grok's live
    data access and Perplexity for verification.
    """

    async def execute(self, task: SubtaskNode) -> TaskResult:
        start_ms = int(time.time() * 1000)
        self._start_task(task)
        total_cost = 0.0

        try:
            # --- Parse input ---
            topic = task.input_data.get("topic") or task.input_data.get("query", task.title)
            signals = task.input_data.get("signals", [])
            timeframe = task.input_data.get("timeframe", "last 24 hours")
            verify_claims = task.input_data.get("verify", True)

            signals_str = (
                f"\nKey signals to track: {', '.join(signals)}"
                if signals
                else ""
            )

            # --- Phase 1: Grok for real-time intel ---
            intel_prompt = (
                f"You are a real-time intelligence analyst. Provide the latest "
                f"information and developments on:\n\n"
                f"Topic: {topic}\n"
                f"Timeframe: {timeframe}{signals_str}\n\n"
                f"Report:\n"
                f"1. BREAKING: Most recent developments (with timestamps if available)\n"
                f"2. SIGNALS: Key indicators and data points\n"
                f"3. SENTIMENT: Overall market/public sentiment direction\n"
                f"4. ACTORS: Key players and their recent actions\n"
                f"5. TRAJECTORY: Where this appears to be heading\n\n"
                f"Be specific with numbers, dates, and names. Flag anything unconfirmed."
            )

            logger.info("Scout gathering intel: %s", topic[:80])
            grok_response = await self.call_llm(
                prompt=intel_prompt,
                model_preference="grok",
                max_tokens=3072,
                temperature=0.5,
            )
            total_cost += grok_response.cost_cents

            await self.checkpoint({
                "phase": "intel_gathered",
                "topic": topic,
            })

            # --- Phase 2: Perplexity for verification ---
            verified_content = grok_response.content
            verification_note = ""

            if verify_claims:
                verify_prompt = (
                    f"Fact-check and verify the following intelligence briefing. "
                    f"For each major claim, indicate if it can be independently confirmed.\n\n"
                    f"Briefing to verify:\n{grok_response.content}\n\n"
                    f"Respond with:\n"
                    f"CONFIRMED: [claims you can verify with sources]\n"
                    f"UNCONFIRMED: [claims that lack independent verification]\n"
                    f"CONTRADICTED: [claims that conflict with other sources]\n"
                    f"ADDITIONAL CONTEXT: [anything important the briefing missed]"
                )

                verify_response = await self.call_llm(
                    prompt=verify_prompt,
                    model_preference="perplexity",
                    max_tokens=2048,
                    temperature=0.3,
                )
                total_cost += verify_response.cost_cents
                verification_note = f"\n\n---\n## Verification Report\n{verify_response.content}"

            # --- Phase 3: Assemble final briefing ---
            final_output = (
                f"# Intelligence Briefing: {topic}\n"
                f"**Timeframe:** {timeframe}\n"
                f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n\n"
                f"---\n\n"
                f"{grok_response.content}"
                f"{verification_note}"
            )

            # Score confidence based on verification
            confidence = 0.80 if verify_claims else 0.65

            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=final_output,
                confidence=confidence,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=["intelligence_briefing"],
            )

        except Exception as exc:
            logger.error("Scout agent failed: %s", exc, exc_info=True)
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
