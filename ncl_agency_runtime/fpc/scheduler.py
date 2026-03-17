"""Background scheduler — automated prediction and scraping runs.

Uses config/schedule.json to define recurring tasks:
  - ``fpc think <topic>``  at cron-like intervals
  - ``fpc scrape --due``   for data freshness
  - ``fpc evolve``         for periodic self-assessment

Runs as a foreground daemon via ``fpc schedule`` or as a background
process via ``fpc schedule --daemon``.

No external dependencies — uses stdlib ``threading.Timer`` with a
simple interval-based schedule (not full cron syntax).
"""

import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEDULE_CONFIG = Path("config/schedule.json")
PYTHON = sys.executable

# Default schedule if config file doesn't exist
_DEFAULT_SCHEDULE: dict[str, Any] = {
    "enabled": False,
    "tasks": [
        {
            "name": "daily_scrape",
            "command": ["scrape", "--due"],
            "interval_minutes": 1440,
            "enabled": True,
        },
        {
            "name": "daily_prediction",
            "command": ["think", "Global market outlook", "--horizon", "short"],
            "interval_minutes": 1440,
            "enabled": False,
        },
        {
            "name": "weekly_evolution",
            "command": ["evolve"],
            "interval_minutes": 10080,
            "enabled": True,
        },
    ],
}


class ScheduledTask:
    """A single recurring task."""

    def __init__(self, name: str, command: list[str], interval_minutes: int, enabled: bool = True):
        self.name = name
        self.command = command
        self.interval_seconds = interval_minutes * 60
        self.enabled = enabled
        self.last_run: str | None = None
        self.last_status: str | None = None
        self.run_count = 0


class Scheduler:
    """Simple interval-based task scheduler."""

    def __init__(self, config_path: Path | None = None):
        self._config_path = config_path or SCHEDULE_CONFIG
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._timers: list[threading.Timer] = []
        self._load_config()

    def _load_config(self):
        """Load schedule from config/schedule.json or create defaults."""
        if self._config_path.exists():
            try:
                cfg = json.loads(self._config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cfg = _DEFAULT_SCHEDULE
        else:
            cfg = _DEFAULT_SCHEDULE
            self._save_config(cfg)

        self._tasks = []
        for t in cfg.get("tasks", []):
            self._tasks.append(ScheduledTask(
                name=t["name"],
                command=t["command"],
                interval_minutes=t.get("interval_minutes", 1440),
                enabled=t.get("enabled", True),
            ))

    def _save_config(self, cfg: dict):
        """Persist config to disk."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(cfg, indent=2), encoding="utf-8"
        )

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return all scheduled tasks with status."""
        return [
            {
                "name": t.name,
                "command": " ".join(t.command),
                "interval_minutes": t.interval_seconds // 60,
                "enabled": t.enabled,
                "last_run": t.last_run,
                "last_status": t.last_status,
                "run_count": t.run_count,
            }
            for t in self._tasks
        ]

    def _run_task(self, task: ScheduledTask):
        """Execute a single task as a subprocess."""
        if not self._running:
            return

        cmd = [PYTHON, "-m", "src.main", *task.command]
        logger.info("Scheduler: running %s → %s", task.name, " ".join(cmd))
        task.last_run = datetime.now().isoformat()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max per task
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            task.last_status = "ok" if result.returncode == 0 else f"exit_{result.returncode}"
            task.run_count += 1
            if result.returncode != 0:
                logger.warning("Task %s failed (exit %d): %s",
                               task.name, result.returncode, result.stderr[:500])
            else:
                logger.info("Task %s completed successfully", task.name)
        except subprocess.TimeoutExpired:
            task.last_status = "timeout"
            logger.warning("Task %s timed out after 600s", task.name)
        except Exception as exc:
            task.last_status = f"error: {exc}"
            logger.error("Task %s error: %s", task.name, exc)

        # Schedule next run
        if self._running and task.enabled:
            timer = threading.Timer(task.interval_seconds, self._run_task, args=[task])
            timer.daemon = True
            timer.start()
            self._timers.append(timer)

    def start(self):
        """Start the scheduler — runs enabled tasks at their configured intervals."""
        self._running = True
        enabled = [t for t in self._tasks if t.enabled]

        if not enabled:
            logger.warning("No enabled tasks in schedule config")
            return

        logger.info("Scheduler starting with %d enabled tasks", len(enabled))

        for i, task in enumerate(enabled):
            # Stagger initial runs by 30 seconds each to avoid thundering herd
            delay = i * 30
            timer = threading.Timer(delay, self._run_task, args=[task])
            timer.daemon = True
            timer.start()
            self._timers.append(timer)

        # Block main thread until interrupted
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Stop the scheduler gracefully."""
        self._running = False
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
        logger.info("Scheduler stopped")

    def run_once(self):
        """Run all enabled tasks once immediately (for testing)."""
        enabled = [t for t in self._tasks if t.enabled]
        self._running = True
        for task in enabled:
            self._run_task(task)
        self._running = False
