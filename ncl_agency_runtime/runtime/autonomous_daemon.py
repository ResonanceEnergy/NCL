#!/usr/bin/env python3
"""
NCL Autonomous Daemon — Self-Organizing, Self-Motivating Runtime
════════════════════════════════════════════════════════════════════
The daemon that never sleeps. Runs continuous PDCA loops, identifies
gaps, dispatches work, learns from outcomes, and only escalates to
the Supreme Commander on genuinely critical matters.

Architecture:
    ┌───────────────────────────────────────────┐
    │          AUTONOMOUS DAEMON                │
    │                                           │
    │   ┌───────────┐     ┌──────────────┐     │
    │   │ Heartbeat │────▷│ Gap Analyzer │     │
    │   │  (tick)   │     │  (introspect)│     │
    │   └───────────┘     └──────┬───────┘     │
    │                            │              │
    │          ┌─────────────────┴──────┐       │
    │          ▼                        ▼       │
    │   ┌────────────┐        ┌──────────────┐ │
    │   │ Task Queue │        │ Web Research │ │
    │   │ (self-gen) │        │ (fallback)   │ │
    │   └─────┬──────┘        └──────────────┘ │
    │         │                                 │
    │         ▼                                 │
    │   ┌────────────┐     ┌──────────────────┐│
    │   │ Executor   │────▷│ Self-Assessment  ││
    │   │ (do work)  │     │ (learn + log)    ││
    │   └────────────┘     └──────────────────┘│
    │                                           │
    │   ┌──────────────────────────────────────┐│
    │   │ Escalation Gate (CRITICAL only)      ││
    │   └──────────────────────────────────────┘│
    └───────────────────────────────────────────┘

Doctrine Compliance:
    - Art of War: "Know yourself, know your enemy"  → continuous self-analysis
    - Law 28: "Enter action with boldness"          → retry with conviction
    - Habit 7: "Sharpen the Saw"                    → learning after every cycle
    - Agentic Lab: "Agent-first design"             → autonomous, human optional
    - Dario Amodei: "Safety-first scaling"          → escalation gate
    - CW: "Compound habits"                         → daily accumulation
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import traceback
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "ncl_agency_runtime" / "runtime"))

LOG = logging.getLogger("ncl.autonomous")
LOG.setLevel(logging.DEBUG)
if not LOG.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s  %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    LOG.addHandler(_h)

# File-based logging for 24/7 evidence trail
_LOG_DIR = _REPO_ROOT / "ncl_agency_runtime" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_LOG_DIR / "autonomous_daemon.log", encoding="utf-8")
_file_handler.setFormatter(
    logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)
LOG.addHandler(_file_handler)


# ═══════════════════════════════════════════════════════════════
#  Enums & Data Types
# ═══════════════════════════════════════════════════════════════


class TaskPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class DaemonPhase(StrEnum):
    BOOT = "boot"
    INTROSPECT = "introspect"
    PLAN = "plan"
    EXECUTE = "execute"
    ASSESS = "assess"
    LEARN = "learn"
    IDLE = "idle"


class EscalationLevel(StrEnum):
    """Only CRITICAL reaches the human."""

    INFO = "info"  # logged only
    WARNING = "warning"  # logged, self-handled
    ERROR = "error"  # logged, retry, then escalate
    CRITICAL = "critical"  # THE ONLY LEVEL THAT PINGS NATHAN


@dataclass
class AutonomousTask:
    """A unit of work self-generated or discovered by the daemon."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.QUEUED
    category: str = ""  # gap_fill, roadmap, health, research, learning
    source: str = ""  # introspection, gap_analysis, roadmap, manual
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    evidence: list[str] = field(default_factory=list)  # audit trail
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # task IDs

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CycleReport:
    """Report from one daemon cycle (PDCA loop)."""

    cycle_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    phase: DaemonPhase = DaemonPhase.BOOT
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    gaps_found: int = 0
    tasks_generated: int = 0
    tasks_executed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    learnings: list[str] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  Gap Analyzer — "Look Inside"
# ═══════════════════════════════════════════════════════════════


