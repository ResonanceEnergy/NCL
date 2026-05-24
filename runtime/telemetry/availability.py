"""Assistant Availability Tracker — per-workflow availability metrics.

Tracks uptime, success rates, and latency per workflow. Fires alerts
when availability regresses below defined thresholds.
"""

import asyncio
import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field


log = logging.getLogger("ncl.availability")


class AvailabilityStatus(str, Enum):
    HEALTHY = "healthy"  # ≥99% success rate
    DEGRADED = "degraded"  # 95-99% success rate
    UNHEALTHY = "unhealthy"  # <95% success rate
    DOWN = "down"  # No successful requests in window


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    AVAILABILITY_REGRESSION = "availability_regression"
    LATENCY_SPIKE = "latency_spike"
    ERROR_RATE_SPIKE = "error_rate_spike"
    WORKFLOW_DOWN = "workflow_down"
    RECOVERY = "recovery"


class AvailabilityAlert(BaseModel):
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    workflow: str
    message: str
    current_value: float
    threshold: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False


class WorkflowHealth(BaseModel):
    """Current health snapshot for a single workflow."""

    workflow: str
    status: AvailabilityStatus
    availability_pct: float = 100.0  # Success rate %
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    window_minutes: int = 60
    alerts: list[AvailabilityAlert] = Field(default_factory=list)


class AvailabilityConfig(BaseModel):
    """Configurable thresholds for availability alerts."""

    healthy_threshold: float = 99.0  # ≥99% = healthy
    degraded_threshold: float = 95.0  # ≥95% = degraded
    latency_alert_ms: float = 5000.0  # Alert if avg latency exceeds 5s
    latency_p95_alert_ms: float = 10000.0
    error_spike_threshold: float = 10.0  # Alert if error rate jumps 10% in window
    window_minutes: int = 60  # Rolling window size
    down_after_minutes: int = 5  # Mark DOWN if no success in 5 min
    alert_cooldown_minutes: int = 15  # Don't re-fire same alert within 15 min


