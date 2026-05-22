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

from .authority import (
    AuthorityTier,
    authority_weight,
    tier_for_source,
)

log = logging.getLogger("ncl.memory.working_context")

# ── Configuration ────────────────────────────────────────────────────

# Salience weights — applied to the unweighted (recency, importance, relevance)
# portion of the score. They sum to 0.85 because the remaining 0.15 of the
# composite is reserved for the authority floor; see compute_salience().
ALPHA_RECENCY = 0.25
BETA_IMPORTANCE = 0.35
GAMMA_RELEVANCE = 0.25

# Authority floor: a fraction of the authority weight is added unconditionally
# so a NATRIX directive (weight ~1.0) with poor recency/importance/relevance
# still floats above a scanner item (weight ~0.2) with peak ranking signals.
# Eg: scanner item peak = (0.25+0.35+0.25) * 0.2 + 0.15*0.2 = 0.17 + 0.03 = 0.20
#      NATRIX dud      = (0.25+0.35+0.25) * 1.0 * 0.1 + 0.15*1.0 = 0.085 + 0.15 = 0.235
# So NATRIX wins even on a bad day. Tune AUTHORITY_FLOOR_WEIGHT if scanners
# need more headroom.
AUTHORITY_FLOOR_WEIGHT = 0.15

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
    def _keyword_relevance(content: str, themes: list[str]) -> float:
        """
        Compute relevance via keyword overlap (fast fallback).
        Returns 0.0 - 1.0.
        """
        if not themes:
            return 0.5

        content_tokens = set(re.findall(r'[a-z0-9_-]{3,}', content.lower()))
        if not content_tokens:
            return 0.0

        theme_tokens: set[str] = set()
        for theme in themes:
            theme_tokens.update(re.findall(r'[a-z0-9_-]{3,}', theme.lower()))

        if not theme_tokens:
            return 0.5

        overlap = content_tokens & theme_tokens
        theme_coverage = len(overlap) / max(len(theme_tokens), 1)
        content_density = len(overlap) / max(len(content_tokens), 1)
        return min(1.0, 0.7 * theme_coverage + 0.3 * content_density)

    def compute_relevance(self, content: str, themes: list[str]) -> float:
        """
        Compute relevance of content to today's themes.

        Hybrid approach:
        1. Try ChromaDB vector similarity if memory_store has it (semantic match)
        2. Always run keyword overlap (exact match)
        3. Blend: 60% vector + 40% keyword when vector available, else 100% keyword
        """
        keyword_score = self._keyword_relevance(content, themes)

        # Try vector similarity via ChromaDB
        vector_score = None
        if self.memory_store and hasattr(self.memory_store, '_init_vector_db'):
            try:
                if self.memory_store._init_vector_db():
                    import asyncio
                    # Build a theme query string for vector search
                    theme_query = " ".join(themes[:10])
                    if theme_query:
                        collection = self.memory_store._chroma_collections.get("default")
                        if collection:
                            # Query with content as document, see how close it is to theme query
                            # ChromaDB doesn't support direct similarity scoring between two texts,
                            # so we search for content in the collection and check distance
                            try:
                                results = collection.query(
                                    query_texts=[theme_query],
                                    n_results=50,
                                    include=["documents", "distances"],
                                )
                                if results and results.get("documents") and results["documents"][0]:
                                    # Check if this content appears in results (approximate match)
                                    content_prefix = content[:200].lower().strip()
                                    distances = results.get("distances", [[]])[0]
                                    documents = results["documents"][0]
                                    for doc, dist in zip(documents, distances):
                                        if doc and content_prefix[:80] in doc.lower()[:200]:
                                            # Cosine distance → similarity: 0 = identical, 2 = opposite
                                            vector_score = max(0.0, 1.0 - dist)
                                            break
                            except Exception:
                                pass  # Fall through to keyword-only
            except Exception:
                pass

        if vector_score is not None:
            # Blend: 60% vector + 40% keyword
            return min(1.0, 0.6 * vector_score + 0.4 * keyword_score)
        return keyword_score

    def compute_salience(
        self,
        recency: float,
        importance: float,
        relevance: float,
        authority_weight: float = 1.0,
    ) -> float:
        """Compute composite salience with authority weighting.

        Formula:
            base     = α·recency + β·importance + γ·relevance       # in [0, α+β+γ]
            salience = base * authority_weight + FLOOR * authority_weight

        The first term scales the recency/importance/relevance subscore by
        provenance trust; the second term is a constant floor proportional
        to the authority weight that ensures a high-tier (NATRIX) unit
        with low recency/importance/relevance still outranks a low-tier
        scanner unit with high stats. See AUTHORITY_FLOOR_WEIGHT comment
        for the worked example.

        ``authority_weight`` should be in [0.1, 1.0] — typically obtained
        via ``runtime.memory.authority.authority_weight(tier)``. Defaults
        to 1.0 so callers that haven't been migrated keep their old scoring.
        """
        base = (
            ALPHA_RECENCY * recency +
            BETA_IMPORTANCE * importance +
            GAMMA_RELEVANCE * relevance
        )
        # Clamp to [0.1, 1.0] defensively in case a caller passes an int tier
        # or an out-of-range value.
        aw = max(0.1, min(1.0, float(authority_weight)))
        return base * aw + AUTHORITY_FLOOR_WEIGHT * aw

    @staticmethod
    def _authority_weight_for(item_or_unit) -> float:
        """Resolve the authority weight for either a MemUnit-like object or
        a ContextItem.

        Lookup order:
        1. ``metadata.authority_tier`` int -> authority_weight
        2. ``source`` -> tier_for_source -> authority_weight
        3. RAW (0.1) fallback
        """
        # 1) Pull from metadata bag if present
        meta = getattr(item_or_unit, "metadata", None)
        if isinstance(meta, dict):
            tv = meta.get("authority_tier")
            if tv is not None:
                try:
                    return authority_weight(int(tv))
                except (TypeError, ValueError):
                    pass

        # 2) Fall back to the source string
        src = getattr(item_or_unit, "source", None)
        if src:
            return authority_weight(tier_for_source(src))

        # 3) Worst case
        return authority_weight(AuthorityTier.RAW)

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

            # 6. Portfolio candidates — explicit pull so the freshest
            #    snapshot + last 5 portfolio events ALWAYS land in the
            #    daily window even if the broader memory recall misses
            #    them. NATRIX-tier authority floats them to the top.
            portfolio_items = await self._pull_portfolio_candidates()
            candidates.extend(portfolio_items)
            log.info(f"[WORKING-CTX]   Portfolio: {len(portfolio_items)} candidates")

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
                    self._authority_weight_for(item),
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

            # Memory budget telemetry — count total context-content tokens
            # assembled today. Failure must never break the assembly.
            try:
                from .budget_tracker import record as _bt_record
                total_chars = sum(len(i.content or "") for i in deduped)
                await _bt_record(
                    "working_context_assembly",
                    max(1, total_chars // 4),
                    source=f"working_ctx:{today_str}",
                    metadata={"item_count": len(deduped), "themes": len(themes)},
                )
            except Exception as _bt_err:
                log.debug(f"[WORKING-CTX] budget record failed: {_bt_err}")

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
                aw = self._authority_weight_for(unit)
                salience = self.compute_salience(recency, importance_norm, relevance, aw)

                # Forward the unit's authority_tier into the context item's
                # metadata bag so re-scoring during refresh() can recover the
                # tier without re-classifying the source string.
                unit_meta = getattr(unit, "metadata", None) or {}
                _at = unit_meta.get("authority_tier")
                if _at is None:
                    _at = int(tier_for_source(unit.source))

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
                        "authority_tier": int(_at),
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

    async def _pull_portfolio_candidates(self, max_items: int = 6) -> list[ContextItem]:
        """Pull the freshest portfolio:snapshot + last few portfolio events.

        These are written by `runtime/portfolio/memory_bridge.py` with
        source strings under the ``portfolio:`` namespace, which the
        authority module classifies as NATRIX (tier 100). They will
        therefore beat scanner items in the salience competition, but
        we still pull them explicitly so the snapshot is GUARANTEED
        to be present after a single sync cycle — not at the mercy of
        the importance/recency floor.

        Returns up to ``max_items`` items: the most recent
        ``portfolio:snapshot`` plus the next 5 most-important
        ``portfolio:*`` events.
        """
        items: list[ContextItem] = []
        if not self.memory_store:
            return items

        try:
            units = await self.memory_store.search_units(
                tags=["portfolio"],
                importance_threshold=0.0,
                days_back=14,
            )
        except Exception as exc:
            log.warning(f"[WORKING-CTX] Portfolio pull failed: {exc}")
            return items

        if not units:
            return items

        # Sort by created_at desc so the latest snapshot wins
        try:
            units.sort(key=lambda u: getattr(u, "created_at", datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        except Exception:
            pass

        # Always include the freshest snapshot
        snapshot_unit = next((u for u in units if u.source == "portfolio:snapshot"), None)
        chosen: list[Any] = []
        seen_ids: set[str] = set()
        if snapshot_unit is not None:
            chosen.append(snapshot_unit)
            seen_ids.add(snapshot_unit.unit_id)

        # Then fill with the freshest non-snapshot portfolio events
        for u in units:
            if len(chosen) >= max_items:
                break
            if u.unit_id in seen_ids:
                continue
            chosen.append(u)
            seen_ids.add(u.unit_id)

        for unit in chosen:
            try:
                recency = self.compute_recency(unit.last_accessed, unit.decay_rate)
                importance_norm = self.compute_importance_normalized(unit.importance)
                # Authority weight will be re-applied in the assembly
                # rescore loop; pass 1.0 for now so this candidate is
                # at least as visible as memory candidates before re-rank.
                salience = self.compute_salience(recency, importance_norm, 0.5, 1.0)

                unit_meta = getattr(unit, "metadata", None) or {}
                _at = unit_meta.get("authority_tier")
                if _at is None:
                    _at = int(tier_for_source(unit.source))

                items.append(ContextItem(
                    item_id=f"mem:{unit.unit_id}",
                    content=unit.content[:500],
                    source=unit.source,
                    category="portfolio",
                    salience_score=salience,
                    importance=unit.importance,
                    recency_score=recency,
                    relevance_score=0.5,
                    tags=unit.tags,
                    created_at=unit.created_at.isoformat() if hasattr(unit, "created_at") else "",
                    metadata={
                        "unit_id": unit.unit_id,
                        "reinforcement_count": unit.reinforcement_count,
                        "decay_rate": unit.decay_rate,
                        "authority_tier": int(_at),
                        **{k: v for k, v in unit_meta.items() if k != "authority_tier"},
                    },
                ))
            except Exception as exc:
                log.debug(f"[WORKING-CTX] portfolio item build failed: {exc}")
                continue

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

    async def toggle_pin(self, item_id: str) -> Optional[bool]:
        """Toggle pin on an item. Returns new pin state, or None if not found."""
        async with self._lock:
            if not self._current:
                return None
            for item in self._current.items:
                if item.item_id == item_id:
                    item.pinned = not item.pinned
                    if item.pinned:
                        if item_id not in self._current.pinned_ids:
                            self._current.pinned_ids.append(item_id)
                    else:
                        self._current.pinned_ids = [pid for pid in self._current.pinned_ids if pid != item_id]
                    self._persist()
                    log.info(f"[WORKING-CTX] Toggle pin {item_id} → {'pinned' if item.pinned else 'unpinned'}")
                    return item.pinned
            return None

    async def promote_item(self, content: str, source: str, tags: list[str] = None, item_id: str = None) -> ContextItem:
        """Promote an item into the context window with high importance."""
        import uuid
        async with self._lock:
            if not self._current:
                await self.assemble()

            new_id = item_id or f"promoted:{uuid.uuid4().hex[:8]}"
            now = datetime.now(timezone.utc)
            item = ContextItem(
                item_id=new_id,
                content=content[:500],
                source=source,
                category="promoted",
                salience_score=0.90,
                importance=85.0,
                recency_score=1.0,
                relevance_score=0.95,
                tags=tags or [],
                pinned=True,
                created_at=now.isoformat(),
                assembled_at=now.isoformat(),
            )
            self._current.items.insert(0, item)
            # Keep within max
            if len(self._current.items) > MAX_CONTEXT_ITEMS:
                self._current.items = self._current.items[:MAX_CONTEXT_ITEMS]
            self._persist()
            log.info(f"[WORKING-CTX] Promoted item: {new_id}")
            return item

    async def dismiss_item(self, item_id: str) -> bool:
        """Remove an item from the context window."""
        async with self._lock:
            if not self._current:
                return False
            before = len(self._current.items)
            self._current.items = [i for i in self._current.items if i.item_id != item_id]
            if len(self._current.items) < before:
                self._current.pinned_ids = [pid for pid in self._current.pinned_ids if pid != item_id]
                self._persist()
                log.info(f"[WORKING-CTX] Dismissed item: {item_id}")
                return True
            return False

    async def inject_signal(self, content: str, source: str, importance: float = 50.0, tags: list[str] = None) -> None:
        """Inject an intelligence signal into the working context (called by Awarebot)."""
        import uuid
        # Stamp authority tier into the item's metadata so re-scoring and
        # any downstream consumer can recover the provenance class.
        _tier = tier_for_source(source)
        item = ContextItem(
            item_id=f"signal:{uuid.uuid4().hex[:8]}",
            content=content[:500],
            source=source,
            category="signal",
            salience_score=0.0,  # Will be recomputed
            importance=importance,
            recency_score=1.0,
            relevance_score=0.0,
            tags=tags or [],
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={"authority_tier": int(_tier)},
        )
        aw = authority_weight(_tier)
        # Compute relevance against current themes
        if self._current and self._current.themes:
            item.relevance_score = self.compute_relevance(content, self._current.themes)
            item.salience_score = self.compute_salience(
                item.recency_score,
                self.compute_importance_normalized(importance),
                item.relevance_score,
                aw,
            )
        else:
            # No themes assembled yet — keep authority in the mix so a low-tier
            # scanner inject can't outweigh a high-tier promoted item later.
            item.salience_score = (
                self.compute_importance_normalized(importance) * 0.7 * aw
                + AUTHORITY_FLOOR_WEIGHT * aw
            )

        await self.add_item(item)

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

    async def mark_accessed_batch(self, item_ids: list[str]) -> int:
        """Mark multiple items as accessed in one persist (used by GET endpoint).

        Returns count of items successfully marked.
        """
        if not item_ids:
            return 0
        async with self._lock:
            if not self._current:
                return 0
            id_set = set(item_ids)
            marked = 0
            for item in self._current.items:
                if item.item_id in id_set:
                    item.accessed_today = True
                    item.access_count += 1
                    marked += 1
            if marked:
                self._persist()
            return marked

    async def add_item(self, item: ContextItem) -> None:
        """Manually add an item to today's context (e.g., from chat or command).

        Enforces MAX_CONTEXT_ITEMS cap by evicting the lowest-salience, non-pinned
        item if needed (prevents unbounded growth from Awarebot inject_signal).
        """
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

            # Enforce cap — evict lowest-salience non-pinned items if oversize
            if len(self._current.items) > MAX_CONTEXT_ITEMS:
                # Sort: pinned first (kept), then by salience desc
                self._current.items.sort(key=lambda x: (x.pinned, x.salience_score), reverse=True)
                evicted = self._current.items[MAX_CONTEXT_ITEMS:]
                self._current.items = self._current.items[:MAX_CONTEXT_ITEMS]
                evicted_ids = {e.item_id for e in evicted}
                # Drop any pinned_ids that got evicted (shouldn't, but be safe)
                self._current.pinned_ids = [pid for pid in self._current.pinned_ids if pid not in evicted_ids]

            self._persist()
            log.debug(f"[WORKING-CTX] Added item: {item.item_id} (total={len(self._current.items)})")

    async def refresh(self, themes: Optional[list[str]] = None) -> DailyContext:
        """
        Mid-day refresh — re-score existing items and pull any new
        high-priority items that arrived since morning assembly.

        Unlike a raw assemble(), this preserves accessed_today and access_count
        on existing items so the EOD promote/demote cycle has accurate data.
        """
        # Snapshot existing access state before reassembly
        access_state: dict[str, tuple[bool, int, bool]] = {}
        async with self._lock:
            if self._current:
                for item in self._current.items:
                    access_state[item.item_id] = (
                        item.accessed_today,
                        item.access_count,
                        item.pinned,
                    )

        # Run full assembly (acquires its own lock)
        await self.assemble(themes=themes)

        # Restore access state on items that survived the reassembly
        if access_state:
            async with self._lock:
                if self._current:
                    restored = 0
                    for item in self._current.items:
                        if item.item_id in access_state:
                            prev_accessed, prev_count, prev_pinned = access_state[item.item_id]
                            item.accessed_today = item.accessed_today or prev_accessed
                            item.access_count = max(item.access_count, prev_count)
                            if prev_pinned:
                                item.pinned = True
                                if item.item_id not in self._current.pinned_ids:
                                    self._current.pinned_ids.append(item.item_id)
                            restored += 1
                    if restored > 0:
                        self._persist()
                        log.info(f"[WORKING-CTX] Refresh: restored access state for {restored} items")

        return self._current

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
