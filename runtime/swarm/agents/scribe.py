"""
Scribe Agent — Document and Report Builder.

Uses Ollama qwen3:32b for cost-free bulk drafting and Claude for polish.
Produces publication-ready documents in markdown format.
"""

from __future__ import annotations

import logging
import time
import traceback

from ..agent_base import SwarmAgent
from ..models import SubtaskNode, TaskResult, TaskStatus
from . import register_agent


logger = logging.getLogger("ncl.swarm.scribe")


@register_agent("scribe")
class ScribeAgent(SwarmAgent):
    """
    Document builder agent that drafts and polishes reports, summaries,
    strategy documents, and communications using local LLM for bulk
    writing and Claude for editorial refinement.
    """

    DESCRIPTION = "Scribe — document drafting, report writing, editorial polish (Qwen3 + Claude)"

    def __str__(self) -> str:
        return f"ScribeAgent(id={self.agent_id}, state={self.state.value})"

    async def execute(self, task: SubtaskNode) -> TaskResult:
        start_ms = int(time.time() * 1000)
        self._start_task(task)
        total_cost = 0.0

        try:
            # --- Parse input ---
            doc_spec = task.input_data.get("spec") or task.input_data.get("description", task.title)
            doc_type = task.input_data.get("doc_type", "report")
            content = task.input_data.get("content", "")
            tone = task.input_data.get("tone", "professional")
            audience = task.input_data.get("audience", "executive")
            max_length = task.input_data.get("max_length", "medium")  # short, medium, long
            structure = task.input_data.get("structure", [])

            content_block = f"\nSource Content/Data:\n{content}" if content else ""
            structure_str = f"\nRequired Sections: {', '.join(structure)}" if structure else ""

            # Map length to approximate word count
            length_map = {
                "short": "500-800 words",
                "medium": "1000-2000 words",
                "long": "2500-4000 words",
            }
            target_length = length_map.get(max_length, "1000-2000 words")

            # --- Phase 1: Qwen for bulk drafting ---
            draft_prompt = (
                f"Write a {doc_type} based on the following specification:\n\n"
                f"Specification: {doc_spec}\n"
                f"Tone: {tone}\n"
                f"Target Audience: {audience}\n"
                f"Target Length: {target_length}"
                f"{structure_str}{content_block}\n\n"
                f"Write the complete document in markdown format. Include:\n"
                f"- Clear section headings\n"
                f"- An executive summary or introduction\n"
                f"- Well-structured body sections\n"
                f"- Concrete examples and specific details\n"
                f"- A conclusion or next steps section\n\n"
                f"Write the full document now:"
            )

            logger.info("Scribe drafting (%s): %s", doc_type, doc_spec[:80])
            draft_response = await self.call_llm(
                prompt=draft_prompt,
                model_preference="ollama:qwen3:32b",
                max_tokens=6144,
                temperature=0.7,
            )
            total_cost += draft_response.cost_cents  # Should be 0 for local

            await self.checkpoint(
                {
                    "phase": "draft_complete",
                    "doc_type": doc_type,
                    "draft_length": len(draft_response.content),
                }
            )

            # --- Phase 2: Claude for polish and editing ---
            polish_prompt = (
                f"You are an expert editor. Polish the following {doc_type} draft "
                f"for a {audience} audience. The tone should be {tone}.\n\n"
                f"Original Specification: {doc_spec}\n\n"
                f"Draft:\n{draft_response.content}\n\n"
                f"Edit for:\n"
                f"1. Clarity — remove jargon, simplify complex sentences\n"
                f"2. Impact — strengthen opening and key points\n"
                f"3. Flow — ensure logical progression between sections\n"
                f"4. Precision — tighten language, eliminate filler\n"
                f"5. Completeness — flag any gaps in reasoning or missing sections\n"
                f"6. Formatting — proper markdown, consistent heading hierarchy\n\n"
                f"Return the complete polished document. Do not add commentary, "
                f"just the final document in markdown."
            )

            polish_response = await self.call_llm(
                prompt=polish_prompt,
                model_preference="claude",
                max_tokens=6144,
                temperature=0.4,
            )
            total_cost += polish_response.cost_cents

            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=polish_response.content,
                confidence=0.88,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=[f"document_{doc_type}"],
            )

        except Exception as exc:
            logger.error("Scribe agent failed: %s", exc, exc_info=True)
            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=f"ERROR: {exc}\n{traceback.format_exc()}",
                status=TaskStatus.FAILED,
                confidence=0.0,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=[],
            )
