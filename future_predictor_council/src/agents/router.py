"""Real-Time Event Router — routes events to ATLAS and specialized agents.

Turns the system from batch to continuous. Events flow in, get classified,
privacy-checked, and dispatched to the right agents. Dead-letter queue
for unprocessable events.

Architecture (AWS-flavored but broker-agnostic):
  Ingress → Router → ATLAS Mission Control → Agent Dispatch
                   → LANTERN (explanations)
                   → ECHO (briefs)
                   → FORGE (rollbacks)
                   → DLQ (failures)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .events import Event, EventType, PrivacyLevel

logger = logging.getLogger(__name__)


@dataclass
class RouterMetrics:
    """Track router throughput and health."""

    events_received: int = 0
    events_routed: int = 0
    events_dropped: int = 0
    events_dlq: int = 0
    avg_latency_ms: float = 0.0
    _latencies: list[float] = field(default_factory=list)

    def record_latency(self, ms: float) -> None:
        self._latencies.append(ms)
        if len(self._latencies) > 1000:
            self._latencies = self._latencies[-500:]
        self.avg_latency_ms = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0


# Event handler type
EventHandler = Callable[[Event], None]


class EventRouter:
    """Policy-aware real-time event router.

    Routes events to ATLAS and specialized agents based on event type.
    Enforces privacy gates, deduplication, and backpressure.
    """

    def __init__(self, max_dlq_size: int = 1000) -> None:
        # Handler registry: event_type → list of handlers
        self._handlers: dict[str, list[EventHandler]] = {}
        # Catch-all handler for ATLAS
        self._atlas_handler: EventHandler | None = None
        # Dead-letter queue
        self._dlq: deque[Event] = deque(maxlen=max_dlq_size)
        # Dedup window (event_id → timestamp)
        self._seen: dict[str, float] = {}
        self._dedup_window_s: float = 300.0  # 5 min
        # Metrics
        self.metrics = RouterMetrics()

    # ── Registration ────────────────────────────────────────────
    def set_atlas(self, handler: EventHandler) -> None:
        """Set the ATLAS mission control handler (receives ALL events)."""
        self._atlas_handler = handler

    def subscribe(self, event_type: str | EventType, handler: EventHandler) -> None:
        """Subscribe a handler to a specific event type."""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._handlers.setdefault(key, []).append(handler)

    # ── Core Routing ────────────────────────────────────────────
    def route(self, event: Event) -> bool:
        """Route a single event through the pipeline.

        Returns True if successfully routed, False if dropped/DLQ'd.
        """
        start = time.time()
        self.metrics.events_received += 1

        # 1) Deduplication
        if self._is_duplicate(event):
            self.metrics.events_dropped += 1
            logger.debug("[ROUTER] Duplicate event %s dropped", event.id)
            return False

        # 2) Privacy gate — drop PII that shouldn't propagate
        if not self._privacy_check(event):
            self.metrics.events_dropped += 1
            logger.warning("[ROUTER] Event %s dropped by privacy gate", event.id)
            return False

        # 3) Route to ATLAS (always)
        if self._atlas_handler:
            try:
                self._atlas_handler(event)
            except Exception as exc:
                logger.error("[ROUTER] ATLAS handler failed: %s", exc)
                self._dlq.append(event)
                self.metrics.events_dlq += 1
                return False

        # 4) Route to type-specific subscribers
        detail_key = event.detail_type.value if isinstance(event.detail_type, EventType) else event.detail_type
        handlers = self._handlers.get(detail_key, [])

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.error("[ROUTER] Handler failed for %s: %s", detail_key, exc)

        self.metrics.events_routed += 1
        elapsed_ms = (time.time() - start) * 1000
        self.metrics.record_latency(elapsed_ms)

        return True

    def route_batch(self, events: list[Event]) -> int:
        """Route multiple events. Returns count of successfully routed."""
        return sum(1 for e in events if self.route(e))

    # ── Privacy ─────────────────────────────────────────────────
    def _privacy_check(self, event: Event) -> bool:
        """Enforce privacy policy. Returns False to drop."""
        return not (event.privacy.pii and event.privacy.level == PrivacyLevel.RESTRICTED)

    # ── Dedup ───────────────────────────────────────────────────
    def _is_duplicate(self, event: Event) -> bool:
        """At-least-once dedup within the window."""
        now = time.time()
        # Prune old entries
        cutoff = now - self._dedup_window_s
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

        if event.id in self._seen:
            return True
        self._seen[event.id] = now
        return False

    # ── DLQ ─────────────────────────────────────────────────────
    def drain_dlq(self) -> list[Event]:
        """Return and clear dead-letter queue entries."""
        items = list(self._dlq)
        self._dlq.clear()
        return items

    def dlq_size(self) -> int:
        return len(self._dlq)

    # ── Health ──────────────────────────────────────────────────
    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.metrics.events_dlq == 0 else "degraded",
            "received": self.metrics.events_received,
            "routed": self.metrics.events_routed,
            "dropped": self.metrics.events_dropped,
            "dlq": self.metrics.events_dlq,
            "avg_latency_ms": round(self.metrics.avg_latency_ms, 2),
            "handlers": {k: len(v) for k, v in self._handlers.items()},
        }
