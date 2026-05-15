"""
Analyst Agent — Data and Market Analysis.

Uses Gemini for broad analysis and Claude for structured output.
Produces actionable insights with confidence scores.
"""

from __future__ import annotations

import logging
import time
import traceback

from . import register_agent
from ..agent_base import SwarmAgent
from ..models import SubtaskNode, TaskResult

logger = logging.getLogger("ncl.swarm.analyst")


@register_agent("analyst")
class AnalystAgent(SwarmAgent):
    """
    Data and market analysis agent that performs quantitative analysis,
    market sizing, pattern recognition, and risk assessment using Gemini
    for broad reasoning and Claude for structured delivery.
    """

    async def execute(self, task: SubtaskNode) -> TaskResult:
        start_ms = int(time.time() * 1000)
        self._start_task(task)
        total_cost = 0.0

        try:
            # --- Parse input ---
            question = task.input_data.get("question") or task.input_data.get("query", task.title)
            data_context = task.input_data.get("data", "")
            analysis_type = task.input_data.get("analysis_type", "general")
            metrics = task.input_data.get("metrics", [])
            assumptions = task.input_data.get("assumptions", [])

            metrics_str = f"\nKey Metrics to Analyze: {', '.join(metrics)}" if metrics else ""
            assumptions_str = (
                f"\nAssumptions: {', '.join(assumptions)}" if assumptions else ""
            )
            data_block = f"\nData/Context:\n{data_context}" if data_context else ""

            # --- Phase 1: Gemini for broad analysis ---
            analysis_prompt = (
                f"You are a senior data analyst. Perform a {analysis_type} analysis "
                f"for the following:\n\n"
                f"Question: {question}"
                f"{metrics_str}{assumptions_str}{data_block}\n\n"
                f"Provide:\n"
                f"1. QUANTITATIVE FINDINGS: Numbers, percentages, growth rates\n"
                f"2. PATTERNS: Trends, correlations, anomalies detected\n"
                f"3. COMPARISONS: Benchmarks, relative positioning\n"
                f"4. PROJECTIONS: Forward-looking estimates with ranges\n"
                f"5. RISKS: Key risk factors and their probability/impact\n\n"
                f"Use specific numbers wherever possible. State confidence "
                f"(HIGH/MEDIUM/LOW) for each finding. Show your reasoning."
            )

            logger.info("Analyst analyzing (%s): %s", analysis_type, question[:80])
            gemini_response = await self.call_llm(
                prompt=analysis_prompt,
                model_preference="gemini",
                max_tokens=4096,
                temperature=0.4,
            )
            total_cost += gemini_response.cost_cents

            await self.checkpoint({
                "phase": "analysis_complete",
                "analysis_type": analysis_type,
            })

            # --- Phase 2: Claude for structured output ---
            structure_prompt = (
                f"Transform the following raw analysis into a structured, actionable "
                f"insights report. Maintain all quantitative data but organize it "
                f"for executive decision-making.\n\n"
                f"Original Question: {question}\n\n"
                f"Raw Analysis:\n{gemini_response.content}\n\n"
                f"Produce this exact structure:\n\n"
                f"## Bottom Line\n"
                f"(One paragraph: the answer to the question with key numbers)\n\n"
                f"## Key Metrics\n"
                f"| Metric | Value | Confidence | Trend |\n"
                f"|--------|-------|------------|-------|\n"
                f"(Table of most important data points)\n\n"
                f"## Insights\n"
                f"(Numbered list of actionable insights, each with confidence 0.0-1.0)\n\n"
                f"## Risk Matrix\n"
                f"| Risk | Probability | Impact | Mitigation |\n"
                f"|------|-------------|--------|------------|\n\n"
                f"## Recommendations\n"
                f"(Prioritized action items based on analysis)\n\n"
                f"## Methodology & Limitations\n"
                f"(How this was analyzed and what could be wrong)"
            )

            structure_response = await self.call_llm(
                prompt=structure_prompt,
                model_preference="claude",
                max_tokens=4096,
                temperature=0.3,
            )
            total_cost += structure_response.cost_cents

            # Determine confidence based on data availability
            if data_context:
                confidence = 0.85
            elif analysis_type in ("market_sizing", "projection"):
                confidence = 0.70
            else:
                confidence = 0.75

            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=structure_response.content,
                confidence=confidence,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=["analysis_report", f"type_{analysis_type}"],
            )

        except Exception as exc:
            logger.error("Analyst agent failed: %s", exc, exc_info=True)
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
