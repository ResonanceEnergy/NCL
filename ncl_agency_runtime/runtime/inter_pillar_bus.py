#!/usr/bin/env python3
"""
NCC Inter-Pillar Message Bus — Cross-pillar communication backbone.
═══════════════════════════════════════════════════════════════════
Messages flow between NCC, NCL, AAC, BRS, and Digital Labour
via typed envelopes with routing, priority, audit trails, and dead-letter.

Design Principles:
    - Art of War: "Speed is the essence of war" — async, non-blocking
    - Law 9: "Win through actions" — every message is auditable evidence
    - Habit 6: "Synergize" — pillars amplify each other through the bus
    - Dario Amodei: "Interpretability" — every message is traceable
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from ncl_agency_runtime.runtime.pillar_registry import PillarID

LOG = logging.getLogger("ncc.message_bus")


# ═══════════════════════════════════════════════════════════════
#  Message Types
# ═══════════════════════════════════════════════════════════════

class MessageType(StrEnum):
    """Types of inter-pillar messages."""
    # Operational
    REQUEST = "request"           # Ask a pillar to do something
    RESPONSE = "response"         # Reply to a request
    EVENT = "event"               # Fire-and-forget notification
    COMMAND = "command"           # NCC directive (must-execute)

    # Governance
    HEARTBEAT = "heartbeat"       # Health check
    STATUS_REPORT = "status_report"
    AUDIT = "audit"               # Audit trail entry
    ALERT = "alert"               # Escalation to NCC

    # Labour
    TASK_ASSIGN = "task_assign"   # Assign work to Digital Labour
    TASK_RESULT = "task_result"   # Return completed work
    TASK_FAILED = "task_failed"   # Report failure


class Priority(StrEnum):
    """Message priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"         # Faraday Fortress escalation


# ═══════════════════════════════════════════════════════════════
#  Message Envelope
# ═══════════════════════════════════════════════════════════════

@dataclass
class PillarMessage:
    """Typed envelope for inter-pillar communication.

    Every message has:
        - source/target pillars (routing)
        - type + priority (dispatch)
        - correlation_id (request/response linking)
        - trace_id (end-to-end tracing across pillar boundaries)
        - payload (the actual data)
        - audit fields (timestamp, ttl, attempt tracking)
    """
    source: PillarID
    target: PillarID
    msg_type: MessageType
    payload: dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL

    # Identity & tracing
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    correlation_id: str = ""      # links request→response
    trace_id: str = ""            # spans entire cross-pillar flow

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    ttl_seconds: int = 300        # message expires after this window
    attempt: int = 1
    max_attempts: int = 3

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        d["target"] = self.target.value
        d["msg_type"] = self.msg_type.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PillarMessage:
        d = dict(d)
        d["source"] = PillarID(d["source"])
        d["target"] = PillarID(d["target"])
        d["msg_type"] = MessageType(d["msg_type"])
        d["priority"] = Priority(d.get("priority", "normal"))
        return cls(**d)

    def make_response(self, payload: dict[str, Any], **kwargs: Any) -> PillarMessage:
        """Create a response message linked to this request."""
        return PillarMessage(
            source=self.target,
            target=self.source,
            msg_type=MessageType.RESPONSE,
            payload=payload,
            correlation_id=self.msg_id,
            trace_id=self.trace_id or self.msg_id,
            **kwargs,
        )

    @property
    def is_expired(self) -> bool:
        ts = datetime.fromisoformat(self.timestamp)
        now = datetime.now(UTC)
        return (now - ts).total_seconds() > self.ttl_seconds

    @property
    def can_retry(self) -> bool:
        return self.attempt < self.max_attempts


# ═══════════════════════════════════════════════════════════════
#  Handler Type
# ═══════════════════════════════════════════════════════════════

# Handler signature: async def handler(msg: PillarMessage) -> PillarMessage | None
MessageHandler = Any  # Callable[[PillarMessage], Awaitable[PillarMessage | None]]


# ═══════════════════════════════════════════════════════════════
#  Inter-Pillar Message Bus
# ═══════════════════════════════════════════════════════════════

