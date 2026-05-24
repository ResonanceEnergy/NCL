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
from pathlib import Path
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

# Sentinel loop tunables — W10B-11 stuck-dispatcher detection.
_SENTINEL_INTERVAL_S = float(os.getenv("NCL_ALERT_SENTINEL_INTERVAL_S", "300"))  # 5min
_SENTINEL_STALE_S = float(os.getenv("NCL_ALERT_SENTINEL_STALE_S", "1800"))  # 30min
_SENTINEL_DEPTH_THRESHOLD = int(os.getenv("NCL_ALERT_SENTINEL_DEPTH", "10"))
_SENTINEL_FLAG_PATH = Path(
    os.getenv("NCL_ALERT_SENTINEL_FLAG", "data/alerts/dispatcher-stuck.flag")
)


@dataclass
class Alert:
    title: str
    body: str
    priority: str = "3"  # ntfy priority 1-5
    tags: str = ""  # comma-joined
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
        # W10B-11 — wall-clock timestamp of last *successful* ntfy send.
        # Distinct from `_last_sent_at` (which is bumped pre-send to drive the
        # rate limit even on send failures). 0.0 means "never sent".
        self.last_send_at: float = 0.0
        # W10B-11 — last error string from a failed send (for sentinel context).
        self._last_send_error: Optional[str] = None
        # W10B-11 — sentinel loop singleton guard (idempotent across hot reload).
        self._sentinel_task: Optional[asyncio.Task] = None
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
                # W10B-11 — surface overflow evictions (previously silent).
                log.warning(
                    "[ALERT] queue overflow — dropped oldest (cap=%d, source=%s, title=%r)",
                    _MAX_QUEUE_SIZE,
                    alert.source,
                    alert.title[:80],
                )
            self.stats["enqueued"] += 1
        except Exception as e:  # never raise from a producer
            log.warning("[ALERT] enqueue failed: %s", e)

    # ─── Worker loop ───────────────────────────────────────────────────
    async def dispatch_loop(self) -> None:
        """Drain the queue forever, respecting rate limit + dedup cooldowns."""
        log.info(
            "[ALERT] dispatcher started — topic=%s interval=%.1fs cooldown=%.0fs",
            NTFY_TOPIC,
            _GLOBAL_INTERVAL_S,
            _DEDUP_COOLDOWN_S,
        )
        # Reusable client bound to this loop.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        # W10B-11 — co-locate the sentinel with the dispatcher's lifetime.
        # Idempotent: only spawns if not already running (hot-reload safe).
        self.start_sentinel()
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
            except Exception as _close_err:
                log.warning("[alert_dispatch] httpx client aclose swallowed: %s", _close_err)
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
            # W10B-11 — record success timestamp for sentinel watchdog.
            self.last_send_at = time.time()
            log.info(
                "[ALERT] sent [%s/%s] %s",
                alert.source,
                alert.priority,
                alert.title[:80],
            )
        except Exception as e:
            self.stats["send_failures"] += 1
            self._last_send_error = f"{type(e).__name__}: {e}"
            log.warning("[ALERT] send failed (%s): %s", alert.source, e)

    # ─── W10B-11 stuck-dispatcher sentinel ─────────────────────────────
    def start_sentinel(self) -> None:
        """Spawn _sentinel_loop iff not already running.

        Idempotent: callable from dispatch_loop() startup, scheduler boot, or
        hot-reload without double-instantiating. A task whose `done()` is True
        (e.g. crashed) is replaced with a fresh one.
        """
        existing = self._sentinel_task
        if existing is not None and not existing.done():
            return  # already running
        try:
            self._sentinel_task = asyncio.create_task(
                self._sentinel_loop(),
                name="ncl-alert-dispatch-sentinel",
            )
            log.info(
                "[ALERT] sentinel started — interval=%.0fs stale_threshold=%.0fs depth_threshold=%d flag=%s",  # noqa: E501
                _SENTINEL_INTERVAL_S,
                _SENTINEL_STALE_S,
                _SENTINEL_DEPTH_THRESHOLD,
                _SENTINEL_FLAG_PATH,
            )
        except RuntimeError as e:
            # No running loop — caller should retry from inside an async ctx.
            log.warning("[ALERT] sentinel start deferred (no running loop): %s", e)

    async def _sentinel_loop(self) -> None:
        """Watchdog — every 5min, write a flag file if dispatcher looks stuck.

        Stuck = no successful send in `_SENTINEL_STALE_S` AND queue depth
        exceeds `_SENTINEL_DEPTH_THRESHOLD`. A heartbeat watchdog elsewhere
        stat()s the flag and escalates.
        """
        while True:
            try:
                await asyncio.sleep(_SENTINEL_INTERVAL_S)
                now = time.time()
                depth = len(self._queue)
                last = self.last_send_at
                stale_s = (now - last) if last > 0 else float("inf")
                if stale_s > _SENTINEL_STALE_S and depth > _SENTINEL_DEPTH_THRESHOLD:
                    payload = (
                        f"timestamp={now:.0f}\n"
                        f"queue_depth={depth}\n"
                        f"last_send_at={last:.0f}\n"
                        f"stale_seconds={stale_s:.0f}\n"
                        f"send_failures={self.stats.get('send_failures', 0)}\n"
                        f"last_error={self._last_send_error or 'none'}\n"
                    )
                    try:
                        _SENTINEL_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
                        _SENTINEL_FLAG_PATH.write_text(payload, encoding="utf-8")
                    except Exception as fe:
                        log.error("[ALERT] sentinel flag write failed: %s", fe)
                    log.critical(
                        "[ALERT] DISPATCHER STUCK — depth=%d stale=%.0fs last_send=%.0f last_error=%s",  # noqa: E501
                        depth,
                        stale_s,
                        last,
                        self._last_send_error or "none",
                    )
                else:
                    # Clean up a stale flag once we recover.
                    if _SENTINEL_FLAG_PATH.exists():
                        try:
                            _SENTINEL_FLAG_PATH.unlink()
                            log.info("[ALERT] sentinel cleared stale flag — dispatcher healthy")
                        except Exception:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[ALERT] sentinel iteration error: %s", e, exc_info=True)
                # Don't tight-loop on persistent failure.
                await asyncio.sleep(min(_SENTINEL_INTERVAL_S, 60.0))


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
