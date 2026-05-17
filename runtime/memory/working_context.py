"""
Daily Working Context Window
============================

Curated, time-aware subset of memory that assembles itself each morning
and stays hot throughout the day.  Bridges the gap between raw memory
storage (JSONL) and actionable context for chat, councils, and intelligence.

Architecture (inspired by MemGPT / Letta three-tier model):
    Core Memory  → DailyContextWindow (this file) — always available
    Recall Memory → MemoryStore.search_units() — searchable history
    Archival Memory → ChromaDB vector store — cold semantic search

Salience formula:
    score = (α × recency) + (β × importance) + (γ × relevance)
    Default weights: α=0.3, β=0.4, γ=0.3

Lifecycle:
    6am  → assemble()  — query memory, council reports, active mandates
    all day → query via API, auto-prepended to chat context
    midnight → promote/demote — reinforced items boost, untouched decay
    next 6am → carry forward unresolved items
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.memory.working_context")

# ── Configuration ────────────────────────────────────────────────────

# Salience weights (must sum to 1.0)
ALPHA_RECENCY = 0.30
BETA_IMPORTANCE = 0.40
GAMMA_RELEVANCE = 0.30

# Assembly thresholds
MIN_DECAYED_IMPORTANCE = 30.0   # Minimum importance after decay to consider
MAX_CONTEXT_ITEMS = 50          # Maximum items in daily context
MIN_SALIENCE_SCORE = 0.25       # Floor for inclusion

# Carry-forward
CARRY_FORWARD_THRESHOLD = 0.40  # Items above this salience carry to next day
REINFORCE_BOOST = 1.15          # Importance multiplier for items accessed during the day
DEMOTE_PENALTY = 0.85           # Importance multiplier for items that went untouched

# File paths
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))


# ── Data Models ──────────────────────────────────────────────────────

@dataclass
class ContextItem:
    """A single item in the daily working context window."""
    item_id: str
    content: str
    source: str                         # e.g. "memory:unit_id", "council:youtube:session", "mandate:M-001"
    category: str                       # "memory", "council_report", "council_insight", "mandate", "signal", "pinned"
    salience_score: float               # Composite salience (0.0 - 1.0)
    importance: float                   # Raw importance from source
    recency_score: float                # Normalized recency (0.0 - 1.0)
    relevance_score: float              # Semantic relevance to today's themes (0.0 - 1.0)
    tags: list[str] = field(default_factory=list)
    pinned: bool = False                # Manually pinned by NATRIX
    accessed_today: bool = False        # Was this item accessed/referenced today?
    access_count: int = 0               # How many times accessed today
    created_at: str = ""                # ISO timestamp
    assembled_at: str = ""              # When this item entered today's context
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ContextItem:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DailyContext:
    """The full daily working context snapshot."""
    date: str                                       # ISO date (YYYY-MM-DD)
    assembled_at: str                               # ISO timestamp
    items: list[ContextItem] = field(default_factory=list)
    themes: list[str] = field(default_factory=list) # Today's extracted themes
    pinned_ids: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    carry_forward_from: str = ""                    # Previous day's date if any items carried

    def to_dict(self) -> dict:
        d = asdict(self)
        d["items"] = [item.to_dict() for item in self.items]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> DailyContext:
        items = [ContextItem.from_dict(i) for i in data.get("items", [])]
        return cls(
            date=data["date"],
            assembled_at=data.get("assembled_at", ""),
            items=items,
            themes=data.get("themes", []),
            pinned_ids=data.get("pinned_ids", []),
            stats=data.get("stats", {}),
            carry_forward_from=data.get("carry_forward_from", ""),
        )


# ── Core Engine ──────────────────────────────────────────────────────

class DailyContextWindow:
    """
    Manages the daily working context window for NCL Brain.

    Assembles a curated set of high-salience items each morning from:
    - Memory store (high-importance, recently reinforced units)
    - Council reports (last 24h insights and summaries)
    - Active mandates (in-progress work)
    - Intelligence signals (recent high-priority alerts)
    - Pinned items (manually kept by NATRIX)

    Provides a queryable context that can be prepended to LLM prompts,
    used by councils, or browsed via API.
    """

    def __init__(self, data_dir: str | Path, memory_store=None) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.context_dir = self.data_dir / "working_context"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir = self.context_dir / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)

        self.memory_store = memory_store  # MemoryStore instance
        self._current: Optional[DailyContext] = None
        self._lock = asyncio.Lock()

        # Load today's context if it exists
        self._load_today()

    def _today_file(self) -> Path:
        return self.context_dir / "today.json"

    def _history_file(self, date_str: str) -> Path:
        return self.history_dir / f"context-{date_str}.json"

    def _load_today(self) -> None:
        """Load today's context from disk if it exists and is for today."""
        today_file = self._today_file()
        if not today_file.exists():
            return
        try:
            data = json.loads(today_file.read_text(encoding="utf-8"))
            ctx = DailyContext.from_dict(data)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if ctx.date == today_str:
                self._current = ctx
                log.info(f"[WORKING-CTX] Loaded today's context: {len(ctx.items)} items")
            else:
                log.info(f"[WORKING-CTX] Stale context from {ctx.date}, will reassemble")
        except Exception as e:
            log.warning(f"[WORKING-CTX] Failed to load today.json: {e}")

    def _persist(self) -> None:
        """Save current context to disk atomically."""
        if not self._current:
            return
        try:
            data = self._current.to_dict()
            tmp = self._today_file().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(str(tmp), str(self._today_file()))
        except Exception as e:
            log.error(f"[WORKING-CTX] Failed to persist: {e}")

    def _archive_to_history(self, ctx: DailyContext) -> None:
        """Archive a day's context to history."""
        try:
            path = self._history_file(ctx.date)
            path.write_text(json.dumps(ctx.to_dict(), indent=2, default=str), encoding="utf-8")
            log.info(f"[WORKING-CTX] Archived context for {ctx.date}")
        except Exception as e:
            log.warning(f"[WORKING-CTX] Failed to archive: {e}")

    # ── Salience Scoring ─────────────────────────────────────────────

    @staticmethod
    def compute_recency(last_accessed: datetime, decay_rate: float = 0.95) -> float:
        """
        Compute recency score (0.0 - 1.0).
        Uses exponential decay: score = decay_rate ^ days_since_access.
        """
        days_since = max(0.0, (datetime.now(timezone.utc) - last_accessed).total_seconds() / 86400)
        return max(0.0, decay_rate ** days_since)

    @staticmethod
    def compute_importance_normalized(importance: float) -> float:
        """Normalize importance (0-100) to (0.0 - 1.0)."""
        return max(0.0, min(1.0, importance / 100.0))

    @staticmethod
    def compute_relevance(content: str, themes: list[str]) -> float:
        """
        Compute relevance of content to today's themes using keyword overlap.
        Returns 0.0 - 1.0.

        For production, this could use vector similarity via ChromaDB,
        but keyword overlap is fast and works well for the daily assembly.
        """
        if not themes:
            return 0.5  # Neutral when no themes are set

        content_lower = content.lower()
        content_tokens = set(re.findall(r'[a-z0-9_-]{3,}', content_lower))

        if not content_tokens:
            return 0.0

        theme_tokens: set[str] = set()
        for theme in themes:
            theme_tokens.update(re.findall(r'[a-z0-9_-]{3,}', theme.lower()))

        if not theme_tokens:
            return 0.5

        overlap = content_tokens & theme_tokens
        # Jaccard-like score biased toward theme coverage
        theme_coverage = len(overlap) / max(len(theme_tokens), 1)
        content_density = len(overlap) / max(len(content_tokens), 1)

        # Weighted blend: theme coverage matters more
        return min(1.0, 0.7 * theme_coverage + 0.3 * content_density)

    def compute_salience(
        self,
        recency: float,
        importance: float,
        relevance: float,
    ) -> float:
        """
        Compute composite salience score.
        salience = (α × recency) + (β × importance) + (γ × relevance)
        """
        return (
            ALPHA_RECENCY * recency +
            BETA_IMPORTANCE * importance +
            GAMMA_RELEVANCE * relevance
        )

    # ── Assembly ─────────────────────────────────────────────────────

    async def assemble(self, themes: Optional[list[str]] = None) -> DailyContext:
        """
        Assemble today's working context window.

        Pulls from memory store, council reports, signals, and active mandates.
        Scores each candidate by salience and selects the top N items.

        Args:
            themes: Optional list of today's key themes/topics for relevance scoring.
                    If None, themes are auto-extracted from recent high-importance items.

        Returns:
            Assembled DailyContext
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")

            # Archive yesterday's context if it exists
            if self._current and self._current.date != today_str:
                self._archive_to_history(self._current)

            log.info(f"[WORKING-CTX] Assembling context for {today_str}...")

            candidates: list[ContextItem] = []

            # 1. Pull from memory store
            memory_items = await self._pull_from_memory(themes or [])
            candidates.extend(memory_items)
            log.info(f"[WORKING-CTX]   Memory: {len(memory_items)} candidates")

            # 2. Pull from recent council reports
            council_items = await self._pull_from_councils()
            candidates.extend(council_items)
            log.info(f"[WORKING-CTX]   Council reports: {len(council_items)} candidates")

            # 3. Pull from intelligence signals
            signal_items = await self._pull_from_signals()
            candidates.extend(signal_items)
            log.info(f"[WORKING-CTX]   Signals: {len(signal_items)} candidates")

            # 4. Pull from active mandates
            mandate_items = await self._pull_from_mandates()
            candidates.extend(mandate_items)
            log.info(f"[WORKING-CTX]   Mandates: {len(mandate_items)} candidates")

            # 5. Carry forward pinned items from yesterday
            carried = self._carry_forward_pinned(today_str)
            candidates.extend(carried)
            log.info(f"[WORKING-CTX]   Carried forward: {len(carried)} items")

            # Auto-extract themes if not provided
            if not themes:
                themes = self._extract_themes(candidates)

            # Re-score with themes for relevance
            for item in candidates:
                item.relevance_score = self.compute_relevance(item.content, themes)
                item.salience_score = self.compute_salience(
                    item.recency_score,
                    self.compute_importance_normalized(item.importance),
                    item.relevance_score,
                )

            # Sort by salience, pinned items always on top
            candidates.sort(key=lambda x: (x.pinned, x.salience_score), reverse=True)

            # Select top N above threshold
            selected = []
            for item in candidates:
                if len(selected) >= MAX_CONTEXT_ITEMS:
                    break
                if item.salience_score >= MIN_SALIENCE_SCORE or item.pinned:
                    item.assembled_at = now.isoformat()
                    selected.append(item)

            # Deduplicate by item_id (keep highest salience)
            seen_ids: set[str] = set()
            deduped = []
            for item in selected:
                if item.item_id not in seen_ids:
                    seen_ids.add(item.item_id)
                    deduped.append(item)

            # Build context
            self._current = DailyContext(
                date=today_str,
                assembled_at=now.isoformat(),
                items=deduped,
                themes=themes,
                pinned_ids=[i.item_id for i in deduped if i.pinned],
                stats={
                    "total_candidates": len(candidates),
                    "selected": len(deduped),
                    "memory_items": len(memory_items),
                    "council_items": len(council_items),
                    "signal_items": len(signal_items),
                    "mandate_items": len(mandate_items),
                    "carried_forward": len(carried),
                    "avg_salience": round(
                        sum(i.salience_score for i in deduped) / max(len(deduped), 1), 3
                    ),
                    "themes_count": len(themes),
                },
                carry_forward_from=self._current.date if self._current and carried else "",
            )

            self._persist()

            log.info(
                f"[WORKING-CTX] Assembled: {len(deduped)} items "
                f"(avg salience: {self._current.stats['avg_salience']:.3f}, "
                f"themes: {len(themes)})"
            )

            return self._current

    async def _pull_from_memory(self, themes: list[str]) -> list[ContextItem]:
        """Pull high-salience memory units."""
        items: list[ContextItem] = []
        if not self.memory_store:
            return items

        try:
            # Get recent high-importance units (last 7 days, importance >= threshold)
            units = await self.memory_store.search_units(
                importance_threshold=MIN_DECAYED_IMPORTANCE,
                days_back=7,
            )

            for unit in units[:100]:  # Cap candidates
                recency = self.compute_recency(unit.last_accessed, unit.decay_rate)
                importance_norm = self.compute_importance_normalized(unit.importance)
                relevance = self.compute_relevance(unit.content, themes)
                salience = self.compute_salience(recency, importance_norm, relevance)

                items.append(ContextItem(
                    item_id=f"mem:{unit.unit_id}",
                    content=unit.content[:500],
                    source=unit.source,
                    category="memory",
                    salience_score=salience,
                    importance=unit.importance,
                    recency_score=recency,
                    relevance_score=relevance,
                    tags=unit.tags,
                    created_at=unit.created_at.isoformat(),
                    metadata={
                        "unit_id": unit.unit_id,
                        "reinforcement_count": unit.reinforcement_count,
                        "decay_rate": unit.decay_rate,
                    },
                ))
        except Exception as e:
            log.warning(f"[WORKING-CTX] Memory pull failed: {e}")

        return items

    async def _pull_from_councils(self) -> list[ContextItem]:
        """Pull insights from last 24h council reports."""
        items: list[ContextItem] = []
        reports_dir = NCL_BASE / "intelligence-scan" / "council-reports"
        if not reports_dir.exists():
            return items

        try:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=48)  # Look back 48h for council reports

            for json_file in sorted(reports_dir.glob("*.json"), reverse=True)[:10]:
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    # Parse timestamp from report
                    ts_str = data.get("timestamp", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts < cutoff:
                                continue
                        except (ValueError, TypeError):
                            pass

                    session_id = data.get("session_id", json_file.stem)
                    council_type = data.get("council_type", "unknown")

                    # Add report summary as a context item
                    summary = data.get("summary", "")
                    if summary:
                        recency = self.compute_recency(
                            datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else now
                        )
                        items.append(ContextItem(
                            item_id=f"council:{council_type}:{session_id}",
                            content=summary[:500],
                            source=f"council:{council_type}",
                            category="council_report",
                            salience_score=0.0,  # Will be rescored
                            importance=80.0,
                            recency_score=recency,
                            relevance_score=0.0,
                            tags=[council_type, "council_report"],
                            created_at=ts_str,
                            metadata={"file": json_file.name, "session_id": session_id},
                        ))

                    # Add individual insights
                    for insight in data.get("insights", [])[:5]:
                        title = insight.get("title", "")
                        desc = insight.get("description", "")
                        confidence = insight.get("confidence", 0.5)
                        if not title:
                            continue
                        items.append(ContextItem(
                            item_id=f"insight:{council_type}:{session_id}:{title[:30]}",
                            content=f"[{insight.get('category', '')}] {title}: {desc[:300]}",
                            source=f"council:{council_type}:insight",
                            category="council_insight",
                            salience_score=0.0,
                            importance=confidence * 100,
                            recency_score=recency if ts_str else 0.5,
                            relevance_score=0.0,
                            tags=insight.get("tags", []) + [council_type],
                            created_at=ts_str,
                            metadata={
                                "confidence": confidence,
                                "actionable": insight.get("actionable", False),
                                "action_suggestion": insight.get("action_suggestion", ""),
                            },
                        ))

                except (json.JSONDecodeError, KeyError) as e:
                    log.debug(f"[WORKING-CTX] Skipped council file {json_file.name}: {e}")
                    continue
        except Exception as e:
            log.warning(f"[WORKING-CTX] Council pull failed: {e}")

        return items

    async def _pull_from_signals(self) -> list[ContextItem]:
        """Pull from multiple intelligence sources:
        1. High-severity alerts from last 24h
        2. Latest intelligence brief top signals
        3. Morning brief topics
        """
        items: list[ContextItem] = []
        now = datetime.now(timezone.utc)

        # --- 1. Alert files (existing behavior) ---
        alerts_dir = NCL_BASE / "intelligence-scan" / "alerts"
        if alerts_dir.exists():
            try:
                cutoff = now - timedelta(hours=24)
                for alert_file in sorted(alerts_dir.glob("alert-*.json"), reverse=True)[:20]:
                    try:
                        data = json.loads(alert_file.read_text(encoding="utf-8"))
                        created_str = data.get("created_at", "")
                        if created_str:
                            try:
                                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                                if created < cutoff:
                                    continue
                            except (ValueError, TypeError):
                                pass

                        severity = data.get("severity", "MEDIUM")
                        importance = 90.0 if severity == "HIGH" else 70.0

                        items.append(ContextItem(
                            item_id=f"alert:{data.get('alert_id', alert_file.stem)}",
                            content=f"[{severity}] {data.get('title', '')}: {data.get('summary', '')[:300]}",
                            source=f"alert:{data.get('source', 'unknown')}",
                            category="signal",
                            salience_score=0.0,
                            importance=importance,
                            recency_score=0.9,
                            relevance_score=0.0,
                            tags=[severity.lower(), data.get("category", "")],
                            created_at=created_str,
                            metadata={
                                "severity": severity,
                                "recommended_action": data.get("recommended_action", ""),
                                "acknowledged": data.get("acknowledged", False),
                            },
                        ))
                    except (json.JSONDecodeError, KeyError):
                        continue
            except Exception as e:
                log.warning(f"[WORKING-CTX] Alert pull failed: {e}")

        # --- 2. Latest intelligence brief (top signals → working context) ---
        briefs_dir = self.data_dir / "intelligence"
        briefs_file = briefs_dir / "briefs.jsonl"
        if briefs_file.exists():
            try:
                # Read the last brief from JSONL (last non-empty line)
                lines = briefs_file.read_text(encoding="utf-8").strip().splitlines()
                if lines:
                    latest_brief = json.loads(lines[-1])
                    brief_ts = latest_brief.get("timestamp", now.isoformat())
                    try:
                        brief_dt = datetime.fromisoformat(brief_ts.replace("Z", "+00:00"))
                        # Only include if from last 12 hours
                        if (now - brief_dt).total_seconds() > 43200:
                            latest_brief = None
                    except (ValueError, TypeError):
                        pass

                    if latest_brief:
                        # Executive summary as context item
                        exec_summary = latest_brief.get("executive_summary", "")
                        if exec_summary:
                            items.append(ContextItem(
                                item_id=f"brief:{latest_brief.get('brief_id', 'latest')}",
                                content=f"[INTEL BRIEF] {exec_summary[:500]}",
                                source="intelligence:brief",
                                category="intelligence_brief",
                                salience_score=0.0,
                                importance=85.0,
                                recency_score=0.95,
                                relevance_score=0.0,
                                tags=["intelligence", "brief", latest_brief.get("brief_type", "daily")],
                                created_at=brief_ts,
                                metadata={"brief_id": latest_brief.get("brief_id", "")},
                            ))

                        # Top signals from the brief
                        for sig in latest_brief.get("top_signals", [])[:8]:
                            sig_title = sig.get("title", "")
                            sig_content = sig.get("content", "")
                            if not sig_title:
                                continue
                            sig_source = sig.get("source", "unknown")
                            sig_importance = sig.get("confidence", 0.7) * 100
                            items.append(ContextItem(
                                item_id=f"signal:{sig.get('signal_id', sig_title[:30])}",
                                content=f"[{sig_source.upper()}] {sig_title}: {sig_content[:200]}",
                                source=f"intelligence:{sig_source}",
                                category="intelligence_signal",
                                salience_score=0.0,
                                importance=sig_importance,
                                recency_score=0.85,
                                relevance_score=0.0,
                                tags=sig.get("tags", []) + ["intelligence_signal"],
                                created_at=brief_ts,
                                metadata={
                                    "direction": sig.get("direction", ""),
                                    "change_pct": sig.get("change_pct"),
                                    "signal_id": sig.get("signal_id", ""),
                                },
                            ))
            except Exception as e:
                log.warning(f"[WORKING-CTX] Intelligence brief pull failed: {e}")

        # --- 3. Morning brief topics (today's research agenda) ---
        morning_dir = self.data_dir / "morning_briefs"
        today_str = now.strftime("%Y-%m-%d")
        morning_file = morning_dir / f"morning-{today_str}.json"
        if morning_file.exists():
            try:
                mb = json.loads(morning_file.read_text(encoding="utf-8"))
                topics = mb.get("topics", [])
                for i, topic in enumerate(topics[:5]):
                    topic_text = topic if isinstance(topic, str) else topic.get("title", str(topic))
                    items.append(ContextItem(
                        item_id=f"morning_topic:{today_str}:{i}",
                        content=f"[MORNING BRIEF] Research topic: {topic_text[:300]}",
                        source="intelligence:morning_brief",
                        category="morning_brief",
                        salience_score=0.0,
                        importance=75.0,
                        recency_score=0.9,
                        relevance_score=0.0,
                        tags=["morning_brief", "research_topic"],
                        created_at=mb.get("generated_at", today_str),
                        metadata={"status": mb.get("status", "pending")},
                    ))
            except Exception as e:
                log.warning(f"[WORKING-CTX] Morning brief pull failed: {e}")

        return items

    async def _pull_from_mandates(self) -> list[ContextItem]:
        """Pull active (in-progress) mandates."""
        items: list[ContextItem] = []
        mandates_file = self.data_dir / "mandates.json"
        if not mandates_file.exists():
            return items

        try:
            data = json.loads(mandates_file.read_text(encoding="utf-8"))
            mandates = data if isinstance(data, list) else data.get("mandates", [])

            for m in mandates:
                status = m.get("status", "")
                if status not in ("in_progress", "pending", "approved"):
                    continue

                items.append(ContextItem(
                    item_id=f"mandate:{m.get('mandate_id', 'unknown')}",
                    content=f"[Mandate {m.get('mandate_id', '')}] {m.get('title', '')}: {m.get('description', '')[:300]}",
                    source="mandate",
                    category="mandate",
                    salience_score=0.0,
                    importance=75.0 if status == "in_progress" else 60.0,
                    recency_score=0.7,
                    relevance_score=0.0,
                    tags=m.get("tags", []) + [status],
                    created_at=m.get("created_at", ""),
                    metadata={
                        "status": status,
                        "pillar": m.get("pillar", ""),
                        "priority": m.get("priority", ""),
                    },
                ))
        except Exception as e:
            log.warning(f"[WORKING-CTX] Mandate pull failed: {e}")

        return items

    def _carry_forward_pinned(self, today_str: str) -> list[ContextItem]:
        """Carry forward pinned items and high-salience items from yesterday."""
        carried: list[ContextItem] = []
        if not self._current or self._current.date == today_str:
            return carried

        for item in self._current.items:
            if item.pinned or item.salience_score >= CARRY_FORWARD_THRESHOLD:
                # Reset daily tracking
                item.accessed_today = False
                item.access_count = 0
                item.assembled_at = ""
                carried.append(item)

        return carried

    def _extract_themes(self, candidates: list[ContextItem]) -> list[str]:
        """Auto-extract today's themes from high-importance candidates."""
        # Collect all tags weighted by importance
        tag_scores: dict[str, float] = defaultdict(float)
        for item in candidates:
            weight = item.importance / 100.0
            for tag in item.tags:
                if tag and len(tag) > 2 and tag not in (
                    "auto_ingested", "autonomous", "intelligence_signal",
                    "council_report", "council_insight", "high", "medium",
                ):
                    tag_scores[tag] += weight

        # Top tags become themes
        sorted_tags = sorted(tag_scores.items(), key=lambda x: -x[1])
        return [tag for tag, _ in sorted_tags[:15]]

    # ── Public API ───────────────────────────────────────────────────

    def get_current(self) -> Optional[DailyContext]:
        """Get today's working context."""
        return self._current

    def get_context_text(self, max_items: int = 20) -> str:
        """
        Get a text summary of the working context for LLM prompt injection.

        Returns a formatted string suitable for prepending to system prompts
        or chat context.
        """
        if not self._current or not self._current.items:
            return ""

        lines = [
            f"=== DAILY WORKING CONTEXT ({self._current.date}) ===",
            f"Themes: {', '.join(self._current.themes[:10])}",
            "",
        ]

        for i, item in enumerate(self._current.items[:max_items], 1):
            pin_marker = " [PINNED]" if item.pinned else ""
            lines.append(
                f"{i}. [{item.category}] (salience: {item.salience_score:.2f}){pin_marker}"
            )
            lines.append(f"   {item.content[:200]}")
            if item.tags:
                lines.append(f"   Tags: {', '.join(item.tags[:5])}")
            lines.append("")

        lines.append(f"=== {len(self._current.items)} items total ===")
        return "\n".join(lines)

    async def pin_item(self, item_id: str) -> bool:
        """Pin an item to keep it in working context."""
        async with self._lock:
            if not self._current:
                return False
            for item in self._current.items:
                if item.item_id == item_id:
                    item.pinned = True
                    if item_id not in self._current.pinned_ids:
                        self._current.pinned_ids.append(item_id)
                    self._persist()
                    log.info(f"[WORKING-CTX] Pinned: {item_id}")
                    return True
            return False

    async def unpin_item(self, item_id: str) -> bool:
        """Unpin an item from working context."""
        async with self._lock:
            if not self._current:
                return False
            for item in self._current.items:
                if item.item_id == item_id:
                    item.pinned = False
                    self._current.pinned_ids = [
                        pid for pid in self._current.pinned_ids if pid != item_id
                    ]
                    self._persist()
                    log.info(f"[WORKING-CTX] Unpinned: {item_id}")
                    return True
            return False

    async def mark_accessed(self, item_id: str) -> None:
        """Mark an item as accessed (reinforces it for EOD promote/demote)."""
        async with self._lock:
            if not self._current:
                return
            for item in self._current.items:
                if item.item_id == item_id:
                    item.accessed_today = True
                    item.access_count += 1
                    self._persist()
                    return

    async def add_item(self, item: ContextItem) -> None:
        """Manually add an item to today's context (e.g., from chat or command)."""
        async with self._lock:
            if not self._current:
                now = datetime.now(timezone.utc)
                self._current = DailyContext(
                    date=now.strftime("%Y-%m-%d"),
                    assembled_at=now.isoformat(),
                )

            # Check for duplicate
            if any(i.item_id == item.item_id for i in self._current.items):
                return

            item.assembled_at = datetime.now(timezone.utc).isoformat()
            self._current.items.append(item)
            self._persist()
            log.info(f"[WORKING-CTX] Added item: {item.item_id}")

    async def refresh(self, themes: Optional[list[str]] = None) -> DailyContext:
        """
        Mid-day refresh — re-score existing items and pull any new
        high-priority items that arrived since morning assembly.
        """
        return await self.assemble(themes=themes)

    async def end_of_day(self) -> dict:
        """
        End-of-day promote/demote cycle.

        - Items accessed today get importance boost in memory store
        - Items not accessed get importance penalty
        - High-salience items carry forward to tomorrow
        - Context is archived to history

        Returns:
            Stats dict with promote/demote counts
        """
        async with self._lock:
            if not self._current:
                return {"status": "no_context"}

            promoted = 0
            demoted = 0

            for item in self._current.items:
                if not self.memory_store:
                    break
                # Only promote/demote memory-backed items
                if not item.item_id.startswith("mem:"):
                    continue

                unit_id = item.item_id.replace("mem:", "")

                try:
                    unit = await self.memory_store.get_unit(unit_id)
                    if not unit:
                        continue

                    if item.accessed_today:
                        # Boost importance (reinforcement already happens in get_unit)
                        unit.importance = min(100.0, unit.importance * REINFORCE_BOOST)
                        promoted += 1
                        log.debug(f"[WORKING-CTX] Promoted: {unit_id} → {unit.importance:.1f}")
                    else:
                        # Demote untouched items
                        unit.importance = max(0.0, unit.importance * DEMOTE_PENALTY)
                        demoted += 1
                        log.debug(f"[WORKING-CTX] Demoted: {unit_id} → {unit.importance:.1f}")
                except Exception as e:
                    log.warning(f"[WORKING-CTX] Promote/demote failed for {unit_id}: {e}")

            stats = {
                "date": self._current.date,
                "total_items": len(self._current.items),
                "promoted": promoted,
                "demoted": demoted,
                "pinned": len(self._current.pinned_ids),
                "accessed": sum(1 for i in self._current.items if i.accessed_today),
            }

            # Archive today's context
            self._archive_to_history(self._current)

            log.info(
                f"[WORKING-CTX] EOD: {promoted} promoted, {demoted} demoted, "
                f"{stats['pinned']} pinned carry forward"
            )

            return stats

    def get_history(self, days_back: int = 7) -> list[dict]:
        """Get working context history for the last N days."""
        history = []
        for hist_file in sorted(self.history_dir.glob("context-*.json"), reverse=True):
            if len(history) >= days_back:
                break
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                history.append({
                    "date": data.get("date", ""),
                    "item_count": len(data.get("items", [])),
                    "themes": data.get("themes", []),
                    "stats": data.get("stats", {}),
                })
            except Exception:
                continue
        return history

    def get_stats(self) -> dict:
        """Get working context statistics."""
        if not self._current:
            return {
                "status": "not_assembled",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }

        categories: dict[str, int] = defaultdict(int)
        for item in self._current.items:
            categories[item.category] += 1

        return {
            "status": "active",
            "date": self._current.date,
            "assembled_at": self._current.assembled_at,
            "total_items": len(self._current.items),
            "pinned_items": len(self._current.pinned_ids),
            "themes": self._current.themes,
            "categories": dict(categories),
            "avg_salience": round(
                sum(i.salience_score for i in self._current.items) / max(len(self._current.items), 1), 3
            ),
            "accessed_today": sum(1 for i in self._current.items if i.accessed_today),
            "assembly_stats": self._current.stats,
        }
