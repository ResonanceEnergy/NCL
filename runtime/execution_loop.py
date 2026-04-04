"""
NARTIX Execution Loop — Claude→Copilot Hybrid Coding Pipeline

Reads council output from 03-Execution/, builds precise coding prompts,
writes them for Copilot (Claude Opus 4.6), and manages the review cycle.

This is the 03-Execution stage processor in the MWP pipeline.
Called by the pump watcher or Claude Desktop when a task reaches execution.

Part of NARTIX Ecosystem Build Plan — April 2026.

Usage:
    python3 -m runtime.execution_loop <pump-id>
    # Or called programmatically by Claude Desktop
"""

import json
import logging
import logging.handlers
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --- Config ---

NCL_BASE = Path.home() / "Projects" / "NCL"
EXEC_PIPELINE = NCL_BASE / "workspaces" / "execution-pipeline"
EXECUTION_DIR = EXEC_PIPELINE / "03-Execution"
WORKING_FILES = EXECUTION_DIR / "working-files"
REVIEW_DIR = EXEC_PIPELINE / "04-Review"
OUTPUT_DIR = EXEC_PIPELINE / "05-Output"

MAX_CODING_ITERATIONS = 3
MAX_REVIEW_ROUNDS = 2

# --- Logging ---

LOG_DIR = NCL_BASE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "execution-loop.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
        ),
    ],
)
log = logging.getLogger("ncl.execution-loop")


def build_copilot_prompt(
    task_plan: dict,
    council_output: dict,
    iteration: int = 1,
    previous_issues: Optional[list[str]] = None,
) -> str:
    """
    Build a high-quality coding prompt for Copilot (Claude Opus 4.6).
    Uses Outcome + Constraints + Examples technique from the build plan.
    """
    raw_intent = task_plan.get("raw_intent", "")
    target_pillar = task_plan.get("target_pillar", "NCL")
    priority = task_plan.get("priority", "P2")
    council_decision = council_output.get("decision", "")
    council_plan = council_output.get("implementation_plan", "")
    acceptance_criteria = council_output.get("acceptance_criteria", [])

    prompt_parts = []

    # Header
    prompt_parts.append(f"// NARTIX EXECUTION — Iteration {iteration}/{MAX_CODING_ITERATIONS}")
    prompt_parts.append(f"// Pump: {task_plan.get('pump_id', 'unknown')}")
    prompt_parts.append(f"// Pillar: {target_pillar} | Priority: {priority}")
    prompt_parts.append(f"// Generated: {datetime.now(timezone.utc).isoformat()}")
    prompt_parts.append("")

    # Outcome + Constraints
    prompt_parts.append("// === GOAL ===")
    prompt_parts.append(f"// {raw_intent}")
    prompt_parts.append("")

    if council_decision:
        prompt_parts.append("// === COUNCIL DECISION ===")
        for line in council_decision.split("\n"):
            prompt_parts.append(f"// {line}")
        prompt_parts.append("")

    if council_plan:
        prompt_parts.append("// === IMPLEMENTATION PLAN ===")
        for line in council_plan.split("\n"):
            prompt_parts.append(f"// {line}")
        prompt_parts.append("")

    # Acceptance Criteria
    if acceptance_criteria:
        prompt_parts.append("// === ACCEPTANCE CRITERIA ===")
        for i, criterion in enumerate(acceptance_criteria, 1):
            prompt_parts.append(f"// {i}. {criterion}")
        prompt_parts.append("")

    # Previous issues (debugging loop)
    if previous_issues and iteration > 1:
        prompt_parts.append("// === ISSUES FROM PREVIOUS ITERATION ===")
        prompt_parts.append("// Fix exactly these issues while preserving working logic:")
        for issue in previous_issues:
            prompt_parts.append(f"// - {issue}")
        prompt_parts.append("")

    # Constraints
    prompt_parts.append("// === CONSTRAINTS ===")
    prompt_parts.append("// - Follow NARTIX coding standards (see .github/copilot-instructions.md)")
    prompt_parts.append("// - Python 3.12+ with type hints, TypeScript strict mode")
    prompt_parts.append("// - Include error handling and structured logging")
    prompt_parts.append("// - Add docstrings/JSDoc on all public functions")
    prompt_parts.append("// - Make it testable — pure functions where possible")
    prompt_parts.append("")

    return "\n".join(prompt_parts)


def write_copilot_prompt(prompt: str, pump_id: str, iteration: int) -> Path:
    """Write the prompt to current-copilot-prompt.md in 03-Execution/."""
    EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    WORKING_FILES.mkdir(parents=True, exist_ok=True)

    prompt_file = EXECUTION_DIR / "current-copilot-prompt.md"
    prompt_file.write_text(f"# Copilot Prompt — {pump_id} (iteration {iteration})\n\n```\n{prompt}\n```\n")

    # Also write as a .txt for easy copy-paste
    txt_file = EXECUTION_DIR / f"copilot-prompt-{pump_id}-v{iteration}.txt"
    txt_file.write_text(prompt)

    log.info(f"Copilot prompt written → {prompt_file.name} (iteration {iteration})")
    return prompt_file


