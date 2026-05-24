"""
ncl-memory-budget loop (carved from scheduler.py, W8-A13 proof-of-concept).

Periodic (15min) per-tier token-spend rollup. Calls
`runtime.memory.budget_tracker.run_budget_cycle`, surfacing 80%/100% cap
breaches via ntfy as a side effect of that helper.

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler._running` (bool gate to stop the loop)
- `scheduler._stats` (dict the budget tracker mutates with telemetry)

Other dependencies: the module-level EMERGENCY_STOP_EVENT from
`runtime.governance.emergency_stop`, which all autonomous loops respect.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging

from ...governance.emergency_stop import EMERGENCY_STOP_EVENT
from ...memory.budget_tracker import run_budget_cycle

log = logging.getLogger(__name__)

_INTERVAL_S = 900  # 15 minutes


async def run(scheduler) -> None:
    """Run the memory-budget telemetry loop for the given scheduler.

    The scheduler instance owns the lifecycle flag (`_running`) and the
    stats dict (`_stats`) the cycle annotates. This function is the
    extracted body of what used to be `_memory_budget_loop` defined
    inline inside `Scheduler.start()`.
    """
    while scheduler._running and not EMERGENCY_STOP_EVENT.is_set():
        try:
            await run_budget_cycle(stats=scheduler._stats)
        except Exception as ex:
            log.warning(f"[ncl-memory-budget] {ex}")
        await asyncio.sleep(_INTERVAL_S)
