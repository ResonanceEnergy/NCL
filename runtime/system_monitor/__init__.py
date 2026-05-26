"""NCL system_monitor — Wave 14G (2026-05-25).

Brain-correlated host + network monitoring. Sampler runs as the
ncl-ops-monitor autonomous loop every 5 seconds, writes structured
snapshots into a 60-minute in-memory ring buffer, and serves them via
/system/ops/* endpoints.

See docs/DESKTOP_OPTIONS_2026-05-25.md.
"""

from .models import (
    HostStats,
    BrainStats,
    TailscalePeer,
    TailscaleMesh,
    SchedulerTaskActivity,
    LLMCallSummary,
    OpsSnapshot,
)
from .sampler import OpsSampler, get_sampler

__all__ = [
    "HostStats",
    "BrainStats",
    "TailscalePeer",
    "TailscaleMesh",
    "SchedulerTaskActivity",
    "LLMCallSummary",
    "OpsSnapshot",
    "OpsSampler",
    "get_sampler",
]
