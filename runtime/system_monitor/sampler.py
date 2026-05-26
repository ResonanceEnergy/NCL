"""Sampler — 5s tick autonomous loop + ring buffer + brain-correlation tags."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Optional
from uuid import uuid4

from .collectors import (
    collect_brain,
    collect_host,
    collect_llm_summary,
    collect_tailscale,
)
from .models import (
    OpsSnapshot,
    SchedulerTaskActivity,
)

log = logging.getLogger("ncl.system_monitor.sampler")

_TICK_S = float(os.getenv("NCL_OPS_TICK_S", "5"))
_RING_MINUTES = int(os.getenv("NCL_OPS_RING_MINUTES", "60"))
_RING_SIZE = int((_RING_MINUTES * 60) / _TICK_S)  # ~720 at default 5s/60min


class OpsSampler:
    """Singleton sampler — owns the ring buffer + the autonomous loop."""

    def __init__(self):
        self._ring: deque[OpsSnapshot] = deque(maxlen=_RING_SIZE)
        self._latest: Optional[OpsSnapshot] = None
        self._subscribers: list[asyncio.Queue[OpsSnapshot]] = []
        self._scheduler_ref = None  # set by run()
        self._tailscale_cache: Optional[tuple[float, object]] = None  # (ts, mesh)
        self._tailscale_cache_ttl_s = 20.0  # tailscale CLI is slow; cache 20s

    # ── Public API for endpoints ───────────────────────────────────────

    def latest(self) -> Optional[OpsSnapshot]:
        return self._latest

    def history(self, minutes: int = 10) -> list[OpsSnapshot]:
        if minutes >= _RING_MINUTES:
            return list(self._ring)
        cutoff_ticks = int((minutes * 60) / _TICK_S)
        return list(self._ring)[-cutoff_ticks:]

    def subscribe(self) -> asyncio.Queue[OpsSnapshot]:
        q: asyncio.Queue[OpsSnapshot] = asyncio.Queue(maxsize=4)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[OpsSnapshot]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ── Scheduler-activity probe ────────────────────────────────────────

    def _scheduler_activity(self) -> tuple[list[SchedulerTaskActivity], Optional[str]]:
        """Best-effort introspection of the autonomous scheduler.

        Reads task names + states from the asyncio event loop. Returns the
        activity list + the name of whatever's currently running (for the
        active_scheduler_task tag).
        """
        activity: list[SchedulerTaskActivity] = []
        active_name: Optional[str] = None
        try:
            loop = asyncio.get_running_loop()
            tasks = [t for t in asyncio.all_tasks(loop) if (t.get_name() or "").startswith("ncl-")]
            for t in tasks:
                name = t.get_name()
                state = "dead" if t.done() else ("running" if not t.cancelled() else "idle")
                activity.append(SchedulerTaskActivity(
                    name=name,
                    elapsed_ms=0.0,
                    last_run_iso=None,
                    state=state,
                ))
            # Sort by name for stable display
            activity.sort(key=lambda a: a.name)
        except Exception as e:
            log.debug("[sampler] scheduler activity probe failed: %s", e)
        return activity, active_name

    # ── Main loop ──────────────────────────────────────────────────────

    async def _sample_once(self) -> OpsSnapshot:
        """One sampling tick — collects everything, returns a snapshot."""
        t0 = time.perf_counter()

        # Tailscale cached
        ts_cache_ok = False
        if self._tailscale_cache is not None:
            ts_ts, ts_mesh = self._tailscale_cache
            if (time.time() - ts_ts) < self._tailscale_cache_ttl_s:
                tailscale = ts_mesh
                ts_cache_ok = True

        # Run independent collectors in parallel
        if ts_cache_ok:
            host_task = asyncio.create_task(collect_host())
            brain_task = asyncio.create_task(collect_brain())
            host = await host_task
            brain = await brain_task
        else:
            host_task = asyncio.create_task(collect_host())
            brain_task = asyncio.create_task(collect_brain())
            tailscale_task = asyncio.create_task(collect_tailscale())
            host, brain, tailscale = await asyncio.gather(host_task, brain_task, tailscale_task)
            self._tailscale_cache = (time.time(), tailscale)

        # LLM summary is pure file read, cheap, do it inline
        llm_summary = collect_llm_summary(window_minutes=60)

        # Scheduler activity (sync introspection)
        activity, active_name = self._scheduler_activity()

        # Layer cost_tracker + health-rollup data into brain stats best-effort
        try:
            from .. import cost_tracker as _ct

            today = await _ct.get_today_summary()
            if isinstance(today, dict):
                brain.today_cost_usd = round(float(today.get("total_usd", 0)), 4)
                brain.blocked_sources = list(today.get("blocked_sources", []))
                cap = float(today.get("platform_cap_usd", 0) or 20.0)
                if cap > 0:
                    brain.today_budget_pct = round(brain.today_cost_usd / cap * 100, 1)
        except Exception:
            pass

        brain.active_tasks = len(activity)
        brain.healthy_tasks = sum(1 for a in activity if a.state == "running")
        brain.dead_tasks = [a.name for a in activity if a.state == "dead"]

        sample_ms = round((time.perf_counter() - t0) * 1000, 1)

        return OpsSnapshot(
            sample_id=f"ops-{uuid4().hex[:8]}",
            sample_duration_ms=sample_ms,
            host=host,
            brain=brain,
            tailscale=tailscale,
            scheduler_activity=activity,
            llm_calls=llm_summary,
            active_scheduler_task=active_name,
        )

    async def run(self, scheduler) -> None:
        """Long-running autonomous loop — registered as ncl-ops-monitor."""
        self._scheduler_ref = scheduler
        log.info("[OPS-MONITOR] sampler started (tick=%ss ring=%smin)", _TICK_S, _RING_MINUTES)
        # Prime the pump
        await asyncio.sleep(2)
        while getattr(scheduler, "_running", True):
            try:
                snap = await self._sample_once()
                self._ring.append(snap)
                self._latest = snap
                # Fanout to subscribers
                dead: list[asyncio.Queue] = []
                for q in list(self._subscribers):
                    try:
                        q.put_nowait(snap)
                    except asyncio.QueueFull:
                        # subscriber is slow; drop the snapshot rather than block
                        pass
                    except Exception:
                        dead.append(q)
                for q in dead:
                    self.unsubscribe(q)
            except Exception as e:
                log.exception("[OPS-MONITOR] sample failed: %s", e)
            await asyncio.sleep(_TICK_S)
        log.info("[OPS-MONITOR] sampler stopped")


# ── Module-level singleton ───────────────────────────────────────────────


_SAMPLER: Optional[OpsSampler] = None


def get_sampler() -> OpsSampler:
    global _SAMPLER
    if _SAMPLER is None:
        _SAMPLER = OpsSampler()
    return _SAMPLER


async def run(scheduler) -> None:
    """Entry point for the autonomous scheduler."""
    sampler = get_sampler()
    await sampler.run(scheduler)
