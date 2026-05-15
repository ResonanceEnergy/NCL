"""
Architect Agent — System Design.

Uses Claude for architecture design and GPT for implementation planning.
Produces technical specifications with file structures and integration points.
"""

from __future__ import annotations

import logging
import time
import traceback

from . import register_agent
from ..agent_base import SwarmAgent
from ..models import SubtaskNode, TaskResult

logger = logging.getLogger("ncl.swarm.architect")


@register_agent("architect")
class ArchitectAgent(SwarmAgent):
    """
    System design agent that produces technical specifications covering
    architecture, API design, database schemas, and integration planning.
    """

    async def execute(self, task: SubtaskNode) -> TaskResult:
        start_ms = int(time.time() * 1000)
        self._start_task(task)
        total_cost = 0.0

        try:
            # --- Parse input ---
            brief = task.input_data.get("brief") or task.input_data.get("description", task.title)
            constraints = task.input_data.get("constraints", [])
            tech_stack = task.input_data.get("tech_stack", [])
            existing_systems = task.input_data.get("existing_systems", [])
            design_type = task.input_data.get("design_type", "system_architecture")

            constraints_str = (
                f"\nConstraints: {', '.join(constraints)}" if constraints else ""
            )
            stack_str = (
                f"\nTech Stack: {', '.join(tech_stack)}" if tech_stack else ""
            )
            existing_str = (
                f"\nExisting Systems to Integrate: {', '.join(existing_systems)}"
                if existing_systems
                else ""
            )

            # --- Phase 1: Claude for architecture design ---
            design_prompt = (
                f"You are a principal systems architect. Design a solution for:\n\n"
                f"Brief: {brief}\n"
                f"Design Type: {design_type}"
                f"{constraints_str}{stack_str}{existing_str}\n\n"
                f"Produce:\n"
                f"## Architecture Overview\n"
                f"(High-level description of the system design)\n\n"
                f"## Components\n"
                f"(Each major component with its responsibility and interfaces)\n\n"
                f"## Data Flow\n"
                f"(How data moves through the system)\n\n"
                f"## API Contracts\n"
                f"(Key endpoints/interfaces between components)\n\n"
                f"## Data Model\n"
                f"(Core entities and relationships)\n\n"
                f"## Trade-offs & Decisions\n"
                f"(Key architectural decisions and their rationale)\n\n"
                f"Be specific about technologies, patterns, and protocols."
            )

            logger.info("Architect designing: %s", brief[:80])
            design_response = await self.call_llm(
                prompt=design_prompt,
                model_preference="claude",
                max_tokens=4096,
                temperature=0.5,
            )
            total_cost += design_response.cost_cents

            await self.checkpoint({
                "phase": "design_complete",
                "design_type": design_type,
            })

            # --- Phase 2: GPT for implementation planning ---
            impl_prompt = (
                f"Given the following architecture design, produce a detailed "
                f"implementation plan.\n\n"
                f"Architecture:\n{design_response.content}\n\n"
                f"Produce:\n"
                f"## File Structure\n"
                f"(Directory tree with descriptions for each file/module)\n\n"
                f"## Implementation Order\n"
                f"(Ordered phases with dependencies)\n\n"
                f"## Integration Points\n"
                f"(External services, APIs, SDKs needed)\n\n"
                f"## Configuration\n"
                f"(Environment variables, config files needed)\n\n"
                f"## Testing Strategy\n"
                f"(Unit, integration, and e2e test approach)\n\n"
                f"## Estimated Effort\n"
                f"(Rough T-shirt sizing per component: S/M/L/XL)\n\n"
                f"Be actionable — a developer should be able to start coding from this."
            )

            impl_response = await self.call_llm(
                prompt=impl_prompt,
                model_preference="gpt",
                max_tokens=4096,
                temperature=0.4,
            )
            total_cost += impl_response.cost_cents

            # --- Assemble final spec ---
            final_output = (
                f"# Technical Specification: {task.title}\n\n"
                f"---\n\n"
                f"# Part 1: Architecture Design\n\n"
                f"{design_response.content}\n\n"
                f"---\n\n"
                f"# Part 2: Implementation Plan\n\n"
                f"{impl_response.content}"
            )

            duration_ms = int(time.time() * 1000) - start_ms
            self._finish_task()

            return TaskResult(
                task_id=task.subtask_id,
                subtask_id=task.subtask_id,
                agent_id=self.agent_id,
                output=final_output,
                confidence=0.82,
                cost_cents=total_cost,
                duration_ms=duration_ms,
                artifacts=["technical_spec", "file_structure"],
            )

        except Exception as exc:
            logger.error("Architect agent failed: %s", exc, exc_info=True)
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
