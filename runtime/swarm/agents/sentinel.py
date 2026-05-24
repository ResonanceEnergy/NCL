"""
Sentinel Agent — Quality Control and Review.

Uses Claude with a fresh reviewer context for unbiased quality assessment.
Returns low confidence scores to trigger Foreman retries when quality issues
are detected.
"""

from __future__ import annotations

import logging
import time
import traceback

from ..agent_base import SwarmAgent
from ..models import SubtaskNode, TaskResult, TaskStatus
from . import register_agent


logger = logging.getLogger("ncl.swarm.sentinel")


@register_agent("sentinel")
class SentinelAgent(SwarmAgent):
    """
    Quality control agent that reviews work products for accuracy,
    completeness, consistency, and actionability. Returns confidence < 0.7
    when quality issues are found, triggering the Foreman to retry.
    """

    DESCRIPTION = "Sentinel — quality review, accuracy check, QA scoring (Claude)"

    def __str__(self) -> str:
        return f"SentinelAgent(id={self.agent_id}, state={self.state.value})"

    # Quality dimensions and their weights for scoring
    DIMENSIONS = {
        "accuracy": 0.30,
        "completeness": 0.25,
        "consistency": 0.20,
        "actionability": 0.15,
        "clarity": 0.10,
    }

    async def execute(self, task: SubtaskNode) -> TaskResult:
        start_ms = int(time.time() * 1000)
        self._start_task(task)
        total_cost = 0.0

        try:
            # --- Parse input ---
            content_to_review = task.input_data.get("content", "")
            criteria = task.input_data.get("criteria", [])
            original_spec = task.input_data.get("original_spec", task.title)
            review_type = task.input_data.get("review_type", "general")
            strict_mode = task.input_data.get("strict", False)

            if not content_to_review:
                raise ValueError("No content provided for review (input_data.content is empty)")

            criteria_str = (
                "\nSpecific Criteria to Check:\n- " + "\n- ".join(criteria) if criteria else ""
            )

            # --- Phase 1: Claude review with fresh reviewer context ---
            review_prompt = (
                f"You are an independent quality reviewer. You have NO prior context "
                f"about this work — evaluate it purely on its merits.\n\n"
                f"## Original Specification\n{original_spec}\n\n"
                f"## Content to Review\n{content_to_review}\n\n"
                f"## Review Type: {review_type}{criteria_str}\n\n"
                f"Score each dimension from 0.0 to 1.0 and provide specific issues:\n\n"
                f"### ACCURACY (weight: 30%)\n"
                f"Are claims correct? Any factual errors or unsupported statements?\n"
                f"Score: [0.0-1.0]\n"
                f"Issues: [list specific problems or 'None']\n\n"
                f"### COMPLETENESS (weight: 25%)\n"
                f"Does it fully address the specification? Any gaps?\n"
                f"Score: [0.0-1.0]\n"
                f"Issues: [list specific gaps or 'None']\n\n"
                f"### CONSISTENCY (weight: 20%)\n"
                f"Are there internal contradictions? Does tone/style stay consistent?\n"
                f"Score: [0.0-1.0]\n"
                f"Issues: [list contradictions or 'None']\n\n"
                f"### ACTIONABILITY (weight: 15%)\n"
                f"Can the reader act on this? Are next steps clear?\n"
                f"Score: [0.0-1.0]\n"
                f"Issues: [list problems or 'None']\n\n"
                f"### CLARITY (weight: 10%)\n"
                f"Is it well-written and easy to understand?\n"
                f"Score: [0.0-1.0]\n"
                f"Issues: [list problems or 'None']\n\n"
                f"### OVERALL VERDICT\n"
                f"PASS (quality is acceptable) or FAIL (needs revision)\n"
                f"Summary: [1-2 sentence overall assessment]\n"
                f"Priority Fixes: [ordered list of most important improvements needed]"
            )

            logger.info("Sentinel reviewing (%s): %s", review_type, original_spec[:80])
            review_response = await self.call_llm(
                prompt=review_prompt,
                model_preference="claude",
                max_tokens=3072,
                temperature=0.3,
            )
            total_cost += review_response.cost_cents

            # --- Phase 2: Parse scores from response ---
            scores = self._parse_scores(review_response.content)
            weighted_score = sum(
                scores.get(dim, 0.5) * weight for dim, weight in self.DIMENSIONS.items()
            )

            # Apply strict mode penalty
            if strict_mode:
                weighted_score *= 0.9  # Raise the bar in strict mode

            # Determine confidence (maps to quality verdict)
            # Below 0.7 triggers Foreman retry
            # Robust PASS detection: look for "VERDICT: PASS" on its own line
            # (case-insensitive, tolerates surrounding whitespace).
            import re as _re

            _verdict_match = _re.search(
                r"^\s*VERDICT\s*:\s*(PASS|FAIL)\s*$",
                review_response.content,
                _re.IGNORECASE | _re.MULTILINE,
            )
            if _verdict_match:
                is_pass = _verdict_match.group(1).upper() == "PASS"
            else:
                # No structured verdict line found — fall back to score threshold
                is_pass = weighted_score >= 0.7

            if is_pass and weighted_score >= 0.7:
                confidence = max(0.7, min(0.95, weighted_score))
            else:
                confidence = min(0.65, weighted_score)

            # --- Assemble review output ---
            final_output = (
                f"# Quality Review: {review_type.title()}\n\n"
                f"**Specification:** {original_spec}\n"
                f"**Verdict:** {'PASS' if confidence >= 0.7 else 'FAIL — REVISION NEEDED'}\n"
                f"**Weighted Score:** {weighted_score:.2f}\n\n"
                f"## Dimension Scores\n"
                f"| Dimension | Score | Weight | Weighted |\n"
                f"|-----------|-------|--------|----------|\n"
            )

            for dim, weight in self.DIMENSIONS.items():
                score = scores.get(dim, 0.5)
                final_output += (
                    f"| {dim.title()} | {score:.2f} | {weight:.0%} | {score * weight:.3f} |\n"
                )

            final_output += f"\n**Total Weighted Score:** {weighted_score:.3f}\n\n"
            final_output += f"## Detailed Review\n\n{review_response.content}"

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
                artifacts=["quality_review", f"verdict_{'pass' if confidence >= 0.7 else 'fail'}"],
            )

        except Exception as exc:
            logger.error("Sentinel agent failed: %s", exc, exc_info=True)
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

    def _parse_scores(self, review_text: str) -> dict[str, float]:
        """
        Extract dimension scores from the review response.

        Looks for patterns like "Score: 0.8" or "Score: [0.8]" after each
        dimension heading. Falls back to 0.5 if parsing fails.
        """
        scores: dict[str, float] = {}
        text_upper = review_text.upper()

        for dim in self.DIMENSIONS:
            dim_upper = dim.upper()
            scores[dim] = 0.5  # default

            # Find the dimension section
            dim_pos = text_upper.find(dim_upper)
            if dim_pos == -1:
                continue

            # Look for "Score:" within the next 200 chars
            section = review_text[dim_pos : dim_pos + 300]
            score_markers = ["Score:", "score:", "SCORE:"]

            for marker in score_markers:
                marker_pos = section.find(marker)
                if marker_pos == -1:
                    continue

                # Extract the number after the marker
                after_marker = section[marker_pos + len(marker) : marker_pos + len(marker) + 20]
                score_val = self._extract_float(after_marker)
                if score_val is not None:
                    scores[dim] = max(0.0, min(1.0, score_val))
                    break

        return scores

    @staticmethod
    def _extract_float(text: str) -> float | None:
        """Extract the first float value from a text snippet."""
        cleaned = text.strip().strip("[]() ")
        # Try to find a number pattern
        num_str = ""
        found_digit = False
        for char in cleaned:
            if char.isdigit() or char == ".":
                num_str += char
                found_digit = True
            elif found_digit:
                break

        if num_str:
            try:
                return float(num_str)
            except ValueError:
                pass
        return None
