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
import signal as signal_mod
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# --- Config ---

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
EXEC_PIPELINE = NCL_BASE / "workspaces" / "execution-pipeline"
EXECUTION_DIR = EXEC_PIPELINE / "03-Execution"
WORKING_FILES = EXECUTION_DIR / "working-files"
REVIEW_DIR = EXEC_PIPELINE / "04-Review"
OUTPUT_DIR = EXEC_PIPELINE / "05-Output"

MAX_CODING_ITERATIONS = 3
MAX_REVIEW_ROUNDS = 2

# Claude Code CLI bridge mode: "auto" (try claude CLI), "manual" (write prompt file only)
EXECUTION_MODE = os.getenv("NCL_EXECUTION_MODE", "auto")

# --- Circuit Breaker ---

# Controls the Claude Code CLI bridge. If the bridge fails
# CIRCUIT_FAIL_THRESHOLD times in a row, the breaker opens and backs off
# exponentially, up to CIRCUIT_MAX_BACKOFF_SECONDS.
CIRCUIT_FAIL_THRESHOLD = int(os.getenv("NCL_CIRCUIT_FAIL_THRESHOLD", "3"))
CIRCUIT_MAX_BACKOFF_SECONDS = int(os.getenv("NCL_CIRCUIT_MAX_BACKOFF", "120"))


class _CircuitBreaker:
    """Simple closed/open circuit breaker with exponential backoff."""

    def __init__(
        self,
        threshold: int = CIRCUIT_FAIL_THRESHOLD,
        max_backoff: float = CIRCUIT_MAX_BACKOFF_SECONDS,
    ) -> None:
        self.threshold = threshold
        self.max_backoff = max_backoff
        self._failures = 0
        self._open_until: float = 0.0

    @property
    def is_open(self) -> bool:
        """True when the circuit is open (calls should be skipped)."""
        if self._failures >= self.threshold:
            if time.monotonic() < self._open_until:
                return True
            # Cool-down period expired — allow one probe
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        backoff = min(2 ** (self._failures - 1), self.max_backoff)
        self._open_until = time.monotonic() + backoff
        log.warning(
            "CircuitBreaker: failure #%d — bridge open for %.0fs",
            self._failures,
            backoff,
        )

    def __repr__(self) -> str:
        state = "OPEN" if self.is_open else "CLOSED"
        return f"<CircuitBreaker {state} failures={self._failures}>"


# Module-level circuit breaker for the Claude Code CLI bridge
_claude_code_breaker = _CircuitBreaker()