class InterPillarBus:
    """Async message bus connecting all NCC pillars.

    Features:
        - Topic-based routing: pillar_id + msg_type
        - Priority queuing
        - Dead-letter queue for failed deliveries
        - Audit log persistence (NDJSON)
        - Wildcard subscription ("*" receives all)
        - Correlation-based request/response pattern

    Art of War: "Speed is the essence of war" — asyncio queue, non-blocking.
    Law 29: "Plan all the way to the end" — TTL, retries, dead-letter.
    Habit 2: "Begin with the end in mind" — every message has a trace_id.
    """

    _instance: ClassVar[InterPillarBus | None] = None

    def __init__(self, audit_path: Path | str | None = None) -> None:
        # Handlers keyed by (target_pillar, msg_type) or ("*", "*") for wildcard
        self._handlers: dict[tuple[str, str], list[MessageHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[PillarMessage] = asyncio.Queue()
        self._dead_letter: list[PillarMessage] = []
        self._audit_log: list[dict] = []
        self._audit_path: Path | None = Path(audit_path) if audit_path else None
        self._running = False
        self._processed = 0
        self._failed = 0
        self._pending_responses: dict[str, asyncio.Future[PillarMessage]] = {}
        self._lock = asyncio.Lock()

        if self._audit_path:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls, audit_path: Path | str | None = None) -> InterPillarBus:
        if cls._instance is None:
            cls._instance = cls(audit_path=audit_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ── Subscription ──────────────────────────────────────────

    def subscribe(self, pillar_id: PillarID | str, msg_type: MessageType | str,
                  handler: MessageHandler) -> None:
        """Register a handler for messages targeting a pillar + type combo.

        Use "*" for either argument to receive all.
        """
        key = (str(pillar_id), str(msg_type))
        self._handlers[key].append(handler)
        LOG.debug("Subscribed handler for %s", key)

    def subscribe_pillar(self, pillar_id: PillarID, handler: MessageHandler) -> None:
        """Subscribe to ALL message types for a given pillar."""
        self.subscribe(pillar_id, "*", handler)

    def subscribe_all(self, handler: MessageHandler) -> None:
        """Subscribe to every message on the bus (NCC governance audit)."""
        self.subscribe("*", "*", handler)

    # ── Publishing ────────────────────────────────────────────

    async def publish(self, msg: PillarMessage) -> None:
        """Enqueue a message for delivery."""
        if not msg.trace_id:
            msg.trace_id = msg.msg_id
        self._audit_entry("enqueued", msg)
        await self._queue.put(msg)

    async def request(self, msg: PillarMessage, timeout: float = 30.0) -> PillarMessage | None:
        """Send a request and wait for the correlated response.

        Returns the response message, or None on timeout.
        """
        future: asyncio.Future[PillarMessage] = asyncio.get_event_loop().create_future()
        self._pending_responses[msg.msg_id] = future
        await self.publish(msg)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            LOG.warning("Request %s timed out after %.1fs", msg.msg_id, timeout)
            return None
        finally:
            self._pending_responses.pop(msg.msg_id, None)

    # ── Dispatch Loop ─────────────────────────────────────────

    async def start(self) -> None:
        """Start the message dispatch loop."""
        self._running = True
        LOG.info("InterPillarBus started")
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            if msg.is_expired:
                self._audit_entry("expired", msg)
                self._dead_letter.append(msg)
                self._failed += 1
                continue

            await self._dispatch(msg)

    async def stop(self) -> None:
        """Stop the dispatch loop."""
        self._running = False
        LOG.info("InterPillarBus stopped (processed=%d, failed=%d)", self._processed, self._failed)

    async def _dispatch(self, msg: PillarMessage) -> None:
        """Route a message to matching handlers."""
        handlers: list[MessageHandler] = []
        # Exact match
        key = (str(msg.target), str(msg.msg_type))
        handlers.extend(self._handlers.get(key, []))
        # Pillar wildcard
        handlers.extend(self._handlers.get((str(msg.target), "*"), []))
        # Type wildcard
        handlers.extend(self._handlers.get(("*", str(msg.msg_type)), []))
        # Global wildcard
        handlers.extend(self._handlers.get(("*", "*"), []))

        if not handlers:
            LOG.warning("No handler for %s → %s [%s]", msg.source.value, msg.target.value, msg.msg_type.value)
            if msg.can_retry:
                msg.attempt += 1
                await self._queue.put(msg)
                self._audit_entry("retry", msg)
            else:
                self._dead_letter.append(msg)
                self._audit_entry("dead_letter", msg)
                self._failed += 1
            return

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    response = await handler(msg)
                else:
                    response = handler(msg)

                # If a correlated response, resolve the pending future
                if response and isinstance(response, PillarMessage):
                    if response.correlation_id in self._pending_responses:
                        fut = self._pending_responses.pop(response.correlation_id)
                        if not fut.done():
                            fut.set_result(response)
                    else:
                        # Publish response as a new message
                        await self.publish(response)

            except Exception as exc:
                LOG.error("Handler error on %s: %s", msg.msg_id, exc)
                self._audit_entry("handler_error", msg, error=str(exc))

        self._processed += 1
        self._audit_entry("delivered", msg)

    # ── Synchronous dispatch (for non-async contexts) ─────────

    def dispatch_sync(self, msg: PillarMessage) -> list[PillarMessage | None]:
        """Dispatch a message synchronously — for use outside async context."""
        handlers: list[MessageHandler] = []
        key = (str(msg.target), str(msg.msg_type))
        handlers.extend(self._handlers.get(key, []))
        handlers.extend(self._handlers.get((str(msg.target), "*"), []))
        handlers.extend(self._handlers.get(("*", str(msg.msg_type)), []))
        handlers.extend(self._handlers.get(("*", "*"), []))

        results: list[PillarMessage | None] = []
        for handler in handlers:
            try:
                result = handler(msg)
                results.append(result)
            except Exception as exc:
                LOG.error("Sync handler error on %s: %s", msg.msg_id, exc)
        self._processed += 1
        self._audit_entry("delivered_sync", msg)
        return results

    # ── Audit ─────────────────────────────────────────────────

    def _audit_entry(self, action: str, msg: PillarMessage, **extra: Any) -> None:
        entry = {
            "action": action,
            "msg_id": msg.msg_id,
            "trace_id": msg.trace_id,
            "source": msg.source.value,
            "target": msg.target.value,
            "msg_type": msg.msg_type.value,
            "priority": msg.priority.value,
            "attempt": msg.attempt,
            "ts": datetime.now(UTC).isoformat(),
            **extra,
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]
        if self._audit_path:
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    # ── Diagnostics ───────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "processed": self._processed,
            "failed": self._failed,
            "dead_letter_count": len(self._dead_letter),
            "queue_size": self._queue.qsize(),
            "handler_count": sum(len(h) for h in self._handlers.values()),
            "pending_responses": len(self._pending_responses),
        }

    @property
    def dead_letters(self) -> list[dict]:
        return [m.to_dict() for m in self._dead_letter]