class AvailabilityTracker:
    """Tracks per-workflow availability with regression alerts."""

    def __init__(self, data_dir, config: AvailabilityConfig = None):
        # data_dir should be Path
        self.data_dir = Path(data_dir) if not isinstance(data_dir, Path) else data_dir
        self.config = config or AvailabilityConfig()
        self.avail_dir = self.data_dir / "telemetry" / "availability"

        # In-memory rolling windows per workflow
        self._requests: dict[str, list[dict]] = {}  # workflow → [{timestamp, success, duration_ms}]
        self._alerts: list[AvailabilityAlert] = []
        self._last_alert_time: dict[str, datetime] = {}  # (workflow, alert_type) → last fired
        self._alert_callbacks: list[Callable] = []

    async def init(self):
        """Initialize tracker: create directory and load today's data if exists."""
        self.avail_dir.mkdir(parents=True, exist_ok=True)
        # Load today's data if exists
        today_file = self.avail_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        if today_file.exists():
            import aiofiles

            async with aiofiles.open(today_file, "r") as f:
                async for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        wf = record.get("workflow", "unknown")
                        if wf not in self._requests:
                            self._requests[wf] = []
                        self._requests[wf].append(record)

    def on_alert(self, callback: Callable):
        """Register alert callback."""
        self._alert_callbacks.append(callback)

    async def record_request(
        self, workflow: str, success: bool, duration_ms: float, error_type: str = None
    ):
        """Record a single request outcome."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workflow": workflow,
            "success": success,
            "duration_ms": duration_ms,
            "error_type": error_type,
        }

        if workflow not in self._requests:
            self._requests[workflow] = []
        self._requests[workflow].append(record)

        # Persist
        today_file = self.avail_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        import aiofiles

        async with aiofiles.open(today_file, "a") as f:
            await f.write(json.dumps(record) + "\n")

        # Check for alerts
        await self._check_alerts(workflow)

    def get_workflow_health(self, workflow: str) -> WorkflowHealth:
        """Get current health snapshot for a workflow."""
        records = self._get_window_records(workflow)

        if not records:
            return WorkflowHealth(
                workflow=workflow,
                status=AvailabilityStatus.DOWN
                if workflow in self._requests
                else AvailabilityStatus.HEALTHY,
                window_minutes=self.config.window_minutes,
            )

        total = len(records)
        successful = sum(1 for r in records if r["success"])
        failed = total - successful
        availability = (successful / total * 100) if total > 0 else 0.0

        durations = [r["duration_ms"] for r in records if r.get("duration_ms") is not None]
        avg_latency = sum(durations) / len(durations) if durations else 0.0
        sorted_durations = sorted(durations)
        p95_latency = (
            sorted_durations[int(len(sorted_durations) * 0.95)]
            if len(sorted_durations) >= 20
            else (sorted_durations[-1] if sorted_durations else 0.0)
        )

        # Determine status
        if availability >= self.config.healthy_threshold:
            status = AvailabilityStatus.HEALTHY
        elif availability >= self.config.degraded_threshold:
            status = AvailabilityStatus.DEGRADED
        else:
            status = AvailabilityStatus.UNHEALTHY

        # Check if DOWN
        success_records = [r for r in records if r["success"]]
        if not success_records:
            recent_cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=self.config.down_after_minutes)
            ).isoformat()
            if all(r["timestamp"] > recent_cutoff for r in records):
                status = AvailabilityStatus.DOWN

        last_success = None
        last_failure = None
        for r in reversed(records):
            if r["success"] and last_success is None:
                last_success = datetime.fromisoformat(r["timestamp"])
            if not r["success"] and last_failure is None:
                last_failure = datetime.fromisoformat(r["timestamp"])
            if last_success and last_failure:
                break

        workflow_alerts = [a for a in self._alerts if a.workflow == workflow and not a.acknowledged]

        return WorkflowHealth(
            workflow=workflow,
            status=status,
            availability_pct=round(availability, 2),
            avg_latency_ms=round(avg_latency, 2),
            p95_latency_ms=round(p95_latency, 2),
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            last_success=last_success,
            last_failure=last_failure,
            window_minutes=self.config.window_minutes,
            alerts=workflow_alerts,
        )

    def get_all_health(self) -> list[WorkflowHealth]:
        """Get health for all tracked workflows."""
        return [self.get_workflow_health(wf) for wf in sorted(self._requests.keys())]

    def get_dashboard_summary(self) -> dict:
        """Dashboard-ready summary of all workflows."""
        healths = self.get_all_health()
        return {
            "total_workflows": len(healths),
            "healthy": sum(1 for h in healths if h.status == AvailabilityStatus.HEALTHY),
            "degraded": sum(1 for h in healths if h.status == AvailabilityStatus.DEGRADED),
            "unhealthy": sum(1 for h in healths if h.status == AvailabilityStatus.UNHEALTHY),
            "down": sum(1 for h in healths if h.status == AvailabilityStatus.DOWN),
            "active_alerts": len([a for a in self._alerts if not a.acknowledged]),
            "workflows": [h.model_dump() for h in healths],
        }

    def get_alerts(self, acknowledged: bool = None) -> list[AvailabilityAlert]:
        """Get alerts, optionally filtered by acknowledged status."""
        if acknowledged is None:
            return list(self._alerts)
        return [a for a in self._alerts if a.acknowledged == acknowledged]

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Mark an alert as acknowledged. Returns True if found and updated."""
        for a in self._alerts:
            if a.alert_id == alert_id:
                a.acknowledged = True
                return True
        return False

    def _get_window_records(self, workflow: str) -> list[dict]:
        """Get records for a workflow within the rolling time window."""
        records = self._requests.get(workflow, [])
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=self.config.window_minutes)
        ).isoformat()
        return [r for r in records if r["timestamp"] >= cutoff]

    async def _check_alerts(self, workflow: str):
        """Check workflow health and fire alerts if thresholds exceeded."""
        health = self.get_workflow_health(workflow)

        # Availability regression
        if health.status in (AvailabilityStatus.DEGRADED, AvailabilityStatus.UNHEALTHY):
            severity = (
                AlertSeverity.WARNING
                if health.status == AvailabilityStatus.DEGRADED
                else AlertSeverity.CRITICAL
            )
            await self._fire_alert(
                AvailabilityAlert(
                    alert_id=str(_uuid.uuid4()),
                    alert_type=AlertType.AVAILABILITY_REGRESSION,
                    severity=severity,
                    workflow=workflow,
                    message=f"Workflow '{workflow}' availability at {health.availability_pct}% ({health.status.value})",  # noqa: E501
                    current_value=health.availability_pct,
                    threshold=self.config.degraded_threshold,
                )
            )

        if health.status == AvailabilityStatus.DOWN:
            await self._fire_alert(
                AvailabilityAlert(
                    alert_id=str(_uuid.uuid4()),
                    alert_type=AlertType.WORKFLOW_DOWN,
                    severity=AlertSeverity.CRITICAL,
                    workflow=workflow,
                    message=f"Workflow '{workflow}' is DOWN — no successful requests in {self.config.down_after_minutes}min window",  # noqa: E501
                    current_value=0.0,
                    threshold=1.0,
                )
            )

        # Latency spike
        if health.avg_latency_ms > self.config.latency_alert_ms:
            await self._fire_alert(
                AvailabilityAlert(
                    alert_id=str(_uuid.uuid4()),
                    alert_type=AlertType.LATENCY_SPIKE,
                    severity=AlertSeverity.WARNING,
                    workflow=workflow,
                    message=f"Workflow '{workflow}' avg latency {health.avg_latency_ms:.0f}ms exceeds {self.config.latency_alert_ms:.0f}ms",  # noqa: E501
                    current_value=health.avg_latency_ms,
                    threshold=self.config.latency_alert_ms,
                )
            )

    async def _fire_alert(self, alert: AvailabilityAlert):
        """Fire an alert with cooldown to prevent alert fatigue."""
        # Cooldown check
        key = f"{alert.workflow}:{alert.alert_type.value}"
        last = self._last_alert_time.get(key)
        if last:
            cooldown = timedelta(minutes=self.config.alert_cooldown_minutes)
            if datetime.now(timezone.utc) - last < cooldown:
                return

        self._last_alert_time[key] = datetime.now(timezone.utc)
        self._alerts.append(alert)
        log.warning(f"AVAILABILITY ALERT: {alert.message}")

        for cb in self._alert_callbacks:
            try:
                cb(alert)
            except Exception as e:
                log.error(f"Alert callback error: {e}")


