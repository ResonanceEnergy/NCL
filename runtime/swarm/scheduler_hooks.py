"""
SwarmSchedulerHooks — Integration between the Agent Swarm and the AutonomousScheduler.

Provides:
- A maintenance loop that runs inside the scheduler's task set
- Cron-like recurring task scheduling for the swarm
- Council-to-swarm bridging (council output becomes a swarm task)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("ncl.swarm.scheduler_hooks")


class SwarmSchedulerHooks:
    """
    Hooks that wire the SwarmOrchestrator into the AutonomousScheduler lifecycle.

    Usage:
        hooks = SwarmSchedulerHooks(swarm=brain.swarm, scheduler=autonomous_scheduler)
        await hooks.attach()  # adds maintenance loop to scheduler._tasks
    """

    # Default recurring task definitions (cron-like)
    DEFAULT_RECURRING = [
        {
            "title": "Daily Intelligence Brief",
            "objective": (
                "Compile a concise intelligence briefing covering: "
                "key market moves, relevant news signals, project status updates, "
                "and recommended actions for NATRIX review."
            ),
            "interval_seconds": 86400,  # 24 hours
            "priority": 6,
            "budget_cents": 3000,
            "tags": ["recurring", "intelligence", "daily-brief"],
        },
        {
            "title": "Weekly Strategy Review",
            "objective": (
                "Perform a comprehensive strategy review: evaluate mandate completion rates, "
                "assess pillar health (NCC/BRS/AAC), identify stalled initiatives, "
                "and propose priority adjustments for the coming week."
            ),
            "interval_seconds": 604800,  # 7 days
            "priority": 7,
            "budget_cents": 5000,
            "tags": ["recurring", "strategy", "weekly-review"],
        },
    ]

    def __init__(
        self,
        swarm,
        scheduler=None,
        recurring_tasks: list[dict] | None = None,
    ) -> None:
        """
        Args:
            swarm: SwarmOrchestrator instance.
            scheduler: AutonomousScheduler instance (optional, can attach later).
            recurring_tasks: Override the default recurring task list.
        """
        self.swarm = swarm
        self.scheduler = scheduler
        self._recurring_tasks = recurring_tasks or self.DEFAULT_RECURRING
        self._maintenance_handle: asyncio.Task | None = None
        self._recurring_handles: list[asyncio.Task] = []
        self._running = False

    async def attach(self) -> None:
        """
        Attach the swarm maintenance loop to the scheduler's task set.

        Call this after the scheduler has started.
        """
        if self._running:
            log.warning("SwarmSchedulerHooks already attached")
            return

        self._running = True

        # Start the swarm maintenance loop
        self._maintenance_handle = asyncio.create_task(
            self._swarm_maintenance_loop(),
            name="ncl-swarm-maintenance",
        )

        # If scheduler is available, inject the task handle
        if self.scheduler and hasattr(self.scheduler, "_tasks"):
            self.scheduler._tasks.append(self._maintenance_handle)

        log.info("SwarmSchedulerHooks attached — maintenance loop started")

    async def detach(self) -> None:
        """Stop the maintenance loop and all recurring task loops."""
        self._running = False

        if self._maintenance_handle and not self._maintenance_handle.done():
            self._maintenance_handle.cancel()
            try:
                await self._maintenance_handle
            except asyncio.CancelledError:
                pass

        for handle in self._recurring_handles:
            if not handle.done():
                handle.cancel()
                try:
                    await handle
                except asyncio.CancelledError:
                    pass

        self._recurring_handles.clear()
        log.info("SwarmSchedulerHooks detached")

    # ------------------------------------------------------------------
    # Maintenance Loop
    # ------------------------------------------------------------------

    async def _swarm_maintenance_loop(self) -> None:
        """
        Periodic maintenance for the swarm: detect stalled tasks,
        reap completed workers, and log stats.

        Runs every 60 seconds while attached. Every individual hook is
        wrapped so a failure in one step does not crash the whole loop.
        """
        while self._running:
            await asyncio.sleep(60)

            await self._run_hook("get_stats", self._hook_log_stats)
            await self._run_hook("cleanup_completed_tasks", self._hook_cleanup_tasks)

    async def _run_hook(self, hook_name: str, coro_fn) -> None:
        """
        Execute a maintenance hook, catching and logging any exception so
        the scheduler loop cannot be brought down by a single failing hook.

        Args:
            hook_name: Short name used in log messages.
            coro_fn: Zero-argument async callable to invoke.
        """
        log.debug("[swarm-hook] Running hook: %s", hook_name)
        try:
            await coro_fn()
            log.debug("[swarm-hook] Hook completed: %s", hook_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(
                "[swarm-hook] Hook '%s' raised an unhandled exception: %s",
                hook_name,
                exc,
                exc_info=True,
            )

    async def _hook_log_stats(self) -> None:
        """Log current swarm statistics."""
        stats = self.swarm.get_stats()
        active = stats.get("active_tasks", 0)
        log.debug(
            "[swarm-maintenance] active_tasks=%d completed=%d failed=%d "
            "cost=%.2f¢ agents=%d",
            active,
            stats.get("completed_tasks", 0),
            stats.get("failed_tasks", 0),
            stats.get("total_cost_cents", 0.0),
            stats.get("active_agents", 0),
        )

    async def _hook_cleanup_tasks(self) -> None:
        """Evict completed tasks older than 24 h from the orchestrator dict."""
        if hasattr(self.swarm, "cleanup_completed_tasks"):
            removed = self.swarm.cleanup_completed_tasks()
            if removed:
                log.info(
                    "[swarm-maintenance] cleanup_completed_tasks evicted %d task(s)",
                    removed,
                )

    # ------------------------------------------------------------------
    # Recurring Task Scheduling
    # ------------------------------------------------------------------

    async def schedule_recurring_tasks(self) -> None:
        """
        Start recurring swarm tasks based on the configured schedule.

        Each recurring task spawns on its interval (like cron). Tasks are
        submitted to the swarm as new tasks each cycle — the swarm handles
        deduplication via tags if needed.
        """
        for task_def in self._recurring_tasks:
            handle = asyncio.create_task(
                self._recurring_task_loop(task_def),
                name=f"ncl-swarm-recurring-{task_def['title'][:30]}",
            )
            self._recurring_handles.append(handle)

            # Also inject into scheduler's task list if available
            if self.scheduler and hasattr(self.scheduler, "_tasks"):
                self.scheduler._tasks.append(handle)

        log.info(
            "Scheduled %d recurring swarm tasks",
            len(self._recurring_tasks),
        )

    async def _recurring_task_loop(self, task_def: dict) -> None:
        """Run a single recurring task at its defined interval."""
        interval = task_def.get("interval_seconds", 86400)
        title = task_def["title"]

        # Initial delay — stagger starts to avoid thundering herd
        import random
        initial_delay = random.uniform(10, min(60, interval / 10))
        await asyncio.sleep(initial_delay)

        while self._running:
            try:
                log.info(f"[swarm-recurring] Submitting: {title}")
                await self.swarm.submit_task(
                    title=title,
                    objective=task_def["objective"],
                    priority=task_def.get("priority", 5),
                    budget_cents=task_def.get("budget_cents", 3000),
                    tags=task_def.get("tags", ["recurring"]),
                    metadata={"recurring": True, "scheduled_at": datetime.now(timezone.utc).isoformat()},
                )
            except Exception as e:
                log.error(f"[swarm-recurring] Failed to submit '{title}': {e}")

            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Council → Swarm Bridge
    # ------------------------------------------------------------------

    async def spawn_from_council(self, session) -> dict:
        """
        Create a swarm task from a completed CouncilSession.

        Takes the council's consensus and recommendations and packages them
        into a swarm task for autonomous execution.

        Args:
            session: A CouncilSession instance (from ncl_brain.models).

        Returns:
            Dict with task_id and status of the spawned swarm task.
        """
        if not session.consensus:
            return {"error": "Council session has no consensus — cannot spawn task"}

        # Build objective from council output
        recommendations_text = "\n".join(
            f"- {r}" for r in (session.recommendations or [])
        )
        objective = (
            f"Execute council directive.\n\n"
            f"Council Consensus:\n{session.consensus}\n\n"
            f"Recommendations:\n{recommendations_text or '(none)'}\n\n"
            f"Topic: {session.topic}\n"
            f"Session ID: {session.session_id}"
        )

        # Determine priority from consensus score if available
        priority = 6  # default
        if hasattr(session, "consensus_score") and session.consensus_score:
            if session.consensus_score.agreement_pct > 90:
                priority = 8  # high agreement = high priority
            elif session.consensus_score.agreement_pct > 70:
                priority = 7

        try:
            task = await self.swarm.submit_task(
                title=f"Council Directive: {session.topic[:60]}",
                objective=objective,
                priority=priority,
                budget_cents=5000,
                tags=["council-spawned", f"session:{session.session_id}"],
                metadata={
                    "source": "council",
                    "session_id": session.session_id,
                    "consensus_score": (
                        session.consensus_score.agreement_pct
                        if hasattr(session, "consensus_score") and session.consensus_score
                        else None
                    ),
                },
            )
            log.info(
                "[council→swarm] Spawned task %s from council session %s",
                task.task_id,
                session.session_id,
            )
            return {
                "task_id": task.task_id,
                "title": task.title,
                "priority": task.priority,
                "status": task.status.value,
            }
        except Exception as e:
            log.error(f"[council→swarm] Failed to spawn from session {session.session_id}: {e}")
            return {"error": str(e), "session_id": session.session_id}