def _ensure_exec_dirs() -> None:
    """Create all execution pipeline directories on startup."""
    for d in [
        EXEC_PIPELINE / "01-Input",
        EXEC_PIPELINE / "02-Planning",
        EXECUTION_DIR,
        WORKING_FILES,
        REVIEW_DIR,
        OUTPUT_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


_ensure_exec_dirs()

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


def _sanitize_council_text(text: str) -> str:
    """Sanitize council output to prevent prompt injection.

    Wraps text in XML boundary tags and escapes any existing XML-like
    boundary markers so the LLM treats council output as data, not instructions.
    """
    if not text:
        return ""
    # Escape any attempt to close the boundary tags within the content
    sanitized = text.replace("</council_data>", "&lt;/council_data&gt;")
    sanitized = sanitized.replace("<council_data>", "&lt;council_data&gt;")
    return f"<council_data>\n{sanitized}\n</council_data>"


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
    # Sanitize council output to prevent prompt injection — wrap in XML
    # boundaries so the LLM treats it as data, not instructions.
    council_decision = _sanitize_council_text(council_output.get("decision", ""))
    council_plan = _sanitize_council_text(council_output.get("implementation_plan", ""))
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
    prompt_file.write_text(
        f"# Copilot Prompt — {pump_id} (iteration {iteration})\n\n```\n{prompt}\n```\n"
    )

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


def load_task_plan(pump_id: str) -> dict:
    """Load task plan from 02-Planning, trying versioned then generic filenames."""
    for name in [f"task-plan-{pump_id}.md", "task-plan.md"]:
        path = EXEC_PIPELINE / "02-Planning" / name
        if path.exists():
            try:
                content = path.read_text()
                log.info(f"Loaded task plan from {path.name}")
                return {
                    "pump_id": pump_id,
                    "raw_intent": content,
                    "target_pillar": _extract_field(content, "Pillar", "NCL"),
                    "priority": _extract_field(content, "Priority", "P2"),
                }
            except OSError as e:
                log.error(f"Failed to read task plan: {e}")

    # Fallback: check 03-Execution for legacy location
    legacy = EXECUTION_DIR / "task-plan.md"
    if legacy.exists():
        content = legacy.read_text()
        return {"pump_id": pump_id, "raw_intent": content, "target_pillar": "NCL", "priority": "P2"}

    log.warning("No task plan found — using minimal template")
    return {
        "pump_id": pump_id,
        "raw_intent": "See pump file",
        "target_pillar": "NCL",
        "priority": "P2",
    }


def load_council_output(pump_id: str) -> dict:
    """Load council output from 02-Planning."""
    for name in [f"council-output-{pump_id}.md", "council-output.md"]:
        path = EXEC_PIPELINE / "02-Planning" / name
        if path.exists():
            try:
                content = path.read_text()
                log.info(f"Loaded council output from {path.name}")
                return {
                    "decision": content,
                    "acceptance_criteria": _extract_criteria(content),
                }
            except OSError as e:
                log.error(f"Failed to read council output: {e}")

    # Legacy location
    legacy = EXECUTION_DIR / "council-output.md"
    if legacy.exists():
        return {"decision": legacy.read_text()}

    return {}


def _extract_field(content: str, field: str, default: str) -> str:
    """Extract a field value from markdown content (e.g., 'Pillar: NCL')."""
    for line in content.split("\n"):
        if line.strip().lower().startswith(field.lower() + ":"):
            return line.split(":", 1)[1].strip() or default
    return default


def _extract_criteria(content: str) -> list[str]:
    """Extract acceptance criteria from council output markdown."""
    criteria: list[str] = []
    in_criteria = False
    for line in content.split("\n"):
        if "acceptance" in line.lower() and "criteria" in line.lower():
            in_criteria = True
            continue
        if in_criteria:
            stripped = line.strip()
            if stripped.startswith(("-", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
                # Remove bullet/number prefix
                text = stripped.lstrip("-*0123456789. ").strip()
                if text:
                    criteria.append(text)
            elif stripped.startswith("#") or (stripped == "" and criteria):
                break  # End of criteria section
    return criteria


def _try_claude_code_bridge(prompt: str, pump_id: str, iteration: int) -> bool:
    """
    Attempt to execute coding task via Claude Code CLI (Gap 4 bridge).

    Claude Code (`claude`) is a CLI tool that can receive a prompt and
    execute coding tasks autonomously with file system access.

    Returns True if Claude Code executed successfully, False if unavailable.
    """
    if EXECUTION_MODE != "auto":
        log.info("Execution mode is 'manual' — skipping Claude Code bridge")
        return False

    # Circuit breaker guard
    if _claude_code_breaker.is_open:
        log.warning(
            "CircuitBreaker OPEN — skipping Claude Code bridge for %s (failures=%d). "
            "Will retry after cool-down.",
            pump_id,
            _claude_code_breaker._failures,
        )
        return False

    # Check if claude CLI is available
    claude_path = shutil.which("claude")
    if not claude_path:
        log.info("Claude Code CLI not found in PATH — falling back to manual mode")
        return False

    log.info(f"Claude Code CLI found at {claude_path} — attempting automated execution")

    # Fix #9: Isolate each execution in its own temp directory to prevent
    # cross-pump file contamination
    exec_tmpdir = tempfile.mkdtemp(
        prefix=f"ncl-exec-{pump_id}-v{iteration}-", dir=str(EXECUTION_DIR)
    )
    exec_working = Path(exec_tmpdir)

    # Fix #5: Clear stale working files from previous executions that could
    # cause false "work is done" signals
    if WORKING_FILES.exists():
        for old_file in WORKING_FILES.iterdir():
            if old_file.is_file():
                old_file.unlink()
            elif old_file.is_dir():
                shutil.rmtree(str(old_file), ignore_errors=True)

    # Build the prompt for Claude Code with isolated working directory context
    claude_prompt = (
        f"You are executing a NARTIX coding task.\n\n"
        f"Pump ID: {pump_id}\n"
        f"Iteration: {iteration}/{MAX_CODING_ITERATIONS}\n"
        f"Working directory: {exec_working}\n\n"
        f"Write all output files to: {exec_working}/\n\n"
        f"--- TASK ---\n{prompt}\n--- END TASK ---\n\n"
        f"Execute this task. Write code files to the working directory. "
        f"Do not ask questions — just implement based on the specification above."
    )

    # Write prompt to temp file for claude --prompt-file
    prompt_file = EXECUTION_DIR / f"claude-code-prompt-{pump_id}-v{iteration}.md"
    prompt_file.write_text(claude_prompt)

    # Fix #8: Start timer before subprocess
    t0 = time.monotonic()

    try:
        # Fix #6: Use Popen + process group so we can kill entire child tree on timeout
        proc = subprocess.Popen(
            [
                claude_path,
                "--print",  # Non-interactive: print output and exit
                "--max-turns",
                "10",
                "--output-format",
                "text",
                "-p",
                claude_prompt,
            ],
            cwd=str(exec_working),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
        )
        try:
            stdout, stderr = proc.communicate(timeout=300)  # 5 minute timeout
        except subprocess.TimeoutExpired:
            # Kill entire process group (setsid makes proc the group leader)
            try:
                os.killpg(os.getpgid(proc.pid), signal_mod.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
            proc.wait()
            log.warning(f"Claude Code timed out after 300s for {pump_id} — killed process group")
            _claude_code_breaker.record_failure()
            return False

        # Build a result-like namespace for downstream code
        class _Result:
            pass

        result = _Result()
        result.returncode = proc.returncode
        result.stdout = stdout
        result.stderr = stderr

        # Fix #8: Record elapsed time
        elapsed = time.monotonic() - t0

        # Save Claude Code output
        output_file = EXECUTION_DIR / f"claude-code-output-{pump_id}-v{iteration}.md"
        output_file.write_text(
            f"# Claude Code Output — {pump_id} (iteration {iteration})\n\n"
            f"## Exit Code: {result.returncode}\n"
            f"## Elapsed: {elapsed:.1f}s\n\n"
            f"## stdout\n```\n{result.stdout[-5000:] if result.stdout else '(empty)'}\n```\n\n"
            f"## stderr\n```\n{result.stderr[-2000:] if result.stderr else '(empty)'}\n```\n"
        )

        if result.returncode == 0:
            log.info(
                f"Claude Code executed successfully for {pump_id} iteration {iteration} ({elapsed:.1f}s)"
            )
            # Copy files from isolated temp dir to WORKING_FILES for downstream
            created_files = list(exec_working.glob("*"))
            for f in created_files:
                dest = WORKING_FILES / f.name
                if f.is_file():
                    shutil.copy2(str(f), str(dest))
                elif f.is_dir():
                    shutil.copytree(str(f), str(dest), dirs_exist_ok=True)
            log.info(f"Files in working directory: {[f.name for f in created_files]}")
            _claude_code_breaker.record_success()
            return True
        else:
            log.warning(f"Claude Code exited with code {result.returncode} ({elapsed:.1f}s)")
            _claude_code_breaker.record_failure()
            return False

    except Exception as e:
        log.error(f"Claude Code bridge failed: {e}")
        _claude_code_breaker.record_failure()
        return False
    finally:
        # Clean up isolated temp dir
        try:
            shutil.rmtree(exec_tmpdir, ignore_errors=True)
        except Exception:
            pass


def get_health() -> dict:
    """
    Return a health/status snapshot for the execution loop.

    Useful for launchd watchdogs, monitoring scripts, or the Brain /health endpoint.
    """
    return {
        "status": "ok",
        "circuit_breaker": {
            "state": "open" if _claude_code_breaker.is_open else "closed",
            "consecutive_failures": _claude_code_breaker._failures,
            "open_until": (
                datetime.fromtimestamp(
                    _claude_code_breaker._open_until, tz=timezone.utc
                ).isoformat()
                if _claude_code_breaker._open_until > 0
                else None
            ),
        },
        "execution_mode": EXECUTION_MODE,
        "max_coding_iterations": MAX_CODING_ITERATIONS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run_execution_loop(pump_id: str, start_iteration: int = 1) -> dict:
    """
    Run the full hybrid execution loop for a pump.

    Attempts Claude Code CLI bridge first (automated), falls back to
    manual Copilot prompt mode if Claude Code is unavailable.

    Returns a feedback payload dict suitable for iPhone pump-back.
    The function never raises — all unhandled exceptions are caught,
    logged with full traceback, and returned as an 'error' feedback payload.
    """
    # Validate pump_id — must be a non-empty alphanumeric slug
    if not pump_id or not all(c.isalnum() or c in "-_." for c in pump_id):
        err = f"Invalid pump_id: '{pump_id}' — must be alphanumeric with hyphens/underscores/dots"
        log.error(err)
        return create_feedback_payload(
            pump_id=pump_id or "unknown",
            status="error",
            summary=err,
            artifacts=[],
            iterations=0,
            review_rounds=0,
        )

    # Validate iteration range
    if not (1 <= start_iteration <= MAX_CODING_ITERATIONS):
        err = f"Invalid start_iteration={start_iteration}, must be 1..{MAX_CODING_ITERATIONS}"
        log.error(err)
        return create_feedback_payload(
            pump_id=pump_id,
            status="error",
            summary=err,
            artifacts=[],
            iterations=0,
            review_rounds=0,
        )

    log.info(f"Execution loop started for pump: {pump_id}")

    try:
        return _run_execution_loop_inner(pump_id, start_iteration)
    except Exception as e:
        log.exception(
            "Execution loop for pump '%s' crashed unexpectedly: %s",
            pump_id,
            e,
        )
        return create_feedback_payload(
            pump_id=pump_id,
            status="error",
            summary=f"Execution loop crashed: {e}",
            artifacts=[],
            iterations=start_iteration,
            review_rounds=0,
        )


def _run_execution_loop_inner(pump_id: str, start_iteration: int = 1) -> dict:
    """Inner implementation — called by run_execution_loop with outer try/except."""
    # Fix #8: Start timing at the beginning of execution
    loop_start_time = time.monotonic()

    task_plan = load_task_plan(pump_id)
    council_output = load_council_output(pump_id)

    iteration = start_iteration
    issues: list[str] = []

    while iteration <= MAX_CODING_ITERATIONS:
        log.info(f"Building Copilot prompt — iteration {iteration}/{MAX_CODING_ITERATIONS}")

        prompt = build_copilot_prompt(
            task_plan,
            council_output,
            iteration=iteration,
            previous_issues=issues if iteration > 1 else None,
        )
        prompt_path = write_copilot_prompt(prompt, pump_id, iteration)

        log.info(f"Prompt ready at {prompt_path}")

        # Try automated execution via Claude Code CLI (Gap 4 bridge)
        if _try_claude_code_bridge(prompt, pump_id, iteration):
            log.info(f"Claude Code completed iteration {iteration} — auto-reviewing")
            # Auto-review: check if working files exist
            created = list(WORKING_FILES.glob("*"))
            if created:
                log.info(f"Auto-execution produced {len(created)} files — proceeding to sign-off")
                summary = f"Auto-executed via Claude Code CLI (iteration {iteration}, {len(created)} files)"
                feedback = run_sign_off(pump_id, summary, iterations=iteration)
                # Fix #8: Record actual execution time
                feedback["metrics"]["total_time_seconds"] = round(
                    time.monotonic() - loop_start_time, 1
                )
                return feedback
            else:
                log.warning("Claude Code ran but produced no files — retrying")
                issues.append("Claude Code produced no output files")
                iteration += 1
                continue

        # Manual mode fallback — write prompt and wait for human
        log.info(f"Waiting for manual Copilot output in {WORKING_FILES}/")

        if iteration == 1:
            # First iteration — just write the prompt and return
            print(f"\n{'='*60}")
            print(f"  COPILOT PROMPT READY — Iteration {iteration}/{MAX_CODING_ITERATIONS}")
            print(f"  Pump: {pump_id}")
            print(f"{'='*60}")
            print(f"\n  Prompt: {prompt_path}")
            print(f"  Working files: {WORKING_FILES}/")
            print("\n  Next steps:")
            print("  1. Send prompt to Copilot Chat in VS Code")
            print("  2. Copilot generates code in working-files/")
            print(f"  3. Run: python3 -m runtime.execution_loop {pump_id} --review")
            print("     to proceed to review phase")
            break

        iteration += 1

    # If max iterations reached, escalate
    if iteration > MAX_CODING_ITERATIONS:
        log.warning(
            f"Max coding iterations ({MAX_CODING_ITERATIONS}) reached — escalating to NATRIX"
        )
        return create_feedback_payload(
            pump_id=pump_id,
            status="escalated",
            summary=f"Max {MAX_CODING_ITERATIONS} iterations reached. Issues: {'; '.join(issues)}",
            artifacts=[],
            iterations=MAX_CODING_ITERATIONS,
            review_rounds=0,
        )

    return create_feedback_payload(
        pump_id=pump_id,
        status="prompt_ready",
        summary=f"Copilot prompt ready (iteration {iteration})",
        artifacts=[str(prompt_path)],
        iterations=iteration,
        review_rounds=0,
    )


def run_sign_off(pump_id: str, summary: str, iterations: int = 1) -> dict:
    """Sign off execution, stage for review, and produce output."""
    create_signed_off(pump_id, iterations, summary)
    stage_for_review(pump_id)

    feedback = create_feedback_payload(
        pump_id=pump_id,
        status="complete",
        summary=summary,
        artifacts=[f.name for f in WORKING_FILES.iterdir() if f.is_file()]
        if WORKING_FILES.exists()
        else [],
        iterations=iterations,
        review_rounds=0,
    )

    stage_for_output(pump_id, feedback)
    log.info(f"Execution complete for {pump_id} — staged in 05-Output/")
    return feedback


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 -m runtime.execution_loop <pump-id>          Build Copilot prompt")
        print(
            "  python3 -m runtime.execution_loop <pump-id> --review  Sign off and stage for review"
        )
        print(
            "  python3 -m runtime.execution_loop <pump-id> --iterate <n>  Build fix prompt (iteration n)"
        )
        sys.exit(1)

    pump_id = sys.argv[1].strip()
    if not pump_id or not all(c.isalnum() or c in "-_." for c in pump_id):
        log.error(f"Invalid pump_id: '{pump_id}' — must be alphanumeric with hyphens/underscores")
        sys.exit(1)

    # Parse mode
    mode = "prompt"
    iteration = 1
    if "--review" in sys.argv:
        mode = "review"
    elif "--iterate" in sys.argv:
        mode = "iterate"
        try:
            idx = sys.argv.index("--iterate")
            iteration = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            log.error("--iterate requires an iteration number (e.g., --iterate 2)")
            sys.exit(1)

    if mode == "review":
        summary = input("Sign-off summary: ") if sys.stdin.isatty() else "Execution complete"
        feedback = run_sign_off(pump_id, summary)
        print(f"\nSign-off complete. Feedback: {json.dumps(feedback, indent=2)}")
    elif mode == "iterate":
        feedback = run_execution_loop(pump_id, start_iteration=iteration)
        print(f"\nIteration {iteration} prompt ready.")
    else:
        feedback = run_execution_loop(pump_id)
        print(f"\nExecution loop result: {feedback['status']}")