# ── ntfy push integration ────────────────────────────────────────────

_NTFY_TOPIC = os.getenv("NTFY_TOPIC", "ncl-natrix-intel-7x9k")
_NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

_SEVERITY_TO_PRIORITY = {
    AlertSeverity.CRITICAL: "5",
    AlertSeverity.WARNING: "4",
    AlertSeverity.INFO: "3",
}

_SEVERITY_TO_TAGS = {
    AlertSeverity.CRITICAL: "rotating_light,skull",
    AlertSeverity.WARNING: "warning,chart_with_downwards_trend",
    AlertSeverity.INFO: "information_source",
}


async def _send_availability_ntfy(
    title: str, message: str, priority: str = "3", tags: str = ""
) -> None:
    """Send a push notification via ntfy.sh for availability alerts."""
    if not _NTFY_TOPIC:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            safe_title = title.encode("ascii", "replace").decode("ascii")
            await client.post(
                f"{_NTFY_SERVER}/{_NTFY_TOPIC}",
                content=message.encode("utf-8"),
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Title": safe_title,
                    "Priority": priority,
                    "Tags": tags or "brain",
                },
            )
        log.info(f"ntfy availability alert sent: {title}")
    except Exception as e:
        log.warning(f"ntfy availability alert failed: {e}")


def make_ntfy_alert_callback() -> Callable:
    """Create a callback that sends availability alerts to ntfy.

    The returned callback is synchronous (as required by AvailabilityTracker.on_alert)
    but schedules the async ntfy POST on the running event loop.
    """

    def _on_alert(alert: AvailabilityAlert) -> None:
        priority = _SEVERITY_TO_PRIORITY.get(alert.severity, "3")
        tags = _SEVERITY_TO_TAGS.get(alert.severity, "brain")

        title = f"NCL {alert.severity.value.upper()}: {alert.workflow}"
        lines = [
            f"Type: {alert.alert_type.value.replace('_', ' ').title()}",
            f"Workflow: {alert.workflow}",
            f"Current: {alert.current_value:.1f}",
            f"Threshold: {alert.threshold:.1f}",
            f"{alert.message}",
        ]
        message = "\n".join(lines)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send_availability_ntfy(title, message, priority, tags))
        except RuntimeError:
            log.debug("No running event loop for ntfy alert — skipped")

    return _on_alert
