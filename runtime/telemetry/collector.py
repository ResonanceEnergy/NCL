"""Telemetry Collector for NCL Brain Pipeline.

Buffers, redacts, and persists telemetry records. Respects privacy levels.
Runs background flush tasks on configurable intervals.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from statistics import mean, quantiles

from .schema import (
    TelemetryLevel,
    TelemetryRecord,
    TelemetryConfig,
    TelemetryCategory,
    WorkflowTelemetry,
    RedactionRule,
)

logger = logging.getLogger(__name__)


class TelemetryCollector:
    """NCL Brain telemetry collector with buffer and redaction."""

    def __init__(
        self,
        data_dir: str | Path,
        config: Optional[TelemetryConfig] = None,
    ):
        """Initialize telemetry collector.

        Args:
            data_dir: Root data directory. Creates data_dir/telemetry/
            config: TelemetryConfig instance. Defaults to TelemetryConfig()
        """
        self.data_dir = Path(data_dir)
        self.telemetry_dir = self.data_dir / "telemetry"
        self.config = config or TelemetryConfig()

        # Ensure directory exists
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)

        # Buffer
        self._buffer: list[TelemetryRecord] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._shutdown = False

        logger.info(
            f"TelemetryCollector initialized: level={self.config.level}, "
            f"redaction={self.config.redaction_enabled}, "
            f"dir={self.telemetry_dir}"
        )

    async def init(self) -> None:
        """Start background flush task."""
        if self.config.enabled and self.config.level != TelemetryLevel.OFF:
            self._flush_task = asyncio.create_task(self._auto_flush_loop())
            logger.info("Telemetry auto-flush started")

    async def shutdown(self) -> None:
        """Stop background task and flush remaining records."""
        self._shutdown = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()
        logger.info("TelemetryCollector shutdown complete")

    def record(
        self,
        category: TelemetryCategory | str,
        workflow: str,
        action: str,
        *,
        duration_ms: Optional[float] = None,
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        counters: Optional[dict[str, int]] = None,
        gauges: Optional[dict[str, float]] = None,
        success: bool = True,
        error_type: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> TelemetryRecord:
        """Record a telemetry event.

        Args:
            category: TelemetryCategory enum or string
            workflow: Workflow name (e.g., 'pump_intake')
            action: Action name (e.g., 'started', 'completed')
            duration_ms: Operation duration in milliseconds
            correlation_id: Correlation ID (will be hashed)
            session_id: Session identifier
            counters: Count metrics
            gauges: Gauge metrics
            success: Whether operation succeeded
            error_type: Error class name (not message)
            payload: Additional data (redacted before persistence)

        Returns:
            TelemetryRecord instance
        """
        if self.config.level == TelemetryLevel.OFF or not self.config.enabled:
            # Return a no-op record
            return TelemetryRecord(
                category=category,
                workflow=workflow,
                action=action,
            )

        # Build record
        record = TelemetryRecord(
            category=category,
            workflow=workflow,
            action=action,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            session_id=session_id,
            counters=counters or {},
            gauges=gauges or {},
            success=success,
            error_type=error_type,
            payload=payload or {},
            telemetry_level=self.config.level,
        )

        # Filter by level
        if self.config.level == TelemetryLevel.MINIMAL:
            # Keep only counters and timing
            record.payload = {}
            record.workflow = ""
            record.action = ""
        elif self.config.level == TelemetryLevel.STANDARD:
            # Keep workflow, action, but no payload
            record.payload = {}

        # Redact if enabled
        if self.config.redaction_enabled:
            record = record.redacted()

        # Add to buffer synchronously
        self._buffer.append(record)

        # Check if should flush (non-blocking)
        if len(self._buffer) >= self.config.max_buffer_size:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule flush as task
                    asyncio.create_task(self.flush())
                else:
                    # No running loop, flush synchronously
                    loop.run_until_complete(self.flush())
            except RuntimeError:
                # No event loop, run in new loop
                asyncio.run(self.flush())

        return record

    async def flush(self) -> None:
        """Write buffer to disk (NDJSON format)."""
        if not self._buffer:
            return

        async with self._lock:
            if not self._buffer:
                return

            records = self._buffer.copy()
            self._buffer.clear()

        # Write to file with today's date
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = self.telemetry_dir / f"{today}.ndjson"

        try:
            # Serialize records first, then offload blocking write to thread
            lines = [record.model_dump_json() + "\n" for record in records]

            def _write() -> None:
                with open(filepath, "a") as f:
                    f.writelines(lines)

            await asyncio.to_thread(_write)
            logger.debug(
                f"Flushed {len(records)} telemetry records to {filepath}"
            )
        except Exception as e:
            logger.error(f"Failed to flush telemetry: {e}")
            # Re-buffer on failure
            async with self._lock:
                self._buffer.extend(records)

    async def _auto_flush_loop(self) -> None:
        """Background task: flush on interval."""
        while not self._shutdown:
            try:
                await asyncio.sleep(self.config.flush_interval_seconds)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto-flush loop: {e}")

    def get_recent(self, n: int = 100) -> list[TelemetryRecord]:
        """Get last N records from buffer."""
        return self._buffer[-n:]

    def get_workflow_stats(
        self, workflow: str, hours_back: int = 24
    ) -> Optional[WorkflowTelemetry]:
        """Calculate aggregated stats for a workflow in the past N hours.

        Args:
            workflow: Workflow name to aggregate
            hours_back: Look back this many hours

        Returns:
            WorkflowTelemetry with aggregated metrics, or None if no records
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        # Load records from files in the timeframe
        records = self._load_records_in_range(cutoff)

        # Filter by workflow
        matching = [
            r for r in records
            if r.workflow == workflow and r.timestamp >= cutoff
        ]

        if not matching:
            return None

        # Aggregate
        durations = [r.duration_ms for r in matching if r.duration_ms]
        successful = sum(1 for r in matching if r.success)
        failed = sum(1 for r in matching if not r.success)

        # Percentiles
        avg_duration = mean(durations) if durations else 0.0
        p95 = p99 = 0.0
        if len(durations) > 1:
            quantile_vals = quantiles(durations, n=100)
            p95 = quantile_vals[94]  # 95th percentile
            p99 = quantile_vals[98]  # 99th percentile

        # Error distribution
        error_dist = {}
        for r in matching:
            if r.error_type:
                error_dist[r.error_type] = error_dist.get(r.error_type, 0) + 1

        return WorkflowTelemetry(
            workflow=workflow,
            period_start=cutoff,
            period_end=datetime.now(timezone.utc),
            total_executions=len(matching),
            successful=successful,
            failed=failed,
            avg_duration_ms=avg_duration,
            p95_duration_ms=p95,
            p99_duration_ms=p99,
            error_distribution=error_dist,
        )

    def get_all_workflow_stats(
        self, hours_back: int = 24
    ) -> list[WorkflowTelemetry]:
        """Get stats for all workflows in the past N hours.

        Args:
            hours_back: Look back this many hours

        Returns:
            List of WorkflowTelemetry
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        records = self._load_records_in_range(cutoff)

        # Group by workflow
        workflows = {}
        for r in records:
            if r.timestamp >= cutoff:
                workflows.setdefault(r.workflow, []).append(r)

        # Aggregate each
        stats = []
        for workflow, matching in workflows.items():
            if not workflow:  # Skip MINIMAL level with empty workflow
                continue

            durations = [r.duration_ms for r in matching if r.duration_ms]
            successful = sum(1 for r in matching if r.success)
            failed = sum(1 for r in matching if not r.success)

            avg_duration = mean(durations) if durations else 0.0
            p95 = p99 = 0.0
            if len(durations) > 1:
                quantile_vals = quantiles(durations, n=100)
                p95 = quantile_vals[94]
                p99 = quantile_vals[98]

            error_dist = {}
            for r in matching:
                if r.error_type:
                    error_dist[r.error_type] = (
                        error_dist.get(r.error_type, 0) + 1
                    )

            stats.append(
                WorkflowTelemetry(
                    workflow=workflow,
                    period_start=cutoff,
                    period_end=datetime.now(timezone.utc),
                    total_executions=len(matching),
                    successful=successful,
                    failed=failed,
                    avg_duration_ms=avg_duration,
                    p95_duration_ms=p95,
                    p99_duration_ms=p99,
                    error_distribution=error_dist,
                )
            )

        return stats

    def _load_records_in_range(
        self, start_time: datetime
    ) -> list[TelemetryRecord]:
        """Load all records from NDJSON files in date range.

        Note: This method performs synchronous file I/O.  It is called from
        synchronous ``get_workflow_stats`` / ``get_all_workflow_stats`` helpers,
        so wrapping it in ``asyncio.to_thread`` is the caller's responsibility
        if the event loop must not block.

        Args:
            start_time: Lower bound (loads all files from this date onward)

        Returns:
            List of TelemetryRecord instances
        """
        records = []

        # Include current buffer
        records.extend(self._buffer)

        # Load from files
        if not self.telemetry_dir.exists():
            return records

        start_date = start_time.date()
        current_date = datetime.now(timezone.utc).date()

        # Iterate through date range
        current = start_date
        while current <= current_date:
            filepath = self.telemetry_dir / f"{current}.ndjson"
            if filepath.exists():
                try:
                    with open(filepath) as f:
                        for line in f:
                            if line.strip():
                                try:
                                    data = json.loads(line)
                                    record = TelemetryRecord(**data)
                                    records.append(record)
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.warning(f"Skipping malformed telemetry record in {filepath}: {e}")
                except Exception as e:
                    logger.error(f"Error reading {filepath}: {e}")
            current += timedelta(days=1)

        return records
