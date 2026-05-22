"""
NCL Centralized Alert Dispatcher
================================

Single queue + worker for every push notification the Brain emits.
Replaces the five independent ntfy POST sites (supervisor, calendar
alerts, cost tracker budget alerts, journal pushes, awarebot pushes)
with one in-memory queue, a global rate limit (max 1 per 10s by
default), and per-dedup-key cooldowns (1 hour default).

Usage
-----
    from runtime.notifications import enqueue_alert

    enqueue_alert(
        title="NCL Cost Warning",
        body="Anthropic at 80% of daily budget",
        priority="4",
        tags="warning,money_with_wings",
        dedup_key="cost:anthropic:80pct",
        source="cost_tracker",
    )

The actual POST happens later from the worker loop
(`AlertDispatcher.dispatch_loop()`), which the autonomous scheduler
spawns once as `ncl-alert-dispatch`.

Design notes
------------
- enqueue_alert() is synchronous and never blocks — it uses an
  unbounded ``asyncio.Queue.put_nowait`` (queue is capped at 500 with
  drop-oldest semantics to bound memory).
- Dispatcher writes to a configurable ntfy topic (env
  ``NTFY_TOPIC``) with ``httpx``. Failures are logged but never
  raised — push notifications must never crash NCL.
- Dedup key cooldowns survive within the dispatcher's lifetime but
  not across restarts (acceptable for a process that lives for
  weeks).
- Backward-compat fallback: callers may still post directly to ntfy
  if they cannot reach the dispatcher (e.g. tests, scripts). The
  scheduler-driven loops use this module exclusively now.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger("ncl.notifications")

# ── Tunables (env-overridable) ─────────────────────────────────────────
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "ncl-natrix-intel-7x9k")

# Global rate limit: at most 1 alert posted every N seconds.
_GLOBAL_INTERVAL_S = float(os.getenv("NCL_ALERT_INTERVAL_S", "10"))
# Per-dedup-key cooldown in seconds.
_DEDUP_COOLDOWN_S = float(os.getenv("NCL_ALERT_DEDUP_COOLDOWN_S", "3600"))
# Bounded queue — drop oldest if a runaway producer floods.
_MAX_QUEUE_SIZE = int(os.getenv("NCL_ALERT_QUEUE_MAX", "500"))


@dataclass
class Alert:
    title: str
    body: str
    priority: str = "3"  # ntfy priority 1-5
    tags: str = ""        # comma-joined
    dedup_key: Optional[str] = None
    source: str = "generic"
    enqueued_at: float = field(default_factory=time.time)


class AlertDispatcher:
    """Single shared queue + worker for outbound notifications."""

    def __init__(self) -> None:
        # asyncio.Queue is async-safe; put_nowait is synchronous (good — many
        # callers are sync code paths).
        self._queue: deque[Alert] = deque(maxlen=_MAX_QUEUE_SIZE)
        # Per-dedup-key last-sent timestamp (unix seconds).
        self._dedup: dict[str, float] = {}
        # Last-global-send timestamp for rate limiting.
        self._last_sent_at: float = 0.0
        # Reusable client; lazily created in the loop's own loop context.
        self._client: Optional[httpx.AsyncClient] = None
        # Stats
        self.stats = {
            "enqueued": 0,
            "dispatched": 0,
            "dropped_dedup": 0,
            "dropped_overflow": 0,
            "send_failures": 0,
            "last_send_at": None,
        }

    # ─── Producer-side API ─────────────────────────────────────────────
    def enqueue(
        self,
        title: str,
        body: str,
        priority: str = "3",
        tags: str = "",
        dedup_key: Optional[str] = None,
        source: str = "generic",
    ) -> None:
        """Synchronously append an alert. Never blocks, never raises."""
        try:
            alert = Alert(
                title=str(title)[:200],
                body=str(body)[:3500],
                priority=str(priority),
                tags=str(tags),
                dedup_key=dedup_key,
                source=source,
            )
            # If queue full, deque(maxlen) silently drops oldest.
            pre_len = len(self._queue)
            self._queue.append(alert)
            if pre_len == _MAX_QUEUE_SIZE:
                self.stats["dropped_overflow"] += 1
            self.stats["enqueued"] += 1
        except Exception as e:  # never raise from a producer
            log.warning("[ALERT] enqueue failed: %s", e)

    # ─── Worker loop ───────────────────────────────────────────────────
    async def dispatch_loop(self) -> None:
        """Drain the queue forever, respecting rate limit + dedup cooldowns."""
        log.info(
            "[ALERT] dispatcher started — topic=%s interval=%.1fs cooldown=%.0fs",
            NTFY_TOPIC, _GLOBAL_INTERVAL_S, _DEDUP_COOLDOWN_S,
        )
        # Reusable client bound to this loop.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        try:
            while True:
                try:
                    alert = self._pop_next_eligible()
                    if alert is None:
                        # Empty (or only-dedup-blocked) — back off briefly.
                        await asyncio.sleep(1.0)
                        continue

                    # Global rate limit
                    now = time.time()
                    wait = self._last_sent_at + _GLOBAL_INTERVAL_S - now
                    if wait > 0:
                        await asyncio.sleep(wait)

                    await self._send(alert)
                    self._last_sent_at = time.time()
                    self.stats["last_send_at"] = self._last_sent_at
                    if alert.dedup_key:
                        self._dedup[alert.dedup_key] = self._last_sent_at
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.error("[ALERT] dispatch_loop iteration error: %s", e, exc_info=True)
                    await asyncio.sleep(2.0)
        finally:
            try:
                if self._client is not None:
                    await self._client.aclose()
            except Exception:
                pass
            self._client = None

    def _pop_next_eligible(self) -> Optional[Alert]:
        """Pop the first alert whose dedup_key isn't on cooldown.
        Returns None if the queue is empty or all entries are dedup-blocked.
        Dedup-blocked entries are dropped (counted)."""
        now = time.time()
        # Walk up to len(queue) entries — anything dedup-blocked is removed.
        n = len(self._queue)
        for _ in range(n):
            try:
                alert = self._queue.popleft()
            except IndexError:
                return None
            if alert.dedup_key:
                last = self._dedup.get(alert.dedup_key, 0.0)
                if now - last < _DEDUP_COOLDOWN_S:
                    self.stats["dropped_dedup"] += 1
                    continue
            return alert
        return None

    async def _send(self, alert: Alert) -> None:
        """POST one alert to ntfy. Logged-only on failure."""
        if self._client is None:
            log.warning("[ALERT] no http client — dropping alert: %s", alert.title)
            return
        try:
            headers = {
                "Content-Type": "text/plain; charset=utf-8",
                "Title": alert.title.encode("ascii", "replace").decode("ascii"),
                "Priority": alert.priority,
            }
            if alert.tags:
                headers["Tags"] = alert.tags
            resp = await self._client.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                content=alert.body.encode("utf-8"),
                headers=headers,
            )
            resp.raise_for_status()
            self.stats["dispatched"] += 1
            log.info(
                "[ALERT] sent [%s/%s] %s",
                alert.source, alert.priority, alert.title[:80],
            )
        except Exception as e:
            self.stats["send_failures"] += 1
            log.warning("[ALERT] send failed (%s): %s", alert.source, e)


# ── Singleton accessor ────────────────────────────────────────────────
_dispatcher_singleton: Optional[AlertDispatcher] = None


def get_alert_dispatcher() -> AlertDispatcher:
    """Return the process-wide singleton dispatcher (lazy init)."""
    global _dispatcher_singleton
    if _dispatcher_singleton is None:
        _dispatcher_singleton = AlertDispatcher()
    return _dispatcher_singleton


def enqueue_alert(
    title: str,
    body: str,
    priority: str = "3",
    tags: str = "",
    dedup_key: Optional[str] = None,
    source: str = "generic",
) -> None:
    """Module-level convenience — most callers should use this."""
    get_alert_dispatcher().enqueue(
        title=title,
        body=body,
        priority=priority,
        tags=tags,
        dedup_key=dedup_key,
        source=source,
    )
