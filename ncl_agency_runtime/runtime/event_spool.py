#!/usr/bin/env python3
"""
NCL Event Spool — offline resilience layer.

When the relay server is unreachable, events are written to a local spool
directory instead of being dropped. A background drain thread periodically
retries sending queued events once the server comes back online.

Usage::

    spool = EventSpool(relay_url="http://localhost:8787/event")
    spool.submit(event_dict)   # auto-queues if server unreachable
    spool.drain()              # manual drain attempt
    spool.shutdown()           # stop background thread

Configuration via environment variables:

    NCL_RELAY_URL       — override default relay URL
    NCL_SPOOL_DIR       — override default spool directory
    NCL_SPOOL_DRAIN_INTERVAL — seconds between drain attempts (default 30)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("ncl.event_spool")

_DEFAULT_RELAY_URL = "http://localhost:8787/event"
_DEFAULT_SPOOL_DIR = Path("~/NCL/data/spool").expanduser()
_DEFAULT_DRAIN_INTERVAL = 30  # seconds


class EventSpool:
    """Buffer events locally and drain to relay when online.

    Art of War: 'He who can modify his tactics wins' — graceful offline mode.
    Habit 1 (Be Proactive): Never drop data; queue and retry.
    Law 29 (Plan all the way to the end): Guarantee delivery or audit trail.
    """

    def __init__(
        self,
        relay_url: str | None = None,
        spool_dir: Path | None = None,
        drain_interval: int | None = None,
        api_key: str | None = None,
        auto_start: bool = True,
    ) -> None:
        self.relay_url = relay_url or os.environ.get("NCL_RELAY_URL", _DEFAULT_RELAY_URL)
        raw_dir = spool_dir or Path(os.environ.get("NCL_SPOOL_DIR", str(_DEFAULT_SPOOL_DIR)))
        self.spool_dir = Path(raw_dir).expanduser()
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.drain_interval = drain_interval or int(
            os.environ.get("NCL_SPOOL_DRAIN_INTERVAL", str(_DEFAULT_DRAIN_INTERVAL))
        )
        self.api_key = api_key or os.environ.get("NCL_API_KEY", "")

        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        if auto_start:
            self.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, event: dict[str, Any]) -> bool:
        """Try to send *event* directly; spool it locally on failure.

        Returns True if delivered immediately, False if spooled.
        """
        event.setdefault("event_id", str(uuid.uuid4()))
        event.setdefault("observed_at", datetime.now(UTC).isoformat())

        if self._try_send(event):
            logger.debug("Event %s delivered directly.", event["event_id"])
            return True

        self._spool(event)
        logger.info(
            "Relay unreachable — spooled event %s (queue depth: %d)",
            event["event_id"],
            self._queue_depth(),
        )
        return False

    def drain(self) -> int:
        """Attempt to send all spooled events. Returns number successfully drained."""
        files = sorted(self.spool_dir.glob("*.json"))
        if not files:
            return 0

        drained = 0
        for path in files:
            try:
                with self._lock:
                    if not path.exists():
                        continue
                    raw = path.read_text(encoding="utf-8")

                event = json.loads(raw)
                if self._try_send(event):
                    path.unlink(missing_ok=True)
                    drained += 1
                    logger.debug("Drained spooled event %s.", event.get("event_id"))
                else:
                    # Server still unreachable — stop trying for this cycle
                    break
            except Exception as exc:
                logger.warning("Error draining %s: %s", path.name, exc)

        if drained:
            logger.info("Spool drain: %d events delivered.", drained)
        return drained

    def queue_depth(self) -> int:
        """Number of events currently in the spool."""
        return self._queue_depth()

    def start(self) -> None:
        """Start background drain thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._drain_loop,
            name="ncl-event-spool-drainer",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Event spool started (dir=%s, interval=%ds, relay=%s)",
            self.spool_dir,
            self.drain_interval,
            self.relay_url,
        )

    def shutdown(self) -> None:
        """Stop the background drain thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Event spool shut down (remaining queue: %d).", self._queue_depth())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_send(self, event: dict[str, Any]) -> bool:
        """Attempt a single HTTP POST. Returns True on 2xx, False otherwise."""
        body = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            self.relay_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            # 4xx = server rejected event (bad schema, etc.) — do NOT re-queue
            if 400 <= exc.code < 500:
                logger.warning(
                    "Relay rejected event %s (%d) — discarding.",
                    event.get("event_id"),
                    exc.code,
                )
                return True  # treat as "delivered" to avoid infinite retry
            return False
        except Exception:
            return False

    def _spool(self, event: dict[str, Any]) -> None:
        """Write event to spool directory as a JSON file."""
        event_id = event.get("event_id", str(uuid.uuid4()))
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        filename = f"{ts}--{event_id[:8]}.json"
        path = self.spool_dir / filename
        with self._lock:
            path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")

    def _queue_depth(self) -> int:
        try:
            return sum(1 for _ in self.spool_dir.glob("*.json"))
        except Exception:
            return 0

    def _drain_loop(self) -> None:
        """Background thread: periodically drain spool."""
        while self._running:
            try:
                if self._queue_depth() > 0:
                    self.drain()
            except Exception as exc:
                logger.warning("Drain loop error: %s", exc)
            time.sleep(self.drain_interval)


# ---------------------------------------------------------------------------
# Module-level convenience singleton
# ---------------------------------------------------------------------------

_spool_instance: EventSpool | None = None
_spool_lock = threading.Lock()


def get_event_spool(
    relay_url: str | None = None,
    spool_dir: Path | None = None,
) -> EventSpool:
    """Return (or create) the module-level EventSpool singleton."""
    global _spool_instance
    with _spool_lock:
        if _spool_instance is None:
            _spool_instance = EventSpool(relay_url=relay_url, spool_dir=spool_dir)
        return _spool_instance


def submit_event(event: dict[str, Any]) -> bool:
    """Convenience wrapper — submit via module singleton."""
    return get_event_spool().submit(event)
