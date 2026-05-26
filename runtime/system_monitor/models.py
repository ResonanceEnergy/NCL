"""Pydantic models for the ops-monitoring snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class HostStats(BaseModel):
    """Whole-host metrics (the Mac Studio itself)."""

    cpu_pct: float = 0.0                 # 0-100, all cores aggregated
    cpu_count: int = 0
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0
    load_avg_15m: float = 0.0

    mem_total_gb: float = 0.0
    mem_used_gb: float = 0.0
    mem_free_gb: float = 0.0
    mem_active_gb: float = 0.0
    mem_wired_gb: float = 0.0

    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0

    # Per-interface bytes/sec, totalled across all up interfaces
    net_rx_mbps: float = 0.0
    net_tx_mbps: float = 0.0

    uptime_seconds: int = 0
    hostname: str = ""


class BrainStats(BaseModel):
    """Brain process-level metrics."""

    pid: Optional[int] = None
    cpu_pct: float = 0.0                 # 0-100
    rss_mb: float = 0.0
    threads: int = 0
    file_descriptors: int = 0
    uptime_seconds: int = 0

    active_tasks: int = 0                # asyncio tasks currently scheduled
    healthy_tasks: int = 0               # = scheduler.healthy_count from /system/health/rollup
    dead_tasks: list[str] = Field(default_factory=list)

    # Live counters from cost_tracker for the day
    today_cost_usd: float = 0.0
    today_budget_pct: float = 0.0
    blocked_sources: list[str] = Field(default_factory=list)


class TailscalePeer(BaseModel):
    name: str
    addr: str = ""                       # 100.x.y.z
    latency_ms: float = 0.0              # latest probe
    last_handshake_secs: int = 0         # age in seconds (0 = now)
    relayed_via_derp: bool = False
    online: bool = True


class TailscaleMesh(BaseModel):
    self_name: str = ""
    self_addr: str = ""
    peer_count: int = 0
    online_count: int = 0
    peers: list[TailscalePeer] = Field(default_factory=list)


class SchedulerTaskActivity(BaseModel):
    """Per-named-loop wall-time accumulation in the last sampling window."""

    name: str
    elapsed_ms: float = 0.0              # cumulative ms over the sample window
    last_run_iso: Optional[str] = None
    state: str = "idle"                  # "running" | "idle" | "dead"


class LLMCallSummary(BaseModel):
    """Rolling-window summary of LLM calls from cost_tracker."""

    window_minutes: int = 60
    call_count: int = 0
    total_cost_usd: float = 0.0
    avg_latency_s: float = 0.0
    p99_latency_s: float = 0.0
    by_model: dict[str, dict] = Field(default_factory=dict)  # model -> {count, cost_usd}


class OpsSnapshot(BaseModel):
    """One sampling tick — what the ring buffer stores."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sample_id: str = ""
    sample_duration_ms: float = 0.0      # how long this sample took to collect

    host: HostStats = Field(default_factory=HostStats)
    brain: BrainStats = Field(default_factory=BrainStats)
    tailscale: TailscaleMesh = Field(default_factory=TailscaleMesh)
    scheduler_activity: list[SchedulerTaskActivity] = Field(default_factory=list)
    llm_calls: LLMCallSummary = Field(default_factory=LLMCallSummary)

    # Brain-correlation tags (cheap to compute, used by desktop for overlays)
    active_scheduler_task: Optional[str] = None
    inflight_llm_call_id: Optional[str] = None