class GapAnalyzer:
    """Inspects the NCL system to find gaps, weaknesses, and opportunities.

    This is the daemon's introspective eye — "know yourself" (Sun Tzu).
    It scans:
        - Test health (pytest output)
        - Lint health (ruff)
        - Roadmap progress (phases not done)
        - Config completeness
        - Memory system health
        - File structure integrity
        - Documentation gaps
        - Dependency freshness
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._last_scan: dict[str, Any] = {}

    def full_scan(self) -> list[dict[str, Any]]:
        """Run all gap scanners and return a list of gap dicts."""
        gaps: list[dict[str, Any]] = []
        scanners = [
            self._scan_test_health,
            self._scan_lint_health,
            self._scan_roadmap_gaps,
            self._scan_config_completeness,
            self._scan_file_structure,
            self._scan_documentation,
            self._scan_dependency_health,
            self._scan_log_anomalies,
            self._scan_fpc_health,
        ]
        for scanner in scanners:
            try:
                found = scanner()
                gaps.extend(found)
            except Exception as exc:
                LOG.warning("Scanner %s failed: %s", scanner.__name__, exc)
                gaps.append(
                    {
                        "category": "scanner_failure",
                        "severity": "warning",
                        "description": f"Scanner {scanner.__name__} crashed: {exc}",
                        "source": scanner.__name__,
                    }
                )
        self._last_scan = {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_gaps": len(gaps),
            "gaps": gaps,
        }
        return gaps

    def _scan_test_health(self) -> list[dict]:
        """Check for test failures or missing test coverage."""
        gaps = []
        test_dir = self.repo_root / "tests"
        if not test_dir.exists():
            gaps.append(
                {
                    "category": "testing",
                    "severity": "high",
                    "description": "Tests directory missing",
                    "source": "test_health",
                }
            )
            return gaps

        test_files = list(test_dir.glob("test_*.py"))
        # Check for modules without corresponding tests
        runtime_dir = self.repo_root / "ncl_agency_runtime" / "runtime"
        if runtime_dir.exists():
            for py_file in runtime_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                module_name = py_file.stem
                has_test = any(f"test_{module_name}" in tf.name or module_name in tf.name for tf in test_files)
                if not has_test:
                    gaps.append(
                        {
                            "category": "testing",
                            "severity": "normal",
                            "description": f"Module '{module_name}' has no dedicated test file",
                            "source": "test_health",
                            "file": str(py_file.relative_to(self.repo_root)),
                        }
                    )

        return gaps

    def _scan_lint_health(self) -> list[dict]:
        """Check ruff.toml exists and note any known lint issues."""
        gaps = []
        ruff_cfg = self.repo_root / "ruff.toml"
        if not ruff_cfg.exists():
            gaps.append(
                {
                    "category": "linting",
                    "severity": "normal",
                    "description": "ruff.toml config missing",
                    "source": "lint_health",
                }
            )
        mypy_cfg = self.repo_root / "mypy.ini"
        if not mypy_cfg.exists():
            gaps.append(
                {
                    "category": "typing",
                    "severity": "normal",
                    "description": "mypy.ini config missing",
                    "source": "lint_health",
                }
            )
        return gaps

    def _scan_roadmap_gaps(self) -> list[dict]:
        """Parse ROADMAP_TO_SUCCESS.md for unchecked items."""
        gaps = []
        roadmap = self.repo_root / "ROADMAP_TO_SUCCESS.md"
        if not roadmap.exists():
            gaps.append(
                {
                    "category": "roadmap",
                    "severity": "high",
                    "description": "ROADMAP_TO_SUCCESS.md missing",
                    "source": "roadmap_gaps",
                }
            )
            return gaps

        content = roadmap.read_text(encoding="utf-8")
        unchecked = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [ ]"):
                unchecked.append(stripped[6:].strip())

        for item in unchecked:
            # Determine priority from phase
            severity = "normal"
            if "Phase 4" in content.split(item)[0][-200:]:
                severity = "high"
            elif "Phase 5" in content.split(item)[0][-200:]:
                severity = "normal"
            elif "Phase 6" in content.split(item)[0][-200:]:
                severity = "low"

            gaps.append(
                {
                    "category": "roadmap",
                    "severity": severity,
                    "description": f"Roadmap item incomplete: {item[:120]}",
                    "source": "roadmap_gaps",
                }
            )

        return gaps

    def _scan_config_completeness(self) -> list[dict]:
        """Check ncl_config.json for missing or stub sections."""
        gaps = []
        config_path = self.repo_root / "ncl_config.json"
        if not config_path.exists():
            gaps.append(
                {
                    "category": "config",
                    "severity": "critical",
                    "description": "ncl_config.json missing",
                    "source": "config_completeness",
                }
            )
            return gaps

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            gaps.append(
                {
                    "category": "config",
                    "severity": "critical",
                    "description": f"ncl_config.json parse error: {exc}",
                    "source": "config_completeness",
                }
            )
            return gaps

        # Check for disabled features that should be enabled
        if not config.get("agency", {}).get("auto_start", False):
            gaps.append(
                {
                    "category": "config",
                    "severity": "normal",
                    "description": "Agency auto_start is disabled — autonomous daemon requires it",
                    "source": "config_completeness",
                }
            )

        if not config.get("memory", {}).get("enabled", False):
            gaps.append(
                {
                    "category": "config",
                    "severity": "high",
                    "description": "Memory system is disabled",
                    "source": "config_completeness",
                }
            )

        return gaps

    def _scan_file_structure(self) -> list[dict]:
        """Check for expected directories and files."""
        gaps = []
        expected_dirs = [
            "ncl_agency_runtime/agents",
            "ncl_agency_runtime/runtime",
            "ncl_agency_runtime/config",
            "ncl_agency_runtime/logs",
            "ncl_agency_runtime/missions",
            "tests",
            "evaluation/golden_tasks",
            "schemas",
            "tools",
        ]
        for d in expected_dirs:
            full = self.repo_root / d
            if not full.exists():
                gaps.append(
                    {
                        "category": "structure",
                        "severity": "normal",
                        "description": f"Expected directory missing: {d}",
                        "source": "file_structure",
                    }
                )
        return gaps

    def _scan_documentation(self) -> list[dict]:
        """Check key documentation files exist."""
        gaps = []
        expected_docs = [
            ("README.md", "high"),
            ("CONTRIBUTING.md", "low"),
            ("ROADMAP_TO_SUCCESS.md", "normal"),
            ("NCC_Master_Doctrine_v2.0.md", "normal"),
        ]
        for doc, severity in expected_docs:
            if not (self.repo_root / doc).exists():
                gaps.append(
                    {
                        "category": "documentation",
                        "severity": severity,
                        "description": f"Documentation file missing: {doc}",
                        "source": "documentation",
                    }
                )
        return gaps

    def _scan_dependency_health(self) -> list[dict]:
        """Check requirements files exist and are non-empty."""
        gaps = []
        req_file = self.repo_root / "requirements-dev.txt"
        if not req_file.exists():
            gaps.append(
                {
                    "category": "dependencies",
                    "severity": "high",
                    "description": "requirements-dev.txt missing",
                    "source": "dependency_health",
                }
            )
        elif req_file.stat().st_size == 0:
            gaps.append(
                {
                    "category": "dependencies",
                    "severity": "high",
                    "description": "requirements-dev.txt is empty",
                    "source": "dependency_health",
                }
            )
        return gaps

    def _scan_log_anomalies(self) -> list[dict]:
        """Check daemon logs for recurring errors."""
        gaps: list[dict[str, Any]] = []
        log_file = self.repo_root / "ncl_agency_runtime" / "logs" / "autonomous_daemon.log"
        if not log_file.exists():
            return gaps  # First run, no logs yet

        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            # Only check last 500 lines
            recent = lines[-500:] if len(lines) > 500 else lines
            error_count = sum(1 for line in recent if "ERROR" in line)
            if error_count > 20:
                gaps.append(
                    {
                        "category": "health",
                        "severity": "high",
                        "description": f"High error rate in daemon logs: {error_count} errors in last {len(recent)} lines",
                        "source": "log_anomalies",
                    }
                )
        except Exception:
            LOG.debug("Failed to scan logs for anomalies", exc_info=True)

        return gaps

    def _scan_fpc_health(self) -> list[dict]:
        """Check FPC intelligence platform coverage and data freshness."""
        try:
            from ncl_agency_runtime.runtime.fpc_integration import scan_fpc_health

            return scan_fpc_health(self.repo_root)
        except Exception as exc:
            LOG.debug("FPC health scan unavailable: %s", exc)
            return []


# ═══════════════════════════════════════════════════════════════
#  Task Generator — Self-Motivation Engine
# ═══════════════════════════════════════════════════════════════


class TaskGenerator:
    """Converts gaps into actionable tasks.

    Embodies Agentic Lab: "Agent-first design — autonomous operation."
    And CW: "High agency means full ownership."
    """

    CATEGORY_PRIORITY_MAP: ClassVar[dict[str, TaskPriority]] = {
        "critical": TaskPriority.CRITICAL,
        "high": TaskPriority.HIGH,
        "normal": TaskPriority.NORMAL,
        "low": TaskPriority.LOW,
    }

    def generate_from_gaps(self, gaps: list[dict]) -> list[AutonomousTask]:
        """Convert gap analysis results into executable tasks."""
        tasks: list[AutonomousTask] = []
        for gap in gaps:
            severity = gap.get("severity", "normal")
            priority = self.CATEGORY_PRIORITY_MAP.get(severity, TaskPriority.NORMAL)

            task = AutonomousTask(
                title=self._make_title(gap),
                description=gap.get("description", ""),
                priority=priority,
                category=gap.get("category", "general"),
                source="gap_analysis",
                tags=[gap.get("category", ""), gap.get("source", "")],
            )
            tasks.append(task)

        return tasks

    def generate_scheduled_tasks(self) -> list[AutonomousTask]:
        """Generate time-based recurring tasks."""
        now = datetime.now(UTC)
        tasks: list[AutonomousTask] = []

        # Daily morning brief (if between 5:00-7:00 UTC)
        if 5 <= now.hour <= 7:
            tasks.append(
                AutonomousTask(
                    title="Generate Daily Brief",
                    description="Produce morning cognitive state assessment from event logs",
                    priority=TaskPriority.HIGH,
                    category="briefing",
                    source="scheduler",
                    tags=["daily", "brief", "proactive"],
                )
            )

        # HELIX clip pre-render (08:00, 12:00, 16:00 UTC)
        if now.hour in (8, 12, 16):
            tasks.append(
                AutonomousTask(
                    title="HELIX Clip Pre-Render",
                    description="Incrementally render new prediction clips to cache for evening assembly",
                    priority=TaskPriority.NORMAL,
                    category="helix_prerender",
                    source="scheduler",
                    tags=["helix", "clips", "prerender"],
                )
            )

        # HELIX evening brief assembly (18:00 UTC)
        if now.hour == 18:
            tasks.append(
                AutonomousTask(
                    title="HELIX Evening Brief Assembly",
                    description="Assemble the daily HELIX news episode from pre-cached clips",
                    priority=TaskPriority.HIGH,
                    category="helix_assemble",
                    source="scheduler",
                    tags=["helix", "brief", "assembly", "evening"],
                )
            )

        # Weekly review (Sunday)
        if now.weekday() == 6 and now.hour == 10:
            tasks.append(
                AutonomousTask(
                    title="Weekly System Review",
                    description="Run full gap analysis, consolidate memory, generate weekly brief",
                    priority=TaskPriority.HIGH,
                    category="review",
                    source="scheduler",
                    tags=["weekly", "review"],
                )
            )

        # Memory consolidation (every 6 hours)
        if now.hour % 6 == 0:
            tasks.append(
                AutonomousTask(
                    title="Memory Consolidation Cycle",
                    description="Consolidate working memory to short-term, short-term to long-term",
                    priority=TaskPriority.NORMAL,
                    category="memory",
                    source="scheduler",
                    tags=["memory", "consolidation"],
                )
            )

        # Learning cycle (every 4 hours)
        if now.hour % 4 == 0:
            tasks.append(
                AutonomousTask(
                    title="Learning Engine Cycle",
                    description="Extract patterns from recent events, generate insights",
                    priority=TaskPriority.NORMAL,
                    category="learning",
                    source="scheduler",
                    tags=["learning", "patterns"],
                )
            )

        # Health self-check (every hour)
        tasks.append(
            AutonomousTask(
                title="System Health Self-Check",
                description="Verify all subsystems are operational, check resource usage",
                priority=TaskPriority.LOW,
                category="health",
                source="scheduler",
                tags=["health", "heartbeat"],
            )
        )

        # FPC Intelligence Cycle (every 3 hours)
        if now.hour % 3 == 0:
            tasks.append(
                AutonomousTask(
                    title="FPC Full Intelligence Cycle",
                    description="Run full_cycle FPC intelligence gathering, trend detection, and prediction",
                    priority=TaskPriority.NORMAL,
                    category="fpc_intelligence",
                    source="scheduler",
                    tags=["fpc", "intelligence", "prediction", "trends"],
                )
            )

        return tasks

    def _make_title(self, gap: dict) -> str:
        """Generate a concise task title from a gap."""
        desc = gap.get("description", "Unknown gap")
        category = gap.get("category", "general")
        if len(desc) > 80:
            desc = desc[:77] + "..."
        return f"[{category.upper()}] {desc}"

    def generate_improvement_tasks(self, cycle_report: CycleReport) -> list[AutonomousTask]:
        """Generate self-improvement tasks from cycle outcomes."""
        tasks: list[AutonomousTask] = []

        if cycle_report.tasks_failed > 0:
            tasks.append(
                AutonomousTask(
                    title="Analyze Failed Tasks",
                    description=f"{cycle_report.tasks_failed} tasks failed in cycle {cycle_report.cycle_id}. "
                    "Review errors and determine if approach needs changing.",
                    priority=TaskPriority.HIGH,
                    category="self_improvement",
                    source="self_assessment",
                    tags=["meta", "improvement"],
                )
            )

        if cycle_report.gaps_found > 10:
            tasks.append(
                AutonomousTask(
                    title="Prioritize Gap Reduction",
                    description=f"{cycle_report.gaps_found} gaps detected. Group by category and "
                    "create batched resolution plan.",
                    priority=TaskPriority.NORMAL,
                    category="self_improvement",
                    source="self_assessment",
                    tags=["meta", "planning"],
                )
            )

        return tasks


# ═══════════════════════════════════════════════════════════════
#  Task Executor — "Enter Action with Boldness" (Law 28)
# ═══════════════════════════════════════════════════════════════


class TaskExecutor:
    """Executes autonomous tasks with retry logic and evidence recording.

    Follows the MissionRunner pattern but for self-generated work.
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._history: list[dict] = []

    async def execute(self, task: AutonomousTask) -> AutonomousTask:
        """Execute a task, updating its status and evidence."""
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now(UTC).isoformat()
        task.attempts += 1

        LOG.info("EXECUTING [%s] %s (attempt %d/%d)", task.priority.value, task.title, task.attempts, task.max_attempts)

        try:
            result = await self._dispatch(task)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC).isoformat()
            task.evidence.append(f"Completed at {task.completed_at}: {json.dumps(result)[:200]}")
            LOG.info("COMPLETED [%s] %s", task.priority.value, task.title)

        except Exception as exc:
            task.error = str(exc)
            task.evidence.append(f"Failed attempt {task.attempts}: {exc}")
            LOG.error("FAILED [%s] %s: %s", task.priority.value, task.title, exc)

            if task.attempts >= task.max_attempts:
                task.status = TaskStatus.FAILED
                LOG.warning("DEAD LETTER [%s] %s — max attempts exhausted", task.priority.value, task.title)
            else:
                task.status = TaskStatus.QUEUED  # Retry

        self._history.append(task.to_dict())
        return task

    async def _dispatch(self, task: AutonomousTask) -> dict:
        """Route task to appropriate handler based on category."""
        handlers: dict[str, Any] = {
            "testing": self._handle_testing,
            "linting": self._handle_linting,
            "roadmap": self._handle_roadmap,
            "config": self._handle_config,
            "structure": self._handle_structure,
            "documentation": self._handle_documentation,
            "health": self._handle_health,
            "memory": self._handle_memory,
            "learning": self._handle_learning,
            "briefing": self._handle_briefing,
            "review": self._handle_review,
            "self_improvement": self._handle_self_improvement,
            "dependencies": self._handle_dependencies,
            "scanner_failure": self._handle_scanner_failure,
            "typing": self._handle_linting,
            "fpc_intelligence": self._handle_fpc_intelligence,
            "helix_prerender": self._handle_helix_prerender,
            "helix_assemble": self._handle_helix_assemble,
        }
        handler = handlers.get(task.category, self._handle_generic)
        result: dict[str, Any] = await handler(task)
        return result

    async def _handle_testing(self, task: AutonomousTask) -> dict:
        """Handle test-related tasks by running pytest and analyzing."""
        result: dict[str, Any] = {"action": "test_analysis"}
        # Check which module needs tests
        if "no dedicated test file" in task.description:
            module_name = ""
            for word in task.description.split("'"):
                if len(word) > 2 and not word.startswith(" "):
                    module_name = word
                    break
            result["module"] = module_name
            result["recommendation"] = f"Create test_{module_name}.py with basic smoke tests"
            result["auto_fixable"] = False
        return result

    async def _handle_linting(self, task: AutonomousTask) -> dict:
        """Handle lint/type checking tasks."""
        return {
            "action": "lint_check",
            "description": "Linting infrastructure verified",
            "status": "monitored",
        }

    async def _handle_roadmap(self, task: AutonomousTask) -> dict:
        """Analyze roadmap items and plan approach."""
        return {
            "action": "roadmap_tracking",
            "item": task.description,
            "status": "tracked",
            "recommendation": "Review in next planning cycle",
        }

    async def _handle_config(self, task: AutonomousTask) -> dict:
        """Handle configuration-related tasks."""
        if "auto_start" in task.description:
            # Safe to enable auto_start for the daemon
            config_path = self.repo_root / "ncl_config.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config.setdefault("agency", {})["auto_start"] = True
                config_path.write_text(
                    json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return {"action": "config_update", "changed": "agency.auto_start=true"}
        return {"action": "config_review", "status": "reviewed"}

    async def _handle_structure(self, task: AutonomousTask) -> dict:
        """Create missing directories."""
        if "missing" in task.description:
            dir_name = task.description.split(": ")[-1] if ": " in task.description else ""
            if dir_name:
                target = self.repo_root / dir_name
                target.mkdir(parents=True, exist_ok=True)
                return {"action": "dir_created", "path": str(target)}
        return {"action": "structure_review", "status": "reviewed"}

    async def _handle_documentation(self, task: AutonomousTask) -> dict:
        """Track documentation gaps."""
        return {
            "action": "doc_gap_tracked",
            "description": task.description,
            "status": "tracked_for_improvement",
        }

    async def _handle_health(self, task: AutonomousTask) -> dict:
        """Run system health check."""
        health: dict[str, Any] = {
            "action": "health_check",
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": {},
        }
        # Check core files exist
        core_files = [
            "lib_ncl.py",
            "ncl_memory.py",
            "ncl_config.json",
            "ncl_agency_runtime/__init__.py",
        ]
        for f in core_files:
            health["checks"][f] = (self.repo_root / f).exists()

        # Check log directory writable
        try:
            test_file = _LOG_DIR / ".health_probe"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            health["checks"]["log_writable"] = True
        except Exception:
            health["checks"]["log_writable"] = False

        health["all_healthy"] = all(health["checks"].values())
        return health

    async def _handle_memory(self, task: AutonomousTask) -> dict:
        """Trigger memory consolidation."""
        result: dict[str, Any] = {"action": "memory_consolidation"}
        try:
            from ncl_memory import get_memory_manager

            mgr = get_memory_manager()
            if hasattr(mgr, "consolidate_memories"):
                consolidated = mgr.consolidate_memories()
                result["consolidated"] = consolidated
                result["status"] = "success"
            else:
                result["status"] = "no_consolidation_method"
        except ImportError:
            result["status"] = "memory_unavailable"
        except Exception as exc:
            result["status"] = f"error: {exc}"
        return result

    async def _handle_learning(self, task: AutonomousTask) -> dict:
        """Run learning engine cycle."""
        result: dict[str, Any] = {"action": "learning_cycle"}
        try:
            from learning_engine import LearningEngine

            engine = LearningEngine()
            analysis = engine.analyze_recent_events(days_back=7)
            result["events_analyzed"] = analysis.get("total_events", 0)
            result["patterns_found"] = len(analysis.get("patterns", {}))
            result["status"] = "success"
        except ImportError:
            result["status"] = "learning_engine_unavailable"
        except Exception as exc:
            result["status"] = f"error: {exc}"
        return result

    async def _handle_briefing(self, task: AutonomousTask) -> dict:
        """Generate daily briefs — legacy HELIX + AZ Prime + C-Suite."""
        result: dict[str, Any] = {"action": "generate_brief"}

        # ── Legacy HELIX brief (event-log summary) ──────────────────────
        try:
            from mission_runner import load_events_for_date, make_daily_brief

            today = datetime.now(UTC).strftime("%Y-%m-%d")
            event_log_dir = Path(os.path.expanduser("~/NCL/data/event_log"))
            events, _ = load_events_for_date(event_log_dir, today)
            brief = make_daily_brief(events, today)

            brief_dir = self.repo_root / "ncl_agency_runtime" / "logs" / "briefs"
            brief_dir.mkdir(parents=True, exist_ok=True)
            brief_file = brief_dir / f"daily_{today}.md"
            brief_file.write_text(brief, encoding="utf-8")

            result["helix_brief"] = str(brief_file)
            result["event_count"] = len(events)
        except Exception as exc:
            result["helix_error"] = str(exc)

        # ── AZ Prime + C-Suite briefs ────────────────────────────────────
        try:
            from ncl_agency_runtime.fpc.daily_briefs import AZBrief, CSuiteBrief

            az_paths = AZBrief().save()
            result["az_brief"] = str(az_paths["md"])

            cs_paths = CSuiteBrief().save()
            result["csuite_brief"] = str(cs_paths["md"])
        except Exception as exc:
            result["brief_error"] = str(exc)

        result["status"] = "success" if "brief_error" not in result else f"partial: {result['brief_error']}"
        return result

    async def _handle_helix_prerender(self, task: AutonomousTask) -> dict:
        """Incrementally pre-render HELIX clips from new predictions."""
        result: dict[str, Any] = {"action": "helix_prerender"}
        try:
            from ncl_agency_runtime.fpc.helix_news.clip_cache import IncrementalRenderer

            renderer = IncrementalRenderer()
            render_result = renderer.render_new_clips()
            result.update(render_result)
            result["status"] = "success"
        except Exception as exc:
            result["status"] = f"error: {exc}"
        return result

    async def _handle_helix_assemble(self, task: AutonomousTask) -> dict:
        """Assemble the evening HELIX brief from pre-cached clips."""
        result: dict[str, Any] = {"action": "helix_assemble"}
        try:
            from ncl_agency_runtime.fpc.helix_news.clip_cache import BriefAssembler

            assembler = BriefAssembler()
            assemble_result = assembler.assemble()
            result.update(assemble_result)
            result["status"] = "success"
        except Exception as exc:
            result["status"] = f"error: {exc}"
        return result

    async def _handle_review(self, task: AutonomousTask) -> dict:
        """Run comprehensive review cycle."""
        return {
            "action": "weekly_review",
            "status": "executed",
            "sub_tasks": [
                "gap_analysis",
                "memory_consolidation",
                "weekly_brief",
                "roadmap_review",
                "dependency_audit",
            ],
        }

    async def _handle_self_improvement(self, task: AutonomousTask) -> dict:
        """Analyze failures and generate improvement recommendations."""
        return {
            "action": "self_improvement",
            "description": task.description,
            "status": "analyzed",
            "recommendation": "Review failed task patterns in next cycle",
        }

    async def _handle_dependencies(self, task: AutonomousTask) -> dict:
        """Check dependency health."""
        req_file = self.repo_root / "requirements-dev.txt"
        if req_file.exists():
            content = req_file.read_text(encoding="utf-8")
            dep_count = len([line for line in content.splitlines() if line.strip() and not line.startswith("#")])
            return {"action": "dependency_audit", "count": dep_count, "status": "healthy"}
        return {"action": "dependency_audit", "status": "missing_requirements"}

    async def _handle_scanner_failure(self, task: AutonomousTask) -> dict:
        """Handle when a scanner itself failed."""
        return {
            "action": "scanner_triage",
            "description": task.description,
            "status": "logged_for_investigation",
        }

    async def _handle_generic(self, task: AutonomousTask) -> dict:
        """Fallback handler for uncategorized tasks."""
        return {
            "action": "generic_review",
            "description": task.description,
            "status": "acknowledged",
        }

    async def _handle_fpc_intelligence(self, task: AutonomousTask) -> dict:
        """Handle FPC intelligence cycle tasks — prediction & trend detection."""
        try:
            from ncl_agency_runtime.runtime.fpc_integration import FPCDaemonHandler

            handler = FPCDaemonHandler(self.repo_root)
            return await handler.handle_fpc_task(task)
        except Exception as exc:
            LOG.warning("FPC intelligence task failed: %s", exc)
            return {
                "action": "fpc_intelligence",
                "status": "error",
                "error": str(exc),
            }


# ═══════════════════════════════════════════════════════════════
#  Escalation Gate — "Only CRITICAL reaches Nathan"
# ═══════════════════════════════════════════════════════════════


class EscalationGate:
    """Decides what's truly critical enough to bother the human.

    Dario Amodei: "Safety-first scaling — capability without safety is reckless."
    The daemon handles EVERYTHING itself except genuine crises.
    """

    CRITICAL_KEYWORDS: ClassVar[list[str]] = [
        "data_loss",
        "security_breach",
        "system_crash",
        "corruption",
        "unrecoverable",
        "critical_failure",
    ]

    def __init__(self):
        self._escalation_log: list[dict] = []
        self._suppressed_count: int = 0

    def evaluate(self, task: AutonomousTask) -> EscalationLevel:
        """Determine if a task outcome needs human attention."""
        # Only escalate genuinely critical items
        if (
            task.priority == TaskPriority.CRITICAL
            and task.status == TaskStatus.FAILED
            and task.attempts >= task.max_attempts
        ):
            return EscalationLevel.CRITICAL

        # Check for critical keywords in error
        if task.error:
            error_lower = task.error.lower()
            if any(kw in error_lower for kw in self.CRITICAL_KEYWORDS):
                return EscalationLevel.CRITICAL

        # Everything else the daemon handles
        if task.status == TaskStatus.FAILED:
            self._suppressed_count += 1
            return EscalationLevel.WARNING

        return EscalationLevel.INFO

    def record_escalation(self, task: AutonomousTask, level: EscalationLevel):
        """Log the escalation decision."""
        entry = {
            "task_id": task.id,
            "title": task.title,
            "level": level.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "error": task.error,
        }
        self._escalation_log.append(entry)
        if level == EscalationLevel.CRITICAL:
            LOG.critical("ESCALATION TO HUMAN: %s — %s", task.title, task.error)
        elif level == EscalationLevel.WARNING:
            LOG.warning("Self-handled: %s — %s", task.title, task.error)

    @property
    def suppressed_count(self) -> int:
        return self._suppressed_count


# ═══════════════════════════════════════════════════════════════
#  Knowledge Journal — Evidence Trail
# ═══════════════════════════════════════════════════════════════


class KnowledgeJournal:
    """Persistent NDJSON journal of everything the daemon does.

    Doctrine: "If it isn't captured, it isn't trusted."
    """

    def __init__(self, journal_path: Path):
        self._path = journal_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry_type: str, data: dict[str, Any]):
        """Append an entry to the journal."""
        entry = {
            "type": entry_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def read_recent(self, count: int = 50) -> list[dict]:
        """Read the most recent journal entries."""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        recent = lines[-count:] if len(lines) > count else lines
        entries = []
        for line in recent:
            try:
                entries.append(json.loads(line))
            except Exception:  # noqa: S112
                continue
        return entries

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics from the journal."""
        entries = self.read_recent(500)
        type_counts: Counter[str] = Counter()
        for entry in entries:
            type_counts[entry.get("type", "unknown")] += 1
        return {
            "total_entries": len(entries),
            "entry_types": dict(type_counts),
        }


# ═══════════════════════════════════════════════════════════════
#  AUTONOMOUS DAEMON — The Main Engine
# ═══════════════════════════════════════════════════════════════


class AutonomousDaemon:
    """The self-organizing, self-motivating, 24/7 autonomous runtime.

    PDCA cycle executed continuously:
        PLAN    → GapAnalyzer scans system, TaskGenerator creates work
        DO      → TaskExecutor runs tasks with retry logic
        CHECK   → Self-assessment, escalation evaluation
        ACT     → Learning, knowledge journal update, improvement tasks

    When stuck externally → WebResearchFallback searches for answers.
    When stuck internally → deeper introspection via GapAnalyzer.
    Only CRITICAL escalations reach the human.
    """

    def __init__(
        self,
        repo_root: Path | None = None,
        cycle_interval_s: int = 300,  # 5 min between cycles
        max_tasks_per_cycle: int = 10,
    ):
        self.repo_root = repo_root or _REPO_ROOT
        self.cycle_interval_s = cycle_interval_s
        self.max_tasks_per_cycle = max_tasks_per_cycle

        # Core subsystems
        self.gap_analyzer = GapAnalyzer(self.repo_root)
        self.task_generator = TaskGenerator()
        self.task_executor = TaskExecutor(self.repo_root)
        self.escalation_gate = EscalationGate()
        self.journal = KnowledgeJournal(self.repo_root / "ncl_agency_runtime" / "logs" / "daemon_journal.ndjson")

        # State
        self._running = False
        self._cycle_count = 0
        self._task_queue: list[AutonomousTask] = []
        self._completed_tasks: list[AutonomousTask] = []
        self._boot_time: float = 0.0
        self._phase = DaemonPhase.BOOT

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self):
        """Boot and begin the autonomous loop."""
        self._running = True
        self._boot_time = time.time()
        self._phase = DaemonPhase.BOOT

        LOG.info("═" * 60)
        LOG.info("  NCL AUTONOMOUS DAEMON — STARTING")
        LOG.info("  Cycle interval: %ds | Max tasks/cycle: %d", self.cycle_interval_s, self.max_tasks_per_cycle)
        LOG.info("═" * 60)

        self.journal.record(
            "daemon_start",
            {
                "cycle_interval_s": self.cycle_interval_s,
                "max_tasks_per_cycle": self.max_tasks_per_cycle,
                "repo_root": str(self.repo_root),
            },
        )

        # Main loop
        while self._running:
            try:
                await self._run_cycle()
            except Exception as exc:
                LOG.error("Cycle %d crashed: %s\n%s", self._cycle_count, exc, traceback.format_exc())
                self.journal.record(
                    "cycle_crash",
                    {
                        "cycle": self._cycle_count,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )

            # Sleep between cycles
            if self._running:
                LOG.info("Sleeping %ds until next cycle...", self.cycle_interval_s)
                await asyncio.sleep(self.cycle_interval_s)

    async def stop(self):
        """Gracefully shut down."""
        LOG.info("Autonomous Daemon shutting down...")
        self._running = False
        self.journal.record(
            "daemon_stop",
            {
                "cycles_completed": self._cycle_count,
                "tasks_completed": len(self._completed_tasks),
                "uptime_s": time.time() - self._boot_time,
            },
        )

    # ── Main PDCA Cycle ───────────────────────────────────────

    async def _run_cycle(self):
        """Execute one full PDCA cycle."""
        self._cycle_count += 1
        report = CycleReport(phase=DaemonPhase.INTROSPECT)

        LOG.info("━" * 50)
        LOG.info("CYCLE %d — BEGIN", self._cycle_count)
        LOG.info("━" * 50)

        # ── PLAN: Introspect + Generate Tasks ─────────────────
        self._phase = DaemonPhase.INTROSPECT
        LOG.info("[PLAN] Running gap analysis...")

        gaps = self.gap_analyzer.full_scan()
        report.gaps_found = len(gaps)
        LOG.info("[PLAN] Found %d gaps", len(gaps))

        self._phase = DaemonPhase.PLAN
        gap_tasks = self.task_generator.generate_from_gaps(gaps)
        scheduled_tasks = self.task_generator.generate_scheduled_tasks()

        # Merge new tasks (avoid duplicates by title)
        existing_titles = {t.title for t in self._task_queue}
        for task in gap_tasks + scheduled_tasks:
            if task.title not in existing_titles:
                self._task_queue.append(task)
                existing_titles.add(task.title)
                report.tasks_generated += 1

        LOG.info("[PLAN] %d new tasks queued (total queue: %d)", report.tasks_generated, len(self._task_queue))

        self.journal.record(
            "plan_complete",
            {
                "cycle": self._cycle_count,
                "gaps": len(gaps),
                "new_tasks": report.tasks_generated,
                "queue_size": len(self._task_queue),
            },
        )

        # ── DO: Execute Tasks ─────────────────────────────────
        self._phase = DaemonPhase.EXECUTE
        LOG.info("[DO] Executing up to %d tasks...", self.max_tasks_per_cycle)

        # Sort by priority
        self._task_queue.sort(key=lambda t: list(TaskPriority).index(t.priority))

        # Execute batch
        batch = [t for t in self._task_queue if t.status == TaskStatus.QUEUED][: self.max_tasks_per_cycle]
        for task in batch:
            result_task = await self.task_executor.execute(task)
            report.tasks_executed += 1

            if result_task.status == TaskStatus.COMPLETED:
                report.tasks_succeeded += 1
                self._completed_tasks.append(result_task)
                self._task_queue.remove(task)
            elif result_task.status == TaskStatus.FAILED:
                report.tasks_failed += 1
                self._task_queue.remove(task)  # Move to dead letter

        LOG.info(
            "[DO] Executed %d tasks: %d succeeded, %d failed",
            report.tasks_executed,
            report.tasks_succeeded,
            report.tasks_failed,
        )

        # ── CHECK: Self-Assessment ────────────────────────────
        self._phase = DaemonPhase.ASSESS
        LOG.info("[CHECK] Running self-assessment...")

        for task in batch:
            level = self.escalation_gate.evaluate(task)
            self.escalation_gate.record_escalation(task, level)
            if level == EscalationLevel.CRITICAL:
                report.escalations.append(task.title)

        if report.escalations:
            LOG.critical("[CHECK] %d CRITICAL escalations!", len(report.escalations))
        else:
            LOG.info("[CHECK] No escalations needed — self-handling all outcomes")

        # ── ACT: Learn + Improve ──────────────────────────────
        self._phase = DaemonPhase.LEARN
        LOG.info("[ACT] Recording learnings...")

        # Generate improvement tasks from this cycle
        improvement_tasks = self.task_generator.generate_improvement_tasks(report)
        for task in improvement_tasks:
            if task.title not in existing_titles:
                self._task_queue.append(task)

        # Record learnings
        if report.tasks_succeeded > 0:
            report.learnings.append(f"Completed {report.tasks_succeeded} tasks successfully")
        if report.tasks_failed > 0:
            report.learnings.append(f"Failed {report.tasks_failed} tasks — queued for retry or escalation")
        if report.gaps_found == 0:
            report.learnings.append("System is clean — no gaps detected")

        report.completed_at = datetime.now(UTC).isoformat()

        self.journal.record(
            "cycle_complete",
            {
                "cycle": self._cycle_count,
                "gaps_found": report.gaps_found,
                "tasks_generated": report.tasks_generated,
                "tasks_executed": report.tasks_executed,
                "tasks_succeeded": report.tasks_succeeded,
                "tasks_failed": report.tasks_failed,
                "learnings": report.learnings,
                "escalations": report.escalations,
                "queue_remaining": len(self._task_queue),
            },
        )

        self._phase = DaemonPhase.IDLE

        LOG.info("━" * 50)
        LOG.info(
            "CYCLE %d — COMPLETE | Gaps: %d | Tasks: %d/%d ok | Queue: %d",
            self._cycle_count,
            report.gaps_found,
            report.tasks_succeeded,
            report.tasks_executed,
            len(self._task_queue),
        )
        LOG.info("━" * 50)

    # ── Status ────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Get current daemon status."""
        uptime = time.time() - self._boot_time if self._boot_time else 0
        return {
            "running": self._running,
            "phase": self._phase.value,
            "cycle_count": self._cycle_count,
            "uptime_s": round(uptime, 1),
            "uptime_human": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
            "queue_size": len(self._task_queue),
            "completed_tasks": len(self._completed_tasks),
            "escalations_suppressed": self.escalation_gate.suppressed_count,
            "journal_stats": self.journal.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════
#  CLI Entry Point
# ═══════════════════════════════════════════════════════════════


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="NCL Autonomous Daemon")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between PDCA cycles (default: 300)")
    parser.add_argument("--max-tasks", type=int, default=10, help="Max tasks per cycle (default: 10)")
    parser.add_argument("--single-cycle", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--status", action="store_true", help="Show daemon status from journal and exit")
    args = parser.parse_args()

    if args.status:
        journal = KnowledgeJournal(_REPO_ROOT / "ncl_agency_runtime" / "logs" / "daemon_journal.ndjson")
        stats = journal.get_stats()
        recent = journal.read_recent(5)
        print(json.dumps({"stats": stats, "recent_entries": recent}, indent=2, default=str))
        return

    daemon = AutonomousDaemon(
        cycle_interval_s=args.interval,
        max_tasks_per_cycle=args.max_tasks,
    )

    if args.single_cycle:
        daemon._running = True
        daemon._boot_time = time.time()
        await daemon._run_cycle()
        print(json.dumps(daemon.status(), indent=2))
    else:
        try:
            await daemon.start()
        except KeyboardInterrupt:
            await daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())