def create_signed_off(pump_id: str, iterations: int, summary: str) -> Path:
    """Create signed-off.md when execution is complete."""
    signed_off = EXECUTION_DIR / "signed-off.md"
    content = {
        "pump_id": pump_id,
        "status": "complete",
        "iterations": iterations,
        "summary": summary,
        "signed_off_by": "Claude Desktop Max (NCL Execution Loop)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    signed_off.write_text(
        f"# Execution Sign-Off\n\n"
        f"**Pump:** {pump_id}\n"
        f"**Status:** Complete\n"
        f"**Iterations:** {iterations}/{MAX_CODING_ITERATIONS}\n"
        f"**Summary:** {summary}\n"
        f"**Signed Off:** Claude Desktop Max\n"
        f"**Timestamp:** {content['timestamp']}\n\n"
        f"```json\n{json.dumps(content, indent=2)}\n```\n"
    )
    log.info(f"Signed off → {signed_off.name}")
    return signed_off


def create_feedback_payload(
    pump_id: str,
    status: str,
    summary: str,
    artifacts: list[str],
    iterations: int,
    review_rounds: int,
) -> dict:
    """Build feedback payload for iPhone pump-back via relay /responses."""
    return {
        "pump_id": pump_id,
        "status": status,
        "summary": summary,
        "artifacts": artifacts,
        "metrics": {
            "council_rounds": 1,
            "coding_iterations": iterations,
            "review_rounds": review_rounds,
            "total_time_seconds": 0,  # Filled by caller
        },
        "next_steps": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def stage_for_review(pump_id: str) -> Path:
    """Move execution output to 04-Review/."""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # Copy signed-off and working files
    signed_off_src = EXECUTION_DIR / "signed-off.md"
    if signed_off_src.exists():
        shutil.copy2(str(signed_off_src), str(REVIEW_DIR / f"signed-off-{pump_id}.md"))

    # Copy working files
    review_working = REVIEW_DIR / f"working-files-{pump_id}"
    if WORKING_FILES.exists():
        shutil.copytree(str(WORKING_FILES), str(review_working), dirs_exist_ok=True)

    log.info(f"Staged for review → 04-Review/{pump_id}")
    return REVIEW_DIR


def stage_for_output(pump_id: str, feedback: dict) -> Path:
    """Move verified output to 05-Output/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write feedback payload
    feedback_file = OUTPUT_DIR / f"feedback-{pump_id}.json"
    feedback_file.write_text(json.dumps(feedback, indent=2))

    # Copy final artifacts
    review_working = REVIEW_DIR / f"working-files-{pump_id}"
    output_working = OUTPUT_DIR / f"artifacts-{pump_id}"
    if review_working.exists():
        shutil.copytree(str(review_working), str(output_working), dirs_exist_ok=True)

    log.info(f"Output finalized → 05-Output/{pump_id}")
    return OUTPUT_DIR


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 -m runtime.execution_loop <pump-id>")
        print("  Reads task from 03-Execution/ and builds Copilot prompt")
        sys.exit(1)

    pump_id = sys.argv[1].strip()
    if not pump_id or not all(c.isalnum() or c in "-_." for c in pump_id):
        log.error(f"Invalid pump_id: '{pump_id}' — must be alphanumeric with hyphens/underscores")
        sys.exit(1)
    log.info(f"Execution loop started for pump: {pump_id}")

    # Check for task plan and council output
    task_plan_file = EXECUTION_DIR / "task-plan.md"
    council_output_file = EXECUTION_DIR / "council-output.md"

    if not task_plan_file.exists():
        log.warning(f"No task-plan.md found in 03-Execution/ — creating template")
        task_plan = {"pump_id": pump_id, "raw_intent": "See pump file", "target_pillar": "NCL", "priority": "P2"}
    else:
        # Parse task plan — read full content, extract intent
        try:
            content = task_plan_file.read_text()
            task_plan = {
                "pump_id": pump_id,
                "raw_intent": content,
                "target_pillar": "NCL",
                "priority": "P2",
            }
        except OSError as e:
            log.error(f"Failed to read task plan: {e}")
            task_plan = {"pump_id": pump_id, "raw_intent": "Error reading task plan", "target_pillar": "NCL", "priority": "P2"}

    council_output = {}
    if council_output_file.exists():
        council_output = {"decision": council_output_file.read_text()[:1000]}

    # Build and write prompt
    prompt = build_copilot_prompt(task_plan, council_output)
    write_copilot_prompt(prompt, pump_id, iteration=1)

    print(f"\nCopilot prompt ready at: {EXECUTION_DIR / 'current-copilot-prompt.md'}")
    print(f"Open VS Code → Copilot Chat → paste or use Agent Mode")
    print(f"Working files go in: {WORKING_FILES}/")
