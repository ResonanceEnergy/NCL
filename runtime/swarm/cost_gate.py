"""
Budget enforcement gate for the NCL Agent Swarm.

Wraps cost tracking with per-task budget allocation, spending,
and overage detection. Falls back to in-memory tracking if the
external Paperclip cost service is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _SpendRecord:
    """Single spend event within a task's budget."""

    amount_cents: float
    description: str
    timestamp: float = field(default_factory=time.time)


_MAX_SPEND_RECORDS = 500  # Per-task spend record cap


@dataclass
class _TaskBudget:
    """In-memory budget ledger for a single task."""

    task_id: str
    budget_cents: int
    spent_cents: float = 0.0
    # Bounded deque — oldest spend records dropped automatically when full
    records: deque = field(default_factory=lambda: deque(maxlen=_MAX_SPEND_RECORDS))
    created_at: float = field(default_factory=time.time)


class CostGate:
    """
    Per-task budget enforcement for the swarm.

    Maintains budget allocations and spend ledgers. Attempts to sync
    with the Paperclip cost-tracking service when available; falls back
    to purely in-memory tracking if Paperclip is unreachable.

    Thread-safe via asyncio.Lock.
    """

    def __init__(self, paperclip_client: Any | None = None) -> None:
        """
        Args:
            paperclip_client: Optional async client for the Paperclip cost service.
                              Must expose ``async record_spend(task_id, amount, desc)``
                              and ``async get_balance(task_id) -> float``.
                              If None or calls fail, in-memory tracking is used.
        """
        self._paperclip = paperclip_client
        self._budgets: dict[str, _TaskBudget] = {}
        self._lock = asyncio.Lock()

        logger.info(
            "CostGate initialized (paperclip=%s)",
            "connected" if paperclip_client else "in-memory only",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def allocate(self, task_id: str, budget_cents: int) -> None:
        """
        Reserve a budget for the given task.

        If an allocation already exists it is replaced (budget is reset,
        but previously recorded spends are preserved).

        Args:
            task_id: Unique task identifier.
            budget_cents: Maximum spend allowed, in cents.
        """
        async with self._lock:
            existing = self._budgets.get(task_id)
            if existing is not None:
                # Preserve spend history on re-allocation
                existing.budget_cents = budget_cents
                logger.info(
                    "CostGate re-allocated task=%s budget=%d¢ (spent=%.2f¢)",
                    task_id,
                    budget_cents,
                    existing.spent_cents,
                )
            else:
                self._budgets[task_id] = _TaskBudget(
                    task_id=task_id,
                    budget_cents=budget_cents,
                )
                logger.info(
                    "CostGate allocated task=%s budget=%d¢",
                    task_id,
                    budget_cents,
                )

    async def spend(self, task_id: str, amount_cents: float, description: str) -> None:
        """
        Deduct from a task's budget and record the spend.

        Args:
            task_id: Task to charge against.
            amount_cents: Amount spent in cents.
            description: Human-readable description of what was purchased.

        Raises:
            KeyError: If no budget has been allocated for the task.
        """
        async with self._lock:
            budget = self._get_budget(task_id)
            record = _SpendRecord(
                amount_cents=amount_cents,
                description=description,
            )
            budget.spent_cents += amount_cents
            budget.records.append(record)

        # Snapshot values for logging while still under lock (Gap 15)
        # (The lock was just released above; re-read is fine for spend()
        # because the values were captured inside the lock block.)
        async with self._lock:
            budget = self._get_budget(task_id)
            spent_snap = budget.spent_cents
            budget_snap = budget.budget_cents

        # Best-effort sync with Paperclip
        await self._paperclip_record(task_id, amount_cents, description)

        logger.debug(
            "CostGate spend: task=%s amount=%.2f¢ remaining=%.2f¢ desc=%s",
            task_id,
            amount_cents,
            budget_snap - spent_snap,
            description,
        )

    async def remaining(self, task_id: str) -> float:
        """
        Return the remaining budget in cents for the task.

        Args:
            task_id: Task to query.

        Returns:
            Remaining cents (may be negative if overspent).

        Raises:
            KeyError: If no budget has been allocated for the task.
        """
        async with self._lock:
            budget = self._get_budget(task_id)
            return budget.budget_cents - budget.spent_cents

    async def can_afford(self, task_id: str, estimated_cost: float) -> bool:
        """
        Check whether a task can afford an upcoming expense.

        Args:
            task_id: Task to check.
            estimated_cost: Projected cost in cents.

        Returns:
            True if spending estimated_cost would not exceed the budget.

        Raises:
            KeyError: If no budget has been allocated for the task.
        """
        rem = await self.remaining(task_id)
        return rem >= estimated_cost

    async def check_and_spend(
        self,
        task_id: str,
        estimated_cost: float,
        description: str,
    ) -> bool:
        """
        Atomically check affordability and record the spend (Gap 14).

        Merges can_afford + spend into a single lock acquisition so that
        two concurrent callers cannot both pass the affordability check
        and overshoot the budget (TOCTOU race).

        Args:
            task_id: Task to charge against.
            estimated_cost: Amount in cents.
            description: Human-readable spend description.

        Returns:
            True if the spend was recorded; False if budget would be exceeded.

        Raises:
            KeyError: If no budget has been allocated for the task.
        """
        async with self._lock:
            budget = self._get_budget(task_id)
            remaining = budget.budget_cents - budget.spent_cents
            if remaining < estimated_cost:
                return False
            record = _SpendRecord(
                amount_cents=estimated_cost,
                description=description,
            )
            budget.spent_cents += estimated_cost
            budget.records.append(record)
            # Snapshot values for logging while still under lock (Gap 15)
            spent_snap = budget.spent_cents
            budget_snap = budget.budget_cents

        # Best-effort sync with Paperclip (outside lock)
        await self._paperclip_record(task_id, estimated_cost, description)

        logger.debug(
            "CostGate check_and_spend: task=%s amount=%.2f¢ remaining=%.2f¢ desc=%s",
            task_id,
            estimated_cost,
            budget_snap - spent_snap,
            description,
        )
        return True

    async def exceeded(self, task_id: str) -> bool:
        """
        Check whether the task has exceeded its budget.

        Args:
            task_id: Task to check.

        Returns:
            True if total spend exceeds the allocated budget.

        Raises:
            KeyError: If no budget has been allocated for the task.
        """
        rem = await self.remaining(task_id)
        return rem < 0

    async def get_spend_log(self, task_id: str) -> list[dict[str, Any]]:
        """
        Return the full spend history for a task.

        Args:
            task_id: Task to query.

        Returns:
            List of spend records as dicts.

        Raises:
            KeyError: If no budget has been allocated for the task.
        """
        async with self._lock:
            budget = self._get_budget(task_id)
            return [
                {
                    "amount_cents": r.amount_cents,
                    "description": r.description,
                    "timestamp": r.timestamp,
                }
                for r in budget.records
            ]

    async def deallocate(self, task_id: str) -> None:
        """
        Remove budget tracking for a completed/cancelled task.

        Args:
            task_id: Task to remove.
        """
        async with self._lock:
            removed = self._budgets.pop(task_id, None)

        if removed:
            logger.info(
                "CostGate deallocated task=%s (spent=%.2f¢ of %d¢)",
                task_id,
                removed.spent_cents,
                removed.budget_cents,
            )

    async def cleanup_stale_budgets(self, max_age_seconds: float = 86400.0) -> int:
        """
        Remove budget entries for tasks that are older than max_age_seconds
        and have not been explicitly deallocated (e.g. process crashed mid-task).

        Args:
            max_age_seconds: Age threshold in seconds (default: 24 hours).

        Returns:
            Number of stale budget entries removed.
        """
        cutoff = time.time() - max_age_seconds
        async with self._lock:
            stale = [
                task_id
                for task_id, budget in self._budgets.items()
                if budget.created_at < cutoff
            ]
            for task_id in stale:
                removed = self._budgets.pop(task_id)
                logger.info(
                    "CostGate evicted stale budget: task=%s age=%.0fs spent=%.2f¢",
                    task_id,
                    time.time() - removed.created_at,
                    removed.spent_cents,
                )
        return len(stale)

    async def get_summary(self) -> dict[str, Any]:
        """
        Return aggregate cost information across all tracked tasks.

        Returns:
            Dict with total_allocated, total_spent, active_tasks count.
        """
        async with self._lock:
            total_allocated = sum(b.budget_cents for b in self._budgets.values())
            total_spent = sum(b.spent_cents for b in self._budgets.values())
            return {
                "active_tasks": len(self._budgets),
                "total_allocated_cents": total_allocated,
                "total_spent_cents": round(total_spent, 4),
                "total_remaining_cents": round(total_allocated - total_spent, 4),
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_budget(self, task_id: str) -> _TaskBudget:
        """Retrieve budget or raise KeyError. Must be called under lock."""
        budget = self._budgets.get(task_id)
        if budget is None:
            raise KeyError(f"No budget allocated for task '{task_id}'")
        return budget

    async def _paperclip_record(
        self,
        task_id: str,
        amount_cents: float,
        description: str,
    ) -> None:
        """Best-effort sync with Paperclip. Never raises."""
        if self._paperclip is None:
            return

        try:
            await self._paperclip.record_spend(task_id, amount_cents, description)
        except Exception as exc:
            logger.warning(
                "Paperclip sync failed for task=%s: %s (falling back to in-memory)",
                task_id,
                exc,
            )
