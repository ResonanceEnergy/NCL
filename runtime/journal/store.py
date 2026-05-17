"""
NCL Journal Store
=================

Append-only JSONL persistence for journal entries, reflections, tips,
and insights. Provides full-text search, tag filtering, date-range
queries, and memory/context bridge integration.

The journal is the operator's input channel into the brain's learning
loop — it captures decisions, observations, techniques, and questions
that shape what NCL pays attention to.
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import aiofiles

from .models import (
    JournalEntry,
    DailyReflection,
    JournalInsight,
    TipEntry,
    EntryType,
)

log = logging.getLogger("ncl.journal")

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB rotation threshold
_ROTATE_BACKUP_COUNT = 5


class JournalStore:
    """
    Persistent journal with search, analytics, and brain integration.

    Files:
        journal.jsonl      — all entries (append-only)
        reflections.jsonl  — daily reflections (one per day)
        tips.jsonl         — tips/tricks/techniques knowledge base
        insights.jsonl     — cross-entry pattern insights
    """

    def __init__(self, data_dir: str | Path, memory_store=None, working_context=None):
        self.data_dir = Path(data_dir).expanduser()
        self.journal_dir = self.data_dir / "journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        self.entries_file = self.journal_dir / "journal.jsonl"
        self.reflections_file = self.journal_dir / "reflections.jsonl"
        self.tips_file = self.journal_dir / "tips.jsonl"
        self.insights_file = self.journal_dir / "insights.jsonl"

        # Brain integration hooks
        self.memory_store = memory_store
        self.working_context = working_context

        # In-memory index (populated on first access)
        self._entries_cache: list[JournalEntry] | None = None
        self._tips_cache: list[TipEntry] | None = None
        self._lock = asyncio.Lock()

        # Stats
        self._stats = {
            "total_entries": 0,
            "total_reflections": 0,
            "total_tips": 0,
            "total_insights": 0,
            "entries_today": 0,
            "last_entry": None,
            "last_reflection": None,
        }

        log.info(f"Journal store initialized: {self.journal_dir}")

    # ─── HELPERS ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_entry_type(entry_type: str) -> EntryType:
        """Safely parse an entry_type string into an EntryType enum member."""
        try:
            return EntryType(entry_type)
        except ValueError:
            return EntryType.NOTE

    # ─── ENTRY OPERATIONS ─────────────────────────────────────────────

    async def create_entry(
        self,
        content: str,
        entry_type: str = "note",
        title: str = "",
        tags: list[str] | None = None,
        importance: float = 50.0,
        source_context: str = "manual",
        related_signals: list[str] | None = None,
        related_briefs: list[str] | None = None,
    ) -> JournalEntry:
        """Create and persist a new journal entry."""
        entry = JournalEntry(
            content=content[:50000],  # Cap at 50K chars
            entry_type=self._parse_entry_type(entry_type),
            title=title,
            tags=tags or [],
            importance=max(0.0, min(100.0, importance)),
            source_context=source_context,
            related_signals=related_signals or [],
            related_briefs=related_briefs or [],
        )

        # Persist
        await self._append_jsonl(self.entries_file, entry.model_dump(mode="json"))

        # Invalidate cache
        self._entries_cache = None

        # Update stats
        self._stats["total_entries"] += 1
        self._stats["entries_today"] += 1
        self._stats["last_entry"] = datetime.now(timezone.utc).isoformat()

        # Bridge to memory store — journal entries become long-term memory
        await self._bridge_to_memory(entry)

        # Inject into working context if high importance
        if entry.importance >= 60 and self.working_context:
            await self._inject_to_context(entry)

        log.info(f"Journal entry created: {entry.entry_id} ({entry.entry_type.value}) "
                 f"— {entry.word_count} words, importance={entry.importance}")

        return entry

    async def get_entry(self, entry_id: str) -> JournalEntry | None:
        """Retrieve a single entry by ID."""
        entries = await self._load_entries()
        for e in reversed(entries):  # Most recent first
            if e.entry_id == entry_id:
                return e
        return None

    async def get_entries(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        entry_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[JournalEntry]:
        """Query entries with optional date range, type, and tag filters."""
        entries = await self._load_entries()
        results = []

        for e in reversed(entries):  # Most recent first
            if date_from and e.timestamp.date() < date_from:
                continue
            if date_to and e.timestamp.date() > date_to:
                continue
            if entry_type and e.entry_type.value != entry_type:
                continue
            if tags and not any(t in e.tags for t in tags):
                continue
            results.append(e)
            if len(results) >= limit:
                break

        return results

    async def get_today_entries(self) -> list[JournalEntry]:
        """Get all entries from today."""
        today = datetime.now(timezone.utc).date()
        return await self.get_entries(date_from=today, date_to=today, limit=100)

    async def search(self, query: str, limit: int = 20) -> list[JournalEntry]:
        """Full-text search across entry titles and content."""
        entries = await self._load_entries()
        query_lower = query.lower()
        query_terms = query_lower.split()
        results = []

        for e in reversed(entries):
            text = f"{e.title} {e.content}".lower()
            # Score: how many query terms appear in the text
            score = sum(1 for term in query_terms if term in text)
            if score > 0:
                results.append((score, e))

        # Sort by match score (desc), then by timestamp (desc)
        results.sort(key=lambda x: (-x[0], -x[1].timestamp.timestamp()))
        return [e for _, e in results[:limit]]

    # ─── TIPS & TECHNIQUES ────────────────────────────────────────────

    async def create_tip(
        self,
        title: str,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        source: str = "",
    ) -> TipEntry:
        """Create a tip/trick/technique/best practice entry."""
        tip = TipEntry(
            title=title,
            content=content[:10000],
            category=category,
            tags=tags or [],
            source=source,
        )
        await self._append_jsonl(self.tips_file, tip.model_dump(mode="json"))
        self._tips_cache = None
        self._stats["total_tips"] += 1
        log.info(f"Tip created: {tip.tip_id} — {tip.title}")
        return tip

    async def get_tips(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[TipEntry]:
        """Query tips with optional filters."""
        tips = await self._load_tips()
        results = []

        for tip in reversed(tips):
            if category and tip.category != category:
                continue
            if tags and not any(t in tip.tags for t in tags):
                continue
            if query:
                text = f"{tip.title} {tip.content}".lower()
                if not any(term in text for term in query.lower().split()):
                    continue
            results.append(tip)
            if len(results) >= limit:
                break

        return results

    # ─── REFLECTIONS ──────────────────────────────────────────────────

    async def save_reflection(self, reflection: DailyReflection) -> None:
        """Persist a daily reflection."""
        await self._append_jsonl(
            self.reflections_file, reflection.model_dump(mode="json")
        )
        self._stats["total_reflections"] += 1
        self._stats["last_reflection"] = datetime.now(timezone.utc).isoformat()
        log.info(f"Daily reflection saved: {reflection.reflection_id} for {reflection.date}")

    async def get_reflection(self, target_date: str) -> DailyReflection | None:
        """Get the reflection for a specific date (YYYY-MM-DD)."""
        reflections = await self._load_jsonl(self.reflections_file)
        for r in reversed(reflections):
            if r.get("date") == target_date:
                return DailyReflection(**r)
        return None

    async def get_recent_reflections(self, days: int = 7) -> list[DailyReflection]:
        """Get reflections from the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        reflections = await self._load_jsonl(self.reflections_file)
        results = []
        for r in reversed(reflections):
            if r.get("timestamp", "") >= cutoff:
                results.append(DailyReflection(**r))
            if len(results) >= days:
                break
        return results

    # ─── INSIGHTS ─────────────────────────────────────────────────────

    async def save_insight(self, insight: JournalInsight) -> None:
        """Persist a cross-entry pattern insight."""
        await self._append_jsonl(
            self.insights_file, insight.model_dump(mode="json")
        )
        self._stats["total_insights"] += 1
        log.info(f"Insight saved: {insight.insight_id} — {insight.pattern[:80]}")

    async def get_insights(self, limit: int = 20) -> list[JournalInsight]:
        """Get recent insights, most recent first."""
        raw = await self._load_jsonl(self.insights_file)
        results = []
        for r in reversed(raw):
            results.append(JournalInsight(**r))
            if len(results) >= limit:
                break
        return results

    # ─── ANALYTICS ────────────────────────────────────────────────────

    async def get_analytics(self, days: int = 30) -> dict:
        """Journal analytics — entry frequency, topic distribution, streaks."""
        entries = await self._load_entries()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = [e for e in entries if e.timestamp >= cutoff]

        # Entry frequency by date
        daily_counts: dict[str, int] = defaultdict(int)
        type_counts: dict[str, int] = defaultdict(int)
        tag_counts: dict[str, int] = defaultdict(int)
        sector_counts: dict[str, int] = defaultdict(int)

        for e in recent:
            daily_counts[e.timestamp.strftime("%Y-%m-%d")] += 1
            type_counts[e.entry_type.value] += 1
            for t in e.tags:
                tag_counts[t] += 1
            for s in e.linked_sectors:
                sector_counts[s] += 1

        # Streak calculation
        today = datetime.now(timezone.utc).date()
        streak = 0
        check_date = today
        while check_date.isoformat() in daily_counts:
            streak += 1
            check_date -= timedelta(days=1)

        # Total words
        total_words = sum(e.word_count for e in recent)

        return {
            "period_days": days,
            "total_entries": len(recent),
            "total_words": total_words,
            "avg_words_per_entry": total_words // max(len(recent), 1),
            "current_streak_days": streak,
            "entries_by_date": dict(sorted(daily_counts.items())),
            "entries_by_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
            "top_tags": dict(sorted(tag_counts.items(), key=lambda x: -x[1])[:15]),
            "sectors_touched": dict(sorted(sector_counts.items(), key=lambda x: -x[1])),
            "avg_importance": sum(e.importance for e in recent) / max(len(recent), 1),
        }

    def get_stats(self) -> dict:
        """Quick stats for health/status endpoints."""
        return dict(self._stats)

    # ─── BRAIN INTEGRATION ────────────────────────────────────────────

    async def _bridge_to_memory(self, entry: JournalEntry) -> None:
        """Write journal entry to MemoryStore for long-term retrieval."""
        if self.memory_store is None:
            return
        try:
            tags = list(entry.tags)
            tags.append(f"journal_{entry.entry_type.value}")
            tags.append("journal")
            if entry.linked_sectors:
                tags.extend(entry.linked_sectors[:3])
            # Deduplicate
            tags = list(dict.fromkeys(tags))

            content = f"[Journal {entry.entry_type.value}] {entry.title}: {entry.content[:800]}"
            await self.memory_store.create_unit(
                content=content,
                source="journal",
                importance=entry.importance,
                tags=tags,
            )
        except Exception as e:
            log.warning(f"Failed to bridge journal entry to memory: {e}")

    async def _inject_to_context(self, entry: JournalEntry) -> None:
        """Inject high-importance journal entries into working context."""
        if self.working_context is None:
            return
        try:
            item = {
                "source": "journal",
                "type": entry.entry_type.value,
                "title": entry.title or entry.content[:80],
                "content": entry.content[:400],
                "importance": entry.importance,
                "tags": entry.tags[:5],
                "timestamp": entry.timestamp.isoformat(),
            }
            if hasattr(self.working_context, "inject_item"):
                await self.working_context.inject_item(item)
            elif hasattr(self.working_context, "_items"):
                self.working_context._items.append(item)
        except Exception as e:
            log.warning(f"Failed to inject journal entry to context: {e}")

    async def get_context_for_brief(self, days: int = 3) -> str:
        """Build journal context string for inclusion in intel briefs."""
        entries = await self.get_entries(
            date_from=(datetime.now(timezone.utc) - timedelta(days=days)).date(),
            limit=20,
        )
        if not entries:
            return ""

        parts = [f"OPERATOR JOURNAL (last {days} days, {len(entries)} entries):"]
        for e in entries[:10]:
            parts.append(
                f"- [{e.entry_type.value}] {e.title}: "
                f"{e.content[:200]}{'...' if len(e.content) > 200 else ''}"
            )

        # Add open questions from latest reflection
        reflection = await self.get_reflection(
            datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        if reflection and reflection.open_questions:
            parts.append("\nOPEN QUESTIONS:")
            for q in reflection.open_questions[:5]:
                parts.append(f"  ? {q}")

        return "\n".join(parts)

    # ─── FILE I/O ─────────────────────────────────────────────────────

    async def _append_jsonl(self, path: Path, data: dict) -> None:
        """Append a JSON line to file, rotating if needed."""
        async with self._lock:
            await self._rotate_if_needed(path)
            async with aiofiles.open(path, "a") as f:
                await f.write(json.dumps(data, default=str) + "\n")
                await f.flush()
                os.fsync(f.fileno())

    async def _load_jsonl(self, path: Path) -> list[dict]:
        """Load all records from a JSONL file."""
        if not path.exists():
            return []
        records = []
        try:
            async with aiofiles.open(path, "r") as f:
                async for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            log.warning(f"Failed to load {path.name}: {e}")
        return records

    async def _load_entries(self) -> list[JournalEntry]:
        """Load and cache all journal entries."""
        if self._entries_cache is not None:
            return self._entries_cache
        raw = await self._load_jsonl(self.entries_file)
        entries = []
        for r in raw:
            try:
                entries.append(JournalEntry(**r))
            except Exception:
                continue
        self._entries_cache = entries
        self._stats["total_entries"] = len(entries)
        return entries

    async def _load_tips(self) -> list[TipEntry]:
        """Load and cache all tips."""
        if self._tips_cache is not None:
            return self._tips_cache
        raw = await self._load_jsonl(self.tips_file)
        tips = []
        for r in raw:
            try:
                tips.append(TipEntry(**r))
            except Exception:
                continue
        self._tips_cache = tips
        self._stats["total_tips"] = len(tips)
        return tips

    async def _rotate_if_needed(self, path: Path) -> None:
        """Rotate file if it exceeds size threshold.

        Shifts backup chain: path → .1.jsonl → .2.jsonl → ... → ._ROTATE_BACKUP_COUNT.jsonl
        The oldest backup is deleted. The current file is renamed to .1.jsonl
        so the caller can start fresh by appending to ``path``.
        """
        if not path.exists():
            return
        try:
            size = path.stat().st_size
            if size < _MAX_FILE_BYTES:
                return

            # Delete the oldest backup if it exists
            oldest = path.with_suffix(f".{_ROTATE_BACKUP_COUNT}.jsonl")
            if oldest.exists():
                oldest.unlink()

            # Shift existing backups: .4 → .5, .3 → .4, ... , .1 → .2
            for i in range(_ROTATE_BACKUP_COUNT - 1, 0, -1):
                src = path.with_suffix(f".{i}.jsonl")
                dst = path.with_suffix(f".{i + 1}.jsonl")
                if src.exists():
                    src.rename(dst)

            # Rename current file to .1.jsonl
            path.rename(path.with_suffix(".1.jsonl"))

            log.info(f"Rotated {path.name} ({size / 1024 / 1024:.1f} MB)")
        except Exception as e:
            log.warning(f"Journal file rotation failed: {e}")
