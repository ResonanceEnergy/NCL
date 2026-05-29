"""
NCL Unified Signal Processor
============================

Central hub for all signal routing. Every loop feeds signals through here.
The processor normalizes, ranks, deduplicates, and routes to all destinations:

  1. Prediction buffer  → Loop 2 (FuturePredictor)
  2. Memory store       → Long-term recall, council access
  3. Signals JSONL      → Disk persistence, brief generation input
  4. Working context    → Immediate operator visibility
  5. Push alerts        → iPhone/iPad notifications (hot signals only)

This replaces the inline routing that was previously duplicated across
Loop 1 (Scanner) and Loop 11 (Intel Collection).
"""

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles


log = logging.getLogger("ncl.signal_processor")


def _json_safe(obj: Any) -> Any:
    """JSON serialization fallback."""
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


# ── Importance thresholds ──────────────────────────────────
MEMORY_THRESHOLD = 50.0  # Store in long-term memory
WORKING_CONTEXT_THRESHOLD = 75.0  # Inject into working context
PUSH_ALERT_THRESHOLD = 80.0  # Push to iPhone
COUNCIL_FLAG_THRESHOLD = 85.0  # Flag for council consideration


class SignalProcessor:
    """
    Unified signal processor — the single funnel for all intelligence data.

    Accepts signals from any source (Scanner, Intel Engine, manual),
    normalizes them, ranks by importance, and routes to all consumers.
    """

    def __init__(
        self,
        memory_store: Any,
        working_context: Optional[Any] = None,
        signal_buffer: Optional[deque] = None,
        signal_lock: Optional[asyncio.Lock] = None,
        data_dir: Optional[Path] = None,
    ):
        self.memory_store = memory_store
        self.working_context = working_context
        self.signal_buffer = signal_buffer  # Shared with predictor loop
        self.signal_lock = signal_lock or asyncio.Lock()

        # Data directory for JSONL persistence
        self.data_dir = data_dir or Path(os.getenv("NCL_DATA", str(Path.home() / "NCL" / "data")))
        self.intel_dir = self.data_dir / "intelligence"
        self.intel_dir.mkdir(parents=True, exist_ok=True)
        self.signals_jsonl = self.intel_dir / "signals.jsonl"

        # Dedup: track signal fingerprints within a window
        self._recent_fingerprints: deque = deque(maxlen=2000)

        # Stats
        self._stats = {
            "total_processed": 0,
            "total_stored_memory": 0,
            "total_stored_jsonl": 0,
            "total_injected_wc": 0,
            "total_pushed_alerts": 0,
            "total_deduped": 0,
            "total_fed_predictor": 0,
            "by_source": {},
        }

    # ── PUBLIC API ──────────────────────────────────────────

    async def process_signals(
        self,
        signals: list[Any],
        source_label: str = "unknown",
        push_alerts: bool = True,
    ) -> dict:
        """
        Process a batch of signals from any source.

        Accepts both InsightSignal (scanner) and IntelSignal (collectors).
        Normalizes, deduplicates, ranks, and routes to all destinations.

        Args:
            signals: List of signal objects (InsightSignal or IntelSignal)
            source_label: Human-readable source (e.g. "scanner:x", "intel:crypto")
            push_alerts: Whether to send push notifications for hot signals

        Returns:
            Processing stats dict
        """
        if not signals:
            return {"processed": 0}

        now = datetime.now(timezone.utc)
        normalized = []

        # ── Phase 1: Normalize ──────────────────────────────
        for sig in signals:
            try:
                entry = self._normalize(sig, source_label, now)
                if entry:
                    normalized.append(entry)
            except Exception as e:
                log.debug(f"[PROCESSOR] Normalize failed for signal: {e}")

        if not normalized:
            return {"processed": 0, "all_failed_normalize": True}

        # ── Phase 2: Deduplicate ────────────────────────────
        unique = []
        for entry in normalized:
            fp = self._fingerprint(entry)
            if fp not in self._recent_fingerprints:
                self._recent_fingerprints.append(fp)
                unique.append(entry)
            else:
                self._stats["total_deduped"] += 1

        if not unique:
            return {"processed": len(normalized), "all_dupes": True}

        # ── Phase 3: Rank (sort by importance descending) ───
        unique.sort(key=lambda e: e["importance"], reverse=True)

        # ── Phase 4: Route to all destinations ──────────────
        results = {
            "processed": len(unique),
            "source": source_label,
        }

        # 4a. Prediction buffer — ALL signals (predictor needs volume)
        fed_predictor = await self._feed_predictor(unique)
        results["fed_predictor"] = fed_predictor

        # 4b. Memory store — signals above MEMORY_THRESHOLD
        stored_memory = await self._store_to_memory(unique)
        results["stored_memory"] = stored_memory

        # 4c. Signals JSONL — signals above MEMORY_THRESHOLD
        stored_jsonl = await self._persist_to_jsonl(unique)
        results["stored_jsonl"] = stored_jsonl

        # 4d. Working context — signals above WORKING_CONTEXT_THRESHOLD
        injected_wc = await self._inject_working_context(unique)
        results["injected_wc"] = injected_wc

        # 4e. Push alerts — signals above PUSH_ALERT_THRESHOLD
        pushed = 0
        if push_alerts:
            pushed = await self._push_alerts(unique)
        results["pushed_alerts"] = pushed

        # Update stats
        self._stats["total_processed"] += len(unique)
        src_key = source_label.split(":")[0] if ":" in source_label else source_label
        self._stats["by_source"][src_key] = self._stats["by_source"].get(src_key, 0) + len(unique)

        log.info(
            f"[PROCESSOR] {source_label}: {len(unique)} signals → "
            f"predictor={fed_predictor}, memory={stored_memory}, "
            f"jsonl={stored_jsonl}, wc={injected_wc}, alerts={pushed}"
        )

        return results

    def get_stats(self) -> dict:
        """Return processor statistics."""
        return {**self._stats}

    # ── NORMALIZATION ───────────────────────────────────────

    def _normalize(self, sig: Any, source_label: str, now: datetime) -> Optional[dict]:
        """
        Normalize any signal type into a common dict format.

        Handles:
        - InsightSignal (scanner) — has .importance_score as float attribute
        - IntelSignal (collectors) — has .importance_score() as method
        - Raw dicts — passed through with defaults
        """
        if isinstance(sig, dict):
            # Already a dict — ensure required fields
            return {
                "signal_id": sig.get("signal_id", ""),
                "source": sig.get("source", source_label),
                "title": sig.get("title", sig.get("content", "")[:120]),
                "content": sig.get("content", "")[:1000],
                "category": sig.get("category", ""),
                "importance": float(sig.get("importance", sig.get("importance_score", 50.0))),
                "confidence": float(sig.get("confidence", sig.get("relevance", 0.5))),
                "direction": sig.get("direction", "neutral"),
                "tags": list(sig.get("tags", []))[:15],
                "url": sig.get("url"),
                "timestamp": sig.get("timestamp", now.isoformat()),
                "metadata": sig.get("metadata", {}),
            }

        # Check for InsightSignal (scanner) — importance_score is a float attribute
        if hasattr(sig, "importance_score") and not callable(sig.importance_score):
            return {
                "signal_id": getattr(sig, "signal_id", ""),
                "source": f"scanner:{getattr(sig, 'source_platform', 'unknown')}",
                "title": getattr(sig, "content", "")[:120],
                "content": getattr(sig, "content", "")[:1000],
                "category": getattr(sig, "source_platform", ""),
                "importance": float(sig.importance_score),
                "confidence": float(getattr(sig, "relevance", 0.5)),
                "direction": getattr(sig, "trend", "neutral") or "neutral",
                "tags": list(getattr(sig, "tags", []))[:15],
                "url": getattr(sig, "url", None),
                "timestamp": getattr(sig, "timestamp", now).isoformat()
                if hasattr(getattr(sig, "timestamp", now), "isoformat")
                else str(getattr(sig, "timestamp", now)),
                "metadata": {},
            }

        # Check for IntelSignal (collectors) — importance_score() is a method
        if hasattr(sig, "importance_score") and callable(sig.importance_score):
            source_val = getattr(sig, "source", None)
            source_str = source_val.value if hasattr(source_val, "value") else str(source_val)
            direction_val = getattr(sig, "direction", None)
            direction_str = (
                direction_val.value if hasattr(direction_val, "value") else str(direction_val)
            )
            return {
                "signal_id": getattr(sig, "signal_id", ""),
                "source": f"intel:{source_str}",
                "title": getattr(sig, "title", "")[:120] or getattr(sig, "content", "")[:120],
                "content": getattr(sig, "content", "")[:1000],
                "category": getattr(sig, "category", source_str),
                "importance": float(sig.importance_score()),
                "confidence": float(getattr(sig, "confidence", 0.5)),
                "direction": direction_str,
                "tags": list(getattr(sig, "tags", []))[:15],
                "url": getattr(sig, "url", None),
                "timestamp": getattr(sig, "timestamp", now).isoformat()
                if hasattr(getattr(sig, "timestamp", now), "isoformat")
                else str(getattr(sig, "timestamp", now)),
                "metadata": getattr(sig, "metadata", {}),
            }

        # Unknown type — try best effort via model_dump or __dict__
        if hasattr(sig, "model_dump"):
            d = sig.model_dump()
            return self._normalize(d, source_label, now)

        log.warning(f"[PROCESSOR] Cannot normalize signal type: {type(sig)}")
        return None

    # ── DEDUPLICATION ───────────────────────────────────────

    def _fingerprint(self, entry: dict) -> str:
        """Generate a dedup fingerprint from source + content hash."""
        content = entry.get("content", "")[:200].lower().strip()
        source = entry.get("source", "")
        # Simple but effective: source + first 200 chars of content
        return f"{source}:{hash(content)}"

    # ── ROUTING DESTINATIONS ────────────────────────────────

    async def _feed_predictor(self, entries: list[dict]) -> int:
        """Feed all signals to the prediction buffer."""
        if not self.signal_buffer:
            return 0
        count = 0
        async with self.signal_lock:
            for entry in entries:
                self.signal_buffer.append(
                    {
                        "source": entry["source"],
                        "content": entry["content"][:500],
                        "importance": entry["importance"],
                        "tags": entry["tags"],
                        "timestamp": entry["timestamp"],
                    }
                )
                count += 1
        self._stats["total_fed_predictor"] += count
        return count

    async def _store_to_memory(self, entries: list[dict]) -> int:
        """Store high-importance signals in long-term memory."""
        count = 0
        for entry in entries:
            if entry["importance"] < MEMORY_THRESHOLD:
                continue
            try:
                await self.memory_store.create_unit(
                    content=entry["content"],
                    source=entry["source"],
                    importance=entry["importance"],
                    tags=entry["tags"] + ["intelligence_signal", "auto_processed"],
                )
                count += 1
            except Exception as e:
                log.warning(f"[PROCESSOR] Failed to store signal to memory: {e}")
        self._stats["total_stored_memory"] += count
        return count

    async def _rotate_if_needed(self) -> None:
        """Rename signals.jsonl → signals.{timestamp}.jsonl when it exceeds 50 MB."""
        _MAX_SIGNALS_FILE_BYTES = 50 * 1024 * 1024  # 50 MB  # noqa: N806
        try:
            if (
                self.signals_jsonl.exists()
                and self.signals_jsonl.stat().st_size > _MAX_SIGNALS_FILE_BYTES
            ):
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                rotated = self.signals_jsonl.with_name(f"signals.{stamp}.jsonl")
                self.signals_jsonl.rename(rotated)
                log.info(
                    f"[PROCESSOR] Rotated {self.signals_jsonl.name} → {rotated.name} (exceeded 50 MB)"  # noqa: E501
                )
        except Exception as e:
            log.warning(f"[PROCESSOR] File rotation failed for {self.signals_jsonl}: {e}")

    async def _persist_to_jsonl(self, entries: list[dict]) -> int:
        """Persist high-importance signals to JSONL file."""
        high = [e for e in entries if e["importance"] >= MEMORY_THRESHOLD]
        if not high:
            return 0
        try:
            async with aiofiles.open(self.signals_jsonl, "a") as f:
                for entry in high[:30]:  # Cap per batch
                    await f.write(json.dumps(entry, default=_json_safe) + "\n")
            self._stats["total_stored_jsonl"] += len(high[:30])
            await self._rotate_if_needed()
            return len(high[:30])
        except Exception as e:
            log.warning(f"[PROCESSOR] JSONL write failed: {e}")
            return 0

    async def _inject_working_context(self, entries: list[dict]) -> int:
        """Inject critical signals into working context for immediate visibility."""
        if not self.working_context:
            return 0
        critical = [e for e in entries if e["importance"] >= WORKING_CONTEXT_THRESHOLD]
        if not critical:
            return 0
        count = 0
        try:
            from ..memory.working_context import ContextItem

            for entry in critical[:5]:
                source_upper = entry["source"].split(":")[-1].upper()
                await self.working_context.add_item(
                    ContextItem(
                        item_id=f"processor:{entry['signal_id']}",
                        content=f"[{source_upper} HOT] {entry['title']}: {entry['content'][:300]}",
                        source=entry["source"],
                        category="hot_signal",
                        salience_score=0.0,
                        importance=entry["importance"],
                        recency_score=0.95,
                        relevance_score=0.0,
                        tags=entry["tags"] + ["hot_signal", "auto_processed"],
                        metadata={"signal_id": entry["signal_id"], "url": entry.get("url")},
                    )
                )
                count += 1
        except Exception as e:
            log.debug(f"[PROCESSOR] Working context injection failed: {e}")
        self._stats["total_injected_wc"] += count
        return count

    async def _push_alerts(self, entries: list[dict]) -> int:
        """Push high-importance signals to iPhone via Pushover."""
        hot = [e for e in entries if e["importance"] >= PUSH_ALERT_THRESHOLD]
        if not hot:
            return 0
        count = 0
        try:
            # Wave 14X-3 (2026-05-29): re-wired via the central AlertDispatcher
            # after strike_point_orchestrator was archived 2026-05-23. Push
            # alerts have been silently dead since the archive move.
            from ..notifications.alert_dispatch import enqueue_alert

            for entry in hot[:3]:  # Max 3 alerts per batch
                ticker = entry.get("ticker") or ""
                score = entry.get("score", entry.get("importance", 0))
                src = entry.get("source", "intel")
                content = (entry.get("content") or entry.get("title") or "")[:200]
                title = f"🔥 {ticker} hot signal" if ticker else "🔥 hot intel signal"
                body = f"{src} · score={score} · {content}"
                enqueue_alert(
                    title=title,
                    body=body,
                    priority="4",
                    tags="fire,chart_with_upwards_trend",
                    dedup_key=f"intel:{ticker}:{src}",
                    source="signal_processor",
                )
                count += 1
        except Exception as e:
            log.debug(f"[PROCESSOR] Push alert failed: {e}")
        self._stats["total_pushed_alerts"] += count
        return count
