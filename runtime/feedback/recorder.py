"""Feedback event recorder — captures iOS user actions on signals/predictions/briefs.

Lightweight append-only JSONL stream. Distinct from the pillar-feedback
synthesis pipeline (scanner.py / models.py) which consumes structured reports
from NCC/BRS/AAC. This recorder is for *user behavior* telemetry — what NATRIX
pinned, dismissed, paper-traded, councilled, etc. on the FirstStrike iOS app.

Output: data_dir/feedback/events.jsonl, rotated at 50MB to
events.jsonl.<UTC-stamp>.gz-not-actually-gz (kept plain for grep-ability;
rotation just renames so cold reads still work via scanning).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.feedback.recorder")

# 50 MB rotation threshold
_ROTATE_BYTES = 50 * 1024 * 1024


class FeedbackRecorder:
    """Append-only event-stream recorder for iOS user actions.

    Thread-safe via an asyncio.Lock; writes are small and synchronous on the
    event loop (no async I/O dependency — JSONL append + occasional rotation).
    """

    EVENT_TYPES = {
        "view", "expand", "pin", "unpin", "dismiss",
        "council_request", "paper_trade", "share",
        "outcome_correct", "outcome_wrong", "outcome_partial",
    }

    def __init__(self, data_dir: Path):
        self._base_dir = Path(data_dir) / "feedback"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self._base_dir / "events.jsonl"
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ utils

    def _rotate_if_needed(self) -> None:
        """If events.jsonl exceeds 50MB, rename it with a UTC suffix."""
        try:
            if not self._events_path.exists():
                return
            if self._events_path.stat().st_size < _ROTATE_BYTES:
                return
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            rotated = self._events_path.with_name(f"events.jsonl.{stamp}")
            self._events_path.rename(rotated)
            log.info("rotated feedback events log -> %s", rotated.name)
        except Exception as exc:
            log.warning("feedback rotation failed: %s", exc)

    def _all_log_files(self) -> list[Path]:
        """Current + rotated, newest-first by name (UTC-suffix sorts correctly)."""
        files: list[Path] = []
        if self._events_path.exists():
            files.append(self._events_path)
        rotated = sorted(
            (p for p in self._base_dir.glob("events.jsonl.*") if p.is_file()),
            reverse=True,
        )
        files.extend(rotated)
        return files

    # ------------------------------------------------------------------ api

    async def record(
        self,
        event_type: str,
        signal_id: str,
        source: str = "",
        tier: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """Append a feedback event. Returns the persisted event dict."""
        if event_type not in self.EVENT_TYPES:
            raise ValueError(
                f"unknown event_type '{event_type}'; "
                f"allowed: {sorted(self.EVENT_TYPES)}"
            )
        if not signal_id or not isinstance(signal_id, str):
            raise ValueError("signal_id is required and must be a string")

        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "signal_id": signal_id,
            "source": source or "",
            "tier": tier or "",
            "metadata": metadata or {},
            "ts": datetime.now(timezone.utc).isoformat(),
            "ts_epoch": time.time(),
        }

        async with self._lock:
            self._rotate_if_needed()
            line = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
            with self._events_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return event

    async def query(
        self,
        event_type: str | None = None,
        signal_id: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Tail-read events, newest-first, with optional filters.

        Scans the current log first, then rotated files until `limit` is met.
        Since filters use ISO timestamps; supply tz-aware datetimes.
        """
        if limit <= 0:
            return []
        since_epoch: Optional[float] = None
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            since_epoch = since.timestamp()

        # Snapshot under the lock so we don't race with a rotation rename.
        async with self._lock:
            files = self._all_log_files()

        results: list[dict] = []
        for path in files:
            try:
                # Read whole file then iterate reverse — feedback logs are
                # small (50MB cap) so this is fine and keeps the code simple.
                with path.open("r", encoding="utf-8") as fh:
                    lines = fh.readlines()
            except Exception as exc:
                log.warning("could not read feedback log %s: %s", path, exc)
                continue
            for raw in reversed(lines):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if event_type and obj.get("event_type") != event_type:
                    continue
                if signal_id and obj.get("signal_id") != signal_id:
                    continue
                if since_epoch is not None:
                    ev_epoch = obj.get("ts_epoch")
                    if ev_epoch is None:
                        # Fall back to parsing ISO ts
                        try:
                            ev_epoch = datetime.fromisoformat(
                                obj.get("ts", "").replace("Z", "+00:00")
                            ).timestamp()
                        except Exception:
                            ev_epoch = 0.0
                    if ev_epoch < since_epoch:
                        # Past the cutoff in this file; older files are even older.
                        return results
                results.append(obj)
                if len(results) >= limit:
                    return results
        return results

    def stats(self) -> dict:
        """Per-event counts, top-10 signal_ids, pin/dismiss ratio.

        Reads all log files (current + rotated). Synchronous — for occasional
        ops surfacing, not a hot path. Safe to call from a sync FastAPI handler.
        """
        per_event: Counter = Counter()
        per_signal: Counter = Counter()
        per_source: Counter = Counter()
        total = 0
        earliest: Optional[float] = None
        latest: Optional[float] = None

        files = self._all_log_files()
        for path in files:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            continue
                        et = obj.get("event_type")
                        sid = obj.get("signal_id")
                        src = obj.get("source") or "unknown"
                        if et:
                            per_event[et] += 1
                        if sid:
                            per_signal[sid] += 1
                        per_source[src] += 1
                        total += 1
                        ev_epoch = obj.get("ts_epoch")
                        if ev_epoch is None:
                            try:
                                ev_epoch = datetime.fromisoformat(
                                    obj.get("ts", "").replace("Z", "+00:00")
                                ).timestamp()
                            except Exception:
                                ev_epoch = None
                        if ev_epoch is not None:
                            if earliest is None or ev_epoch < earliest:
                                earliest = ev_epoch
                            if latest is None or ev_epoch > latest:
                                latest = ev_epoch
            except Exception as exc:
                log.warning("stats: could not read %s: %s", path, exc)
                continue

        pin = per_event.get("pin", 0)
        unpin = per_event.get("unpin", 0)
        dismiss = per_event.get("dismiss", 0)
        pin_dismiss_ratio = (pin / dismiss) if dismiss > 0 else (float("inf") if pin > 0 else 0.0)
        pin_unpin_ratio = (pin / unpin) if unpin > 0 else (float("inf") if pin > 0 else 0.0)

        return {
            "total_events": total,
            "per_event_type": dict(per_event),
            "per_source": dict(per_source),
            "top_signals": per_signal.most_common(10),
            "pin_dismiss_ratio": pin_dismiss_ratio if pin_dismiss_ratio != float("inf") else None,
            "pin_unpin_ratio": pin_unpin_ratio if pin_unpin_ratio != float("inf") else None,
            "earliest_ts": (
                datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat()
                if earliest is not None else None
            ),
            "latest_ts": (
                datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()
                if latest is not None else None
            ),
            "log_files": [p.name for p in files],
        }
