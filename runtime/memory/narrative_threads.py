"""
Cross-Session Narrative Threading (Loop 9)
==========================================

Solves the "user moved NY→SF" / "$TSLA earnings on Monday, Tuesday, Friday"
problem: discrete chat sessions and discrete signal memories about the same
ongoing subject are otherwise mutually invisible to each other.

A NarrativeThread links memory units across sessions / days when they share
a primary high-importance entity (ticker, person, project). Threads carry a
short LLM-generated summary, member unit IDs, and an importance bump that
lifts the thread into the daily working context as a single salient item
(the summary — not all members).

Persistence:
    data/memory/narrative_threads.jsonl           — active threads
    data/memory/narrative_threads_archive.jsonl   — least-recently-updated
                                                    archived when active > 100

Invariants:
    - Min 2 distinct source_unit_id "sources" per thread (rejects single-post
      echo chambers).
    - Active thread cap: 100. Archive overflow by LRU on last_updated_at.
    - Idempotent: running materialize_threads on the same candidate cluster
      updates the existing thread (no duplicates).
    - Thread summarization uses Claude Sonnet 4.6 with a $0.20/cycle cost
      cap via cost_tracker. Rule-based fallback when budget exhausted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.memory.narrative_threads")

# ── Configuration ────────────────────────────────────────────────────

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))

# Thread caps
MAX_ACTIVE_THREADS = 100
MIN_SOURCES_PER_THREAD = 2          # distinct source_unit_id (or source labels) required
MIN_UNITS_PER_THREAD = 2             # raw unit count
WORKING_CONTEXT_SURFACE_THRESHOLD = 5  # len(unit_ids) at which thread is surfaced

# Importance bump for member units (applied via link_to_units)
MEMBER_IMPORTANCE_BONUS = 5.0

# LLM
SUMMARIZATION_MODEL = "claude-sonnet-4-20250514"
PER_CYCLE_LLM_BUDGET_USD = 0.20
SUMMARY_MAX_TOKENS = 220             # short, 2-3 sentences

# Entity allow-list patterns (high-importance primary entities)
_TICKER_RE = re.compile(r'(?:\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b(?=\s+(?:stock|shares|earnings|price|rally|drop|surge|crash)))')
_PERSON_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_HASHTAG_RE = re.compile(r'#([a-zA-Z0-9_]{3,})')

# Words we never want as primary thread entities
_BANNED_PRIMARIES = {
    "the", "this", "that", "they", "we", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february",
    "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "today", "yesterday", "tomorrow",
    "claude", "url", "http", "https", "reddit.com", "t.co", "www",
    "ai", "llm", "api",
}

# Multi-word generic phrases that appear in templates (council headers,
# brief boilerplate, etc.) — reject as primary entities even though they
# pass the capitalized-multi-word heuristic.
_BANNED_PRIMARY_PHRASES = {
    "council report", "executive summary", "council insight",
    "key insights", "intelligence sweep", "morning brief",
    "council session", "youtube council", "council member",
    "key metric", "session id", "session report", "daily reflection",
    "intel brief", "context signals",
}


# ── Data Model ───────────────────────────────────────────────────────


@dataclass
class NarrativeThread:
    """A persistent narrative spanning multiple memory units / sessions."""

    thread_id: str
    title: str                              # human-readable, e.g. "TSLA Q1 earnings analysis"
    primary_entity: str                     # canonical key, e.g. "$TSLA"
    related_entities: list[str] = field(default_factory=list)
    started_at: str = ""                    # ISO
    last_updated_at: str = ""               # ISO
    unit_ids: list[str] = field(default_factory=list)
    session_ids: list[str] = field(default_factory=list)
    importance: float = 0.0                 # max importance across members
    summary: str = ""                       # LLM- or rule-generated
    # Bookkeeping
    member_sources: list[str] = field(default_factory=list)
    summary_model: str = ""                 # "claude-sonnet-4-20250514" or "rule"
    archived: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NarrativeThread":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def touch(self) -> None:
        self.last_updated_at = datetime.now(timezone.utc).isoformat()


# ── Helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_entity(e: str) -> str:
    """Canonicalize an entity for use as primary_entity / dict key."""
    if not e:
        return ""
    s = e.strip()
    # Drop leading punctuation that isn't $ or #
    if s and s[0] not in "$#" and not s[0].isalnum():
        s = s.lstrip()
    # Tickers: uppercase, ensure $ prefix
    if s.startswith("$"):
        return "$" + s[1:].upper()
    # Hashtags: keep #, lowercase the rest
    if s.startswith("#"):
        return "#" + s[1:].lower()
    return s


def _entity_quality(e: str) -> int:
    """Higher = better candidate for primary entity. 0 means reject."""
    if not e:
        return 0
    lo = e.lower().strip()
    if lo in _BANNED_PRIMARIES:
        return 0
    if lo in _BANNED_PRIMARY_PHRASES:
        return 0
    if len(lo) < 3 and not lo.startswith("$"):
        return 0
    # Tickers strongest
    if e.startswith("$"):
        return 100
    # Hashtags solid
    if e.startswith("#"):
        return 60
    # Multi-word Capitalized → likely person/company
    if " " in e and e[0].isupper():
        return 70
    if e[0].isupper():
        return 40
    return 20


def _extract_primary_entities(text: str, existing: Optional[list[str]] = None) -> list[str]:
    """
    Cheap primary-entity extraction from a unit's content. Falls back when
    the stored .entities field is empty (which is the case for most units
    in the live store — entity backfill only runs during consolidate_v2).
    """
    found: set[str] = set()
    if existing:
        for e in existing:
            ne = _norm_entity(e)
            if _entity_quality(ne) > 0:
                found.add(ne)
    if text:
        for m in _TICKER_RE.finditer(text):
            tk = m.group(1) or m.group(2)
            if tk and len(tk) >= 2:
                ne = _norm_entity("$" + tk)
                if _entity_quality(ne) > 0:
                    found.add(ne)
        for m in _PERSON_RE.finditer(text):
            ne = _norm_entity(m.group(0))
            if _entity_quality(ne) > 0:
                found.add(ne)
        for m in _HASHTAG_RE.finditer(text):
            ne = _norm_entity("#" + m.group(1))
            if _entity_quality(ne) > 0:
                found.add(ne)
    return sorted(found)


def _session_id_from_tags(tags: list[str]) -> Optional[str]:
    for t in tags or []:
        if t.startswith("session:"):
            return t.split(":", 1)[1]
    return None


def _source_root(source: str) -> str:
    """Strip 'consolidation:' wrappers and keep top-level source family."""
    s = (source or "").lower()
    while s.startswith("consolidation:"):
        s = s[len("consolidation:"):]
    return s.split(":", 1)[0] or "unknown"


def _short_title(primary: str, content: str) -> str:
    """Heuristic short title — used until LLM summary lands."""
    snippet = (content or "").replace("\n", " ").strip()
    snippet = re.sub(r"\s+", " ", snippet)[:60]
    return f"{primary} — {snippet}"


# ── Threader ─────────────────────────────────────────────────────────


class NarrativeThreader:
    """
    Cluster memory units into cross-session narrative threads keyed on
    high-importance primary entities.
    """

    def __init__(self, memory_store, knowledge_graph=None) -> None:
        self.memory_store = memory_store
        self.knowledge_graph = knowledge_graph
        self.data_dir = (NCL_BASE / "data" / "memory")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.active_file = self.data_dir / "narrative_threads.jsonl"
        self.archive_file = self.data_dir / "narrative_threads_archive.jsonl"
        self._lock = asyncio.Lock()
        self._threads: dict[str, NarrativeThread] = {}     # thread_id -> thread
        self._by_primary: dict[str, str] = {}              # primary_entity -> thread_id
        self._loaded = False

    # ── Persistence ──

    def _load(self) -> None:
        if self._loaded:
            return
        if self.active_file.exists():
            try:
                with self.active_file.open("r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            t = NarrativeThread.from_dict(json.loads(line))
                        except Exception:
                            continue
                        if t.archived:
                            continue
                        self._threads[t.thread_id] = t
                        self._by_primary[t.primary_entity] = t.thread_id
            except Exception as e:
                log.warning(f"[NARRATIVE] load failed: {e}")
        self._loaded = True
        log.info(f"[NARRATIVE] loaded {len(self._threads)} active threads")

    def _persist_atomic(self) -> None:
        tmp = self.active_file.with_suffix(".tmp")
        with tmp.open("w") as f:
            for t in self._threads.values():
                f.write(json.dumps(t.to_dict(), default=str) + "\n")
        os.replace(tmp, self.active_file)

    def _append_archive(self, thread: NarrativeThread) -> None:
        thread.archived = True
        with self.archive_file.open("a") as f:
            f.write(json.dumps(thread.to_dict(), default=str) + "\n")

    # ── Candidate detection ──

    async def find_thread_candidates(self, window_days: int = 7) -> list[dict]:
        """
        Cluster recent memory units by primary-entity overlap.

        Returns a list of {candidate_entity, units, span_days, source_count}
        for each cluster that meets the MIN_SOURCES_PER_THREAD floor.
        """
        units = await self.memory_store._load_all_units()  # noqa: SLF001
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        # Bucket by canonical primary entity. A single unit can land in
        # multiple buckets (one per primary it mentions) — that is by design;
        # threads are intersection points in entity-space.
        by_entity: dict[str, list[tuple[Any, list[str]]]] = defaultdict(list)

        for u in units:
            created = getattr(u, "created_at", None)
            if created is None:
                continue
            if getattr(created, "tzinfo", None) is None:
                # Convert naive to UTC; MemUnit should already be tz-aware but
                # belt-and-suspenders.
                from datetime import timezone as _tz
                created = created.replace(tzinfo=_tz.utc)
            if created < cutoff:
                continue
            existing = getattr(u, "entities", None) or []
            primaries = _extract_primary_entities(
                getattr(u, "content", "") or "", existing
            )
            if not primaries:
                continue
            for p in primaries:
                by_entity[p].append((u, primaries))

        candidates: list[dict] = []
        for entity, hits in by_entity.items():
            if len(hits) < MIN_UNITS_PER_THREAD:
                continue
            # Distinct source roots — reject single-source echo chambers
            sources = {_source_root(getattr(u, "source", "")) for u, _ in hits}
            distinct_unit_sources = {getattr(u, "unit_id", "") for u, _ in hits}
            if len(distinct_unit_sources) < MIN_SOURCES_PER_THREAD:
                continue
            # Also enforce: at least 2 distinct source roots OR at least
            # 2 distinct sessions, to avoid all-from-one-feed clusters.
            sessions = {
                s for s in (
                    _session_id_from_tags(getattr(u, "tags", []) or [])
                    for u, _ in hits
                ) if s
            }
            if len(sources) < 2 and len(sessions) < 2:
                # Single source family AND single session — likely just noise
                # from one Reddit thread or one chat. Skip.
                continue

            timestamps = []
            for u, _ in hits:
                t = getattr(u, "created_at", None)
                if t:
                    if getattr(t, "tzinfo", None) is None:
                        from datetime import timezone as _tz
                        t = t.replace(tzinfo=_tz.utc)
                    timestamps.append(t)
            if not timestamps:
                continue
            span_days = (max(timestamps) - min(timestamps)).total_seconds() / 86400.0

            candidates.append({
                "candidate_entity": entity,
                "units": [u for u, _ in hits],
                "span_days": round(span_days, 2),
                "source_count": len(sources),
                "session_count": len(sessions),
                "all_primaries": list({p for _, ps in hits for p in ps}),
            })

        # Order by quality * size (bigger, higher-quality entities first)
        candidates.sort(
            key=lambda c: (
                _entity_quality(c["candidate_entity"]),
                len(c["units"]),
                c["span_days"],
            ),
            reverse=True,
        )
        return candidates

    # ── Materialization ──

    async def materialize_threads(
        self, candidates: list[dict]
    ) -> list[NarrativeThread]:
        """
        Create or update threads from candidate clusters. Idempotent.

        Returns the list of NarrativeThreads that were created or updated
        in this call.
        """
        async with self._lock:
            self._load()
            touched: list[NarrativeThread] = []
            llm_budget_remaining = PER_CYCLE_LLM_BUDGET_USD

            for cand in candidates:
                primary = cand["candidate_entity"]
                units = cand["units"]
                if not units:
                    continue

                existing_id = self._by_primary.get(primary)
                if existing_id and existing_id in self._threads:
                    thread = self._threads[existing_id]
                    is_new = False
                else:
                    thread = NarrativeThread(
                        thread_id=str(uuid.uuid4()),
                        title="",
                        primary_entity=primary,
                        started_at=_now_iso(),
                    )
                    is_new = True

                # Merge member unit_ids (preserve insertion order, dedup)
                seen_units = set(thread.unit_ids)
                added_units: list[str] = []
                for u in units:
                    uid = getattr(u, "unit_id", None)
                    if uid and uid not in seen_units:
                        thread.unit_ids.append(uid)
                        seen_units.add(uid)
                        added_units.append(uid)

                # Sessions
                seen_sessions = set(thread.session_ids)
                for u in units:
                    sid = _session_id_from_tags(getattr(u, "tags", []) or [])
                    if sid and sid not in seen_sessions:
                        thread.session_ids.append(sid)
                        seen_sessions.add(sid)

                # Related entities — union of all primaries seen across members
                related = set(thread.related_entities)
                for p in cand.get("all_primaries", []):
                    if p != primary:
                        related.add(p)
                thread.related_entities = sorted(related)[:30]

                # Max importance across members
                thread.importance = max(
                    [thread.importance]
                    + [float(getattr(u, "importance", 0.0) or 0.0) for u in units]
                )

                # Member source labels
                src_roots = set(thread.member_sources)
                for u in units:
                    src_roots.add(_source_root(getattr(u, "source", "")))
                thread.member_sources = sorted(src_roots)

                # Title — only set on first creation, or if currently empty
                if not thread.title:
                    sample_content = next(
                        (getattr(u, "content", "") for u in units
                         if getattr(u, "content", "")),
                        "",
                    )
                    thread.title = _short_title(primary, sample_content)[:120]

                # Summary — LLM if new/changed AND budget allows
                needs_summary = is_new or bool(added_units) or not thread.summary
                if needs_summary:
                    summary, cost, model = await self._summarize(
                        thread, units, budget_usd=llm_budget_remaining
                    )
                    if summary:
                        thread.summary = summary
                        thread.summary_model = model
                        llm_budget_remaining = max(0.0, llm_budget_remaining - cost)

                thread.touch()
                self._threads[thread.thread_id] = thread
                self._by_primary[primary] = thread.thread_id
                touched.append(thread)

            # Enforce active cap with LRU archive on last_updated_at
            if len(self._threads) > MAX_ACTIVE_THREADS:
                ordered = sorted(
                    self._threads.values(),
                    key=lambda t: t.last_updated_at,
                )
                overflow = len(self._threads) - MAX_ACTIVE_THREADS
                for victim in ordered[:overflow]:
                    self._append_archive(victim)
                    self._threads.pop(victim.thread_id, None)
                    self._by_primary.pop(victim.primary_entity, None)

            self._persist_atomic()
            return touched

    # ── Summarization ──

    async def _summarize(
        self,
        thread: NarrativeThread,
        units: list[Any],
        budget_usd: float,
    ) -> tuple[str, float, str]:
        """
        Generate a 2-3 sentence summary of the thread.

        Tries Sonnet first (respecting per-cycle budget + cost_tracker daily
        cap). Falls back to a rule-based concatenation of top member titles.

        Returns (summary, cost_usd, model_label).
        """
        # Rule-based fallback summary — always available
        def _rule_summary() -> str:
            ranked = sorted(
                units,
                key=lambda u: float(getattr(u, "importance", 0.0) or 0.0),
                reverse=True,
            )
            picks = []
            for u in ranked[:2]:
                snippet = (getattr(u, "content", "") or "").replace("\n", " ")
                snippet = re.sub(r"\s+", " ", snippet).strip()[:140]
                if snippet:
                    picks.append(snippet)
            joined = " // ".join(picks) if picks else "(no content)"
            return (
                f"Thread on {thread.primary_entity}: "
                f"{len(thread.unit_ids)} units across {len(thread.session_ids) or 1} "
                f"session(s). {joined}"
            )

        if budget_usd <= 0.0:
            return _rule_summary(), 0.0, "rule"

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return _rule_summary(), 0.0, "rule"

        # Check daily cost_tracker budget too
        try:
            from ..cost_tracker import get_tracker, record_cost
            tracker = await get_tracker()
            est = min(budget_usd, 0.05)
            if not await tracker.can_spend("anthropic", est):
                return _rule_summary(), 0.0, "rule"
        except Exception:
            record_cost = None  # type: ignore

        # Build the prompt
        sample_lines = []
        for u in sorted(
            units,
            key=lambda u: float(getattr(u, "importance", 0.0) or 0.0),
            reverse=True,
        )[:6]:
            created = getattr(u, "created_at", "")
            src = _source_root(getattr(u, "source", ""))
            content = (getattr(u, "content", "") or "").replace("\n", " ")
            content = re.sub(r"\s+", " ", content)[:280]
            sample_lines.append(f"- [{created}|{src}] {content}")

        prompt = (
            f"You are summarising a cross-session narrative thread for a "
            f"second-brain system.\n\n"
            f"Primary entity: {thread.primary_entity}\n"
            f"Related entities: {', '.join(thread.related_entities[:8]) or '(none)'}\n"
            f"Sessions involved: {len(thread.session_ids) or 1}\n"
            f"Sources: {', '.join(thread.member_sources)}\n\n"
            f"Member excerpts (most important first):\n"
            + "\n".join(sample_lines)
            + "\n\nWrite a 2-3 sentence narrative summary that captures what "
              "is happening with this entity across the sessions. Be concrete. "
              "No preamble. No 'this thread' meta-talk."
        )

        try:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": SUMMARIZATION_MODEL,
                        "max_tokens": SUMMARY_MAX_TOKENS,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["content"][0]["text"].strip()
                usage = data.get("usage", {}) or {}
                # Sonnet 4 pricing: $3/M input, $15/M output
                cost = (
                    usage.get("input_tokens", 0) * 3.0
                    + usage.get("output_tokens", 0) * 15.0
                ) / 1_000_000.0
                try:
                    from ..cost_tracker import record_cost as _rc
                    if cost > 0:
                        await _rc("anthropic", cost, "narrative_thread_summary",
                                  detail=thread.primary_entity)
                except Exception:
                    pass
                # Memory budget telemetry — count Sonnet prompt-context tokens.
                try:
                    from .budget_tracker import record as _bt_record
                    await _bt_record(
                        "narrative_summary",
                        int(usage.get("input_tokens", 0) or 0),
                        tokens_out=int(usage.get("output_tokens", 0) or 0),
                        source=f"thread:{thread.primary_entity}",
                    )
                except Exception:
                    pass
                return text, cost, SUMMARIZATION_MODEL
        except Exception as e:
            log.warning(f"[NARRATIVE] LLM summarization failed for "
                        f"{thread.primary_entity}: {e}")
            return _rule_summary(), 0.0, "rule"

    # ── Queries ──

    async def get_thread(self, thread_id: str) -> Optional[NarrativeThread]:
        async with self._lock:
            self._load()
            return self._threads.get(thread_id)

    async def list_threads(
        self, limit: int = 50, active_only: bool = True
    ) -> list[dict]:
        async with self._lock:
            self._load()
            threads = sorted(
                self._threads.values(),
                key=lambda t: t.last_updated_at,
                reverse=True,
            )
            if not active_only:
                # Also stream the archive file
                if self.archive_file.exists():
                    try:
                        with self.archive_file.open("r") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    threads.append(
                                        NarrativeThread.from_dict(json.loads(line))
                                    )
                                except Exception:
                                    continue
                    except Exception:
                        pass
            return [t.to_dict() for t in threads[:limit]]

    # ── Side effects on member units ──

    async def link_to_units(self, thread: NarrativeThread) -> None:
        """
        Bump each member unit's importance by MEMBER_IMPORTANCE_BONUS and
        write the thread_id into its tags. The store doesn't have a generic
        metadata dict, so we use a `thread:<id>` tag instead — equivalent
        purpose, queryable via search_units(tags=[...]).
        """
        store = self.memory_store
        if not store:
            return
        tag = f"thread:{thread.thread_id}"
        # Use the internal _load_all_units / _rewrite_units path under the
        # store's write lock so reinforcement is atomic w.r.t. concurrent
        # consolidation. Mirror the pattern in consolidate().
        try:
            await store._acquire_write()  # noqa: SLF001
            try:
                units = await store._load_all_units()  # noqa: SLF001
                member_set = set(thread.unit_ids)
                changed = 0
                for u in units:
                    if u.unit_id in member_set:
                        if tag not in (u.tags or []):
                            u.tags.append(tag)
                            changed += 1
                        u.importance = min(
                            100.0,
                            float(u.importance or 0.0) + MEMBER_IMPORTANCE_BONUS,
                        )
                if changed:
                    await store._rewrite_units(units)  # noqa: SLF001
            finally:
                store._release_write()  # noqa: SLF001
        except Exception as e:
            log.warning(f"[NARRATIVE] link_to_units failed for "
                        f"{thread.thread_id}: {e}")


# ─────────────────────────────────────────────────────────────────────
# Loop function — to be wired into runtime/autonomous/scheduler.py
# ─────────────────────────────────────────────────────────────────────


async def _narrative_thread_loop(self) -> None:
    """
    Loop 9 — Cross-session narrative threading. Every 6h:
      1. Find candidate clusters in last 7 days of memory.
      2. Materialize (create or update) threads. Idempotent.
      3. For threads with >= 5 members, surface the SUMMARY (not all members)
         into the working_context as one salient item.
      4. Persist updates.
      5. Log [NARRATIVE] line.

    Designed to live as a method on the Scheduler instance — install with
    `from runtime.memory.narrative_threads import _narrative_thread_loop`
    and `Scheduler._narrative_thread_loop = _narrative_thread_loop`, or
    paste the body into scheduler.py alongside _mandate_purge_loop.
    """
    import asyncio as _asyncio
    from datetime import datetime as _dt, timezone as _tz

    log.info("[NARRATIVE] loop task spawned, warming up 60s...")
    try:
        await _asyncio.sleep(60)
    except _asyncio.CancelledError:
        raise

    # Construct (or reuse) the threader instance. Cache it on the Scheduler
    # so we don't reload the JSONL every tick.
    if getattr(self, "_narrative_threader", None) is None:
        try:
            store = self.brain.memory_store if self.brain else None
            kg = getattr(store, "_knowledge_graph", None) if store else None
            self._narrative_threader = NarrativeThreader(
                memory_store=store, knowledge_graph=kg,
            )
        except Exception as e:
            log.error(f"[NARRATIVE] init failed: {e}", exc_info=True)
            return

    threader: NarrativeThreader = self._narrative_threader

    while getattr(self, "_running", True):
        try:
            from ..autonomous.scheduler import EMERGENCY_STOP_EVENT  # local import
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[NARRATIVE] Emergency stop active — halting loop")
                break
        except Exception:
            pass

        try:
            candidates = await threader.find_thread_candidates(window_days=7)
            cand_count = len(candidates)

            before_ids = set(threader._threads.keys())  # noqa: SLF001
            touched = await threader.materialize_threads(candidates)
            after_ids = set(threader._threads.keys())   # noqa: SLF001
            created = len(after_ids - before_ids)
            updated = len(touched) - created

            # Surface large threads into working_context
            surfaced = 0
            wc = getattr(self, "_working_context", None)
            if wc is not None:
                try:
                    from .working_context import ContextItem  # local import
                    for t in touched:
                        if len(t.unit_ids) < WORKING_CONTEXT_SURFACE_THRESHOLD:
                            continue
                        item = ContextItem(
                            item_id=f"thread:{t.thread_id}",
                            content=(t.summary or t.title)[:1500],
                            source=f"narrative_thread:{t.primary_entity}",
                            category="memory",
                            salience_score=min(1.0, t.importance / 100.0),
                            importance=t.importance,
                            recency_score=1.0,
                            relevance_score=0.7,
                            tags=["narrative_thread", t.primary_entity]
                                 + t.related_entities[:5],
                            created_at=t.started_at,
                            metadata={
                                "thread_id": t.thread_id,
                                "unit_count": len(t.unit_ids),
                                "session_count": len(t.session_ids),
                                "primary_entity": t.primary_entity,
                                "summary_model": t.summary_model,
                            },
                        )
                        await wc.add_item(item)
                        surfaced += 1
                except Exception as e:
                    log.warning(f"[NARRATIVE] working_context surface failed: {e}")

            # Reinforce member units (importance + thread tag) — only for newly
            # touched threads to avoid runaway boosting on every tick.
            for t in touched:
                try:
                    await threader.link_to_units(t)
                except Exception as e:
                    log.debug(f"[NARRATIVE] link_to_units {t.thread_id}: {e}")

            log.info(
                f"[NARRATIVE] {cand_count} candidates, "
                f"{created} threads materialized, {updated} updated, "
                f"{surfaced} surfaced to working_context "
                f"({len(threader._threads)} active total)"  # noqa: SLF001
            )

            now_iso = _dt.now(_tz.utc).isoformat()
            if hasattr(self, "_stats"):
                self._stats["last_narrative_threading"] = now_iso
                self._stats["narrative_threads_total"] = len(threader._threads)  # noqa: SLF001
                self._stats["narrative_threads_created_run"] = created
                self._stats["narrative_threads_updated_run"] = updated

        except _asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"[NARRATIVE] loop error: {e}", exc_info=True)

        # Sleep 6 hours
        try:
            await _asyncio.sleep(21600)
        except _asyncio.CancelledError:
            raise
