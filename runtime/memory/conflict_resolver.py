"""
Loop 5 — Conflict Arbitration.

Detects contradictory memory units (same entity, opposed polarity) within a
rolling window, links them via the knowledge graph (or a sidecar index when KG
is unavailable), and queues high-severity disputes for council adjudication.

Standalone — does NOT modify scheduler.py. The companion loop function
``run_conflict_arbitration_cycle()`` is designed to be invoked by a new
``_conflict_arbitration_loop()`` task in scheduler.py (see integration spec).

Design notes
------------
* Detection is intentionally lightweight: regex-based ticker / entity
  extraction + polarity bag-of-words. Council remains the heavyweight
  arbitrator — this module's job is only to *surface* candidates.
* No mutation of MemUnit (the model has no ``metadata`` field). Sidecar
  index file ``data/memory/contradicts_index.jsonl`` is used as the fallback
  channel so working_context can downweight contradictory pairs.
* All writes are atomic (write-to-tmp + os.replace) and use aiofiles where
  the path is hot.
* Cost-controlled: at most ``MAX_COUNCIL_QUEUE_PER_CYCLE`` council requests
  per tick.

Author: NCL Brain — added 2026-05-21
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

from ..config import flags


log = logging.getLogger("ncl.memory.conflict_resolver")


# ── SQLite units-index fast path (W6-A) ───────────────────────────────────
#
# Conflict arbitration's `run_conflict_arbitration_cycle` fires on a 5/10/15m
# adaptive cadence and previously full-scanned the 200MB units.jsonl every
# tick. When ``NCL_UNITS_INDEX_SQLITE=true``, try the SQLite ``units_index``
# table first (W4-14, store.py:_search_units_via_sqlite_index). Falls back
# to the canonical ``search_units`` path on flag-off or ANY failure —
# flag-off behavior is bit-identical to before this retrofit.
async def _maybe_indexed_search(memory_store, **kwargs):
    """Drop-in replacement for ``memory_store.search_units(**kwargs)``."""
    if flags.units_index_sqlite():
        try:
            unit_ids = await memory_store._search_units_via_sqlite_index(**kwargs)
            if unit_ids:
                units_by_id = await memory_store._load_units_batch(set(unit_ids))
                return [units_by_id[uid] for uid in unit_ids if uid in units_by_id]
        except Exception as e:
            log.debug("[CONFLICT-ARB] sqlite index search failed (%s) — falling back", e)
    return await memory_store.search_units(**kwargs)


# ── Tuning constants ─────────────────────────────────────────────────────────
# Audit 2026-05-22: prior cap of 5/cycle vs 14,800 backlog = ~58 days to
# drain. Bumped to 50/cycle plus adaptive cadence (5min when burst,
# 15min when calm) and a quality filter (only queue conflicts with
# importance_divergence > 40 AND shared_entities >= 3).
MAX_COUNCIL_QUEUE_PER_CYCLE = 50
HIGH_SEVERITY_IMPORTANCE = 60.0  # Both units must be >= this to count "high"
CRITICAL_SEVERITY_IMPORTANCE = 75.0  # Both >= this AND >=2 entities overlap → critical

# Schema version stamped on every NEW contradicts_index.jsonl record (W4-15,
# 2026-05-23). Existing rows are NOT back-migrated — readers should treat
# absence as schema_version=0. Bump whenever the record shape changes.
_CONTRADICTS_SCHEMA_VERSION = 1
DEFAULT_WINDOW_HOURS = 24
OVERLAP_WINDOW_HOURS = 24  # Time gap between two units must be <= this
COUNCIL_IMPORTANCE_DIVERGENCE = 40.0  # min |imp_a - imp_b| to queue for council
COUNCIL_MIN_SHARED_ENTITIES = 3  # min overlap to promote to council

# Adaptive cadence thresholds for the scheduler loop (seconds).
CADENCE_BURST_S = 300  # backlog > 1000 -> 5min cycles
CADENCE_BUSY_S = 600  # backlog > 100  -> 10min cycles
CADENCE_CALM_S = 900  # default        -> 15min cycles
BACKLOG_BURST = 1000
BACKLOG_BUSY = 100

# ── Polarity dictionaries ────────────────────────────────────────────────────
BULLISH_TOKENS = {
    "buy",
    "bullish",
    "long",
    "accumulate",
    "rally",
    "breakout",
    "moon",
    "up",
    "uptrend",
    "positive",
    "outperform",
    "overweight",
    "strong buy",
    "calls",
    "call options",
    "pump",
    "ripping",
    "ripper",
    "surge",
    "gain",
    "rip",
    "rocket",
    "uppy",
    "green",
}
BEARISH_TOKENS = {
    "sell",
    "bearish",
    "short",
    "exit",
    "dump",
    "breakdown",
    "crash",
    "down",
    "downtrend",
    "negative",
    "underperform",
    "underweight",
    "strong sell",
    "puts",
    "put options",
    "fade",
    "tank",
    "tanking",
    "drop",
    "loss",
    "bagholder",
    "rug",
    "red",
    "bleeding",
}
# These act as polarity *inverters* preceding any token (e.g. "not bullish").
NEGATION_TOKENS = {"not", "no", "never", "isn't", "isnt", "won't", "wont", "doesn't", "doesnt"}

# ── Entity extraction ────────────────────────────────────────────────────────
# Tickers: $AAPL OR bare 1-5 capital letters with stock/share context
TICKER_DOLLAR_RE = re.compile(r"\$([A-Z]{1,5})\b")
TICKER_CONTEXT_RE = re.compile(
    r"\b([A-Z]{2,5})\b(?=\s+(?:stock|share|shares|equity|ticker|calls?|puts?|options?|trade|trading|price|chart))",
    re.IGNORECASE,
)
HASHTAG_RE = re.compile(r"#([A-Za-z][A-Za-z0-9_]{1,40})")


def _extract_entities(unit: Any) -> set[str]:
    """Pull entities from a MemUnit. Prefers explicit ``entities`` field,
    falls back to regex over content. Returns uppercase symbol set."""
    out: set[str] = set()
    # Honor pre-extracted entities first
    for e in getattr(unit, "entities", []) or []:
        e = (e or "").strip()
        if not e:
            continue
        # Normalize tickers (strip $ if present)
        if e.startswith("$"):
            e = e[1:]
        # Keep tickers in upper, leave names as-is
        if re.fullmatch(r"[A-Za-z]{1,5}", e):
            out.add(e.upper())
        else:
            out.add(e)
    content = getattr(unit, "content", "") or ""
    for m in TICKER_DOLLAR_RE.findall(content):
        out.add(m.upper())
    for m in TICKER_CONTEXT_RE.findall(content):
        # Skip very common false positives
        if m.upper() in {"THE", "AND", "FOR", "ALL", "NEW", "OLD", "ANY", "ONE", "TWO"}:
            continue
        out.add(m.upper())
    for m in HASHTAG_RE.findall(content):
        if len(m) <= 5 and m.isupper():
            out.add(m)
    # Honor tags that look like tickers
    for t in getattr(unit, "tags", []) or []:
        if t and re.fullmatch(r"[A-Z]{1,5}", t):
            out.add(t)
    return out


def _polarity(content: str) -> int:
    """Return +1 bullish, -1 bearish, 0 neutral. Naive bag-of-tokens with
    1-word negation flip. Lowercased pass."""
    if not content:
        return 0
    text = content.lower()
    tokens = re.findall(r"[a-z']+", text)
    bull = 0
    bear = 0
    for i, tok in enumerate(tokens):
        negated = i > 0 and tokens[i - 1] in NEGATION_TOKENS
        if tok in BULLISH_TOKENS:
            if negated:
                bear += 1
            else:
                bull += 1
        elif tok in BEARISH_TOKENS:
            if negated:
                bull += 1
            else:
                bear += 1
    if bull > bear:
        return 1
    if bear > bull:
        return -1
    return 0


def _source_weight(source: str) -> float:
    """Council/decision sources outweigh single-poster sources. 1.0 = baseline."""
    if not source:
        return 1.0
    s = source.lower()
    if "council" in s or "decision" in s or "mandate" in s:
        return 1.5
    if "brief" in s or "synthesis" in s:
        return 1.3
    if "reddit" in s or "x_twitter" in s or "x/" in s or "twitter" in s:
        return 0.8
    return 1.0


def _classify_severity(unit_a: Any, unit_b: Any, shared_entities: set[str]) -> str:
    """One of: low / medium / high / critical."""
    imp_a = float(getattr(unit_a, "importance", 0.0) or 0.0)
    imp_b = float(getattr(unit_b, "importance", 0.0) or 0.0)
    min_imp = min(imp_a, imp_b)
    wa = _source_weight(getattr(unit_a, "source", "") or "")
    wb = _source_weight(getattr(unit_b, "source", "") or "")
    # Effective importance includes source weighting
    eff = min_imp * min(wa, wb)
    if eff >= CRITICAL_SEVERITY_IMPORTANCE and len(shared_entities) >= 2:
        return "critical"
    if min_imp >= CRITICAL_SEVERITY_IMPORTANCE:
        return "critical" if (wa >= 1.3 and wb >= 1.3) else "high"
    if min_imp >= HIGH_SEVERITY_IMPORTANCE:
        return "high"
    if min_imp >= 30.0:
        return "medium"
    return "low"


# Soft cap on append-only JSONL ledger files. Once exceeded the file is
# rotated to ``<name>.1`` (oldest dropped) so the index can't grow unbounded
# — root cause of ``contradicts_index.jsonl`` hitting 30 MB and contributing
# to Brain RSS pressure / OOM SIGKILL loop.
_JSONL_ROTATE_BYTES = int(os.environ.get("NCL_JSONL_ROTATE_BYTES", 5 * 1024 * 1024))


def _maybe_rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > _JSONL_ROTATE_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            if backup.exists():
                backup.unlink()
            path.rename(backup)
    except OSError as e:
        log.warning("[JSONL-ROTATE] %s rotation failed: %s", path, e)


async def _atomic_append_jsonl(path: Path, record: dict) -> None:
    """Append-only JSONL writer with soft 5 MB rotation guard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate(path)
    line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
    async with aiofiles.open(path, mode="a", encoding="utf-8") as f:
        await f.write(line)


async def _atomic_write_json(path: Path, payload: dict) -> None:
    """Atomic JSON write via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
    async with aiofiles.open(tmp, mode="w", encoding="utf-8") as f:
        await f.write(data)
    os.replace(tmp, path)


class ConflictResolver:
    """
    Detects, links, and queues contradictions between recent memory units.

    Args:
        memory_store: NCL MemoryStore instance (must expose ``search_units``).
        knowledge_graph: Optional NCL KnowledgeGraph; if absent, contradictions
            are written to a sidecar index file instead of graph edges.
    """

    def __init__(self, memory_store: Any, knowledge_graph: Optional[Any] = None) -> None:
        self.memory_store = memory_store
        self.kg = knowledge_graph
        # Sidecar paths derived from the memory store's data_dir
        data_dir: Path = Path(getattr(memory_store, "data_dir", Path("data/memory"))).expanduser()
        self.contradicts_index_path = data_dir / "contradicts_index.jsonl"
        # Council pending queue lives next to the brain's council data
        brain_root = data_dir.parent  # data/memory → data/
        self.council_queue_path = brain_root / "councils" / "pending_conflicts.jsonl"

    # ────────────────────────────────────────────────────────────────────
    async def scan_recent(self, window_hours: int = DEFAULT_WINDOW_HOURS) -> list[dict]:
        """
        Find contradiction candidates from the last ``window_hours``.

        Returns a list of dicts:
            {
              "conflict_id": str,
              "entity": str,                # primary shared entity
              "shared_entities": [str, ...],
              "units": [unit_id_a, unit_id_b],
              "polarities": [+1, -1],
              "sources": [src_a, src_b],
              "importances": [imp_a, imp_b],
              "reason": str,                # human-readable
              "severity": "low|medium|high|critical",
              "created_at": iso8601,
            }
        """
        days = max(1, int((window_hours + 23) // 24))
        try:
            units = await _maybe_indexed_search(self.memory_store, days_back=days)
        except TypeError:
            # Older signatures
            units = await _maybe_indexed_search(self.memory_store)
        except Exception as e:
            log.error("[CONFLICT-ARB] search_units failed: %s", e)
            return []

        # Index by entity → list[(unit, polarity)]
        by_entity: dict[str, list[tuple[Any, int, set[str]]]] = {}
        for u in units:
            content = getattr(u, "content", "") or ""
            pol = _polarity(content)
            if pol == 0:
                continue
            ents = _extract_entities(u)
            if not ents:
                continue
            for ent in ents:
                by_entity.setdefault(ent, []).append((u, pol, ents))

        conflicts: list[dict] = []
        seen_pairs: set[tuple[str, str]] = set()
        now = datetime.now(timezone.utc)

        for entity, holders in by_entity.items():
            if len(holders) < 2:
                continue
            # Compare every bullish vs bearish pair on this entity
            bulls = [h for h in holders if h[1] > 0]
            bears = [h for h in holders if h[1] < 0]
            if not bulls or not bears:
                continue
            for ua, pa, ea in bulls:
                ta = getattr(ua, "created_at", None) or now
                for ub, pb, eb in bears:
                    tb = getattr(ub, "created_at", None) or now
                    # Time-overlap window
                    try:
                        gap_h = abs((ta - tb).total_seconds()) / 3600.0
                    except Exception:
                        gap_h = 0.0
                    if gap_h > OVERLAP_WINDOW_HOURS:
                        continue
                    ida = str(getattr(ua, "unit_id", ""))
                    idb = str(getattr(ub, "unit_id", ""))
                    if not ida or not idb or ida == idb:
                        continue
                    pair = tuple(sorted((ida, idb)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    shared = ea & eb
                    severity = _classify_severity(ua, ub, shared)
                    reason = (
                        f"{getattr(ua, 'source', '?')} (bullish) vs "
                        f"{getattr(ub, 'source', '?')} (bearish) on {entity}; "
                        f"importance {getattr(ua, 'importance', 0):.0f}/"
                        f"{getattr(ub, 'importance', 0):.0f}, "
                        f"gap {gap_h:.1f}h, shared entities={len(shared)}"
                    )
                    conflicts.append(
                        {
                            "conflict_id": uuid.uuid4().hex[:12],
                            "entity": entity,
                            "shared_entities": sorted(shared),
                            "units": [ida, idb],
                            "polarities": [pa, pb],
                            "sources": [getattr(ua, "source", ""), getattr(ub, "source", "")],
                            "importances": [
                                float(getattr(ua, "importance", 0.0) or 0.0),
                                float(getattr(ub, "importance", 0.0) or 0.0),
                            ],
                            "reason": reason,
                            "severity": severity,
                            "created_at": now.isoformat(),
                            "gap_hours": round(gap_h, 2),
                        }
                    )

        # Sort: critical > high > medium > low, then highest min-importance first
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        conflicts.sort(key=lambda c: (order.get(c["severity"], 9), -min(c["importances"])))
        return conflicts

    # ────────────────────────────────────────────────────────────────────
    async def link_contradicts(self, conflicts: list[dict]) -> int:
        """
        For each conflict pair, record the contradiction so downstream
        consumers (working_context, retrieval) can downweight it.

        Strategy:
          1. If a knowledge graph is wired, add a "CONTRADICTS" edge between
             the two units' primary entities (using add_relationships).
          2. Always also append a JSONL row to the sidecar contradicts_index
             so working_context can use it without touching the graph.

        Returns count of contradictions successfully linked.
        """
        if not conflicts:
            return 0

        linked = 0
        kg_ok = self.kg is not None

        for c in conflicts:
            try:
                if kg_ok:
                    # Add a relationship between the two unit_ids themselves
                    # AND between the shared entity and each unit_id.
                    units = c.get("units", [])
                    if len(units) == 2:
                        rels = [
                            {"subject": units[0], "predicate": "CONTRADICTS", "object": units[1]},
                            {"subject": units[1], "predicate": "CONTRADICTS", "object": units[0]},
                        ]
                        entity = c.get("entity")
                        if entity:
                            rels.extend(
                                [
                                    {
                                        "subject": entity,
                                        "predicate": "DISPUTED_BY",
                                        "object": units[0],
                                    },
                                    {
                                        "subject": entity,
                                        "predicate": "DISPUTED_BY",
                                        "object": units[1],
                                    },
                                ]
                            )
                        try:
                            await self.kg.add_relationships(rels, source_unit_id=units[0])
                        except Exception as kge:
                            log.warning(
                                "[CONFLICT-ARB] KG link failed (%s) — sidecar still written", kge
                            )

                # Always append to sidecar — single source of truth for the
                # working_context downweighter.
                record = {
                    "conflict_id": c["conflict_id"],
                    "ts": c["created_at"],
                    "entity": c.get("entity"),
                    "units": c.get("units", []),
                    "severity": c.get("severity"),
                    "polarities": c.get("polarities", []),
                    "sources": c.get("sources", []),
                    "importances": c.get("importances", []),
                    "reason": c.get("reason"),
                    "schema_version": _CONTRADICTS_SCHEMA_VERSION,
                }
                await _atomic_append_jsonl(self.contradicts_index_path, record)
                linked += 1
            except Exception as e:
                log.error("[CONFLICT-ARB] failed to link conflict %s: %s", c.get("conflict_id"), e)
                continue

        return linked

    # ────────────────────────────────────────────────────────────────────
    async def queue_for_council(self, conflict: dict) -> dict:
        """
        Write a council adjudication request to
        ``data/councils/pending_conflicts.jsonl``. The council auto-loop can
        pick this up and spawn a Delphi-MAD session on it.
        """
        try:
            entity = conflict.get("entity", "UNKNOWN")
            cid = conflict.get("conflict_id") or uuid.uuid4().hex[:12]
            topic = f"Conflict arbitration on {entity}: {conflict.get('reason', '')[:160]}"
            payload = {
                "conflict_id": cid,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "topic": topic,
                "entity": entity,
                "severity": conflict.get("severity"),
                "units": conflict.get("units", []),
                "polarities": conflict.get("polarities", []),
                "sources": conflict.get("sources", []),
                "importances": conflict.get("importances", []),
                "reason": conflict.get("reason"),
                "council_type": "delphi_mad",
                "status": "pending",
            }
            await _atomic_append_jsonl(self.council_queue_path, payload)
            return {"queued": True, "council_topic": topic, "conflict_id": cid}
        except Exception as e:
            log.error("[CONFLICT-ARB] queue_for_council failed: %s", e)
            return {
                "queued": False,
                "council_topic": "",
                "conflict_id": conflict.get("conflict_id", ""),
            }


# ── Standalone loop function for scheduler integration ───────────────────────
# Wired into scheduler.py as Loop 18 (`ncl-conflict-arbitration`). Cadence
# 900s (15m). See bottom of this file for the integration spec.


async def run_conflict_arbitration_cycle(
    brain: Any,
    stats: dict,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    high_imp_floor: float = HIGH_SEVERITY_IMPORTANCE,
    max_council_queue: int = MAX_COUNCIL_QUEUE_PER_CYCLE,
) -> dict:
    """
    Single arbitration tick. Designed to be called from the scheduler's
    `_conflict_arbitration_loop` wrapper.

    Returns a dict with counts. Also writes one JSONL row to
    ``data/memory/conflict_arbitration.jsonl`` and updates ``stats`` in place.
    """
    memory_store = getattr(brain, "memory_store", None)
    if memory_store is None:
        log.warning("[CONFLICT-ARB] no memory_store on brain — skipping cycle")
        return {"found": 0, "linked": 0, "queued": 0}

    kg = getattr(memory_store, "_knowledge_graph", None) or getattr(brain, "knowledge_graph", None)
    resolver = ConflictResolver(memory_store, knowledge_graph=kg)

    # 1. Scan
    all_conflicts = await resolver.scan_recent(window_hours=window_hours)

    # 2. Filter to HIGH severity (both units' importance >= floor)
    high_conflicts = [
        c for c in all_conflicts if min(c.get("importances", [0.0, 0.0])) >= high_imp_floor
    ]

    # 3. Link contradictions in KG + sidecar
    linked = await resolver.link_contradicts(high_conflicts)

    # 4. Quality filter for council — only conflicts where there's a real
    #    disagreement worth multi-LLM deliberation. Council bandwidth is
    #    finite; lower-severity contradictions stay logged but unpromoted.
    council_candidates = []
    for c in high_conflicts:
        if c.get("severity") not in ("critical", "high"):
            continue
        imps = c.get("importances", [0.0, 0.0])
        try:
            divergence = abs(float(imps[0]) - float(imps[1]))
        except (TypeError, ValueError, IndexError):
            divergence = 0.0
        shared = c.get("shared_entities", []) or []
        if divergence < COUNCIL_IMPORTANCE_DIVERGENCE:
            continue
        if len(shared) < COUNCIL_MIN_SHARED_ENTITIES:
            continue
        council_candidates.append(c)

    queued = 0
    for c in council_candidates[:max_council_queue]:
        result = await resolver.queue_for_council(c)
        if result.get("queued"):
            queued += 1

    # 5. Persist tick summary (include backlog so the scheduler can pick
    #    the right cadence next tick).
    ts = datetime.now(timezone.utc).isoformat()
    backlog = max(0, len(all_conflicts) - queued)
    summary = {
        "ts": ts,
        "window_hours": window_hours,
        "found": len(all_conflicts),
        "high": len(high_conflicts),
        "linked": linked,
        "critical": len([c for c in high_conflicts if c.get("severity") == "critical"]),
        "council_candidates": len(council_candidates),
        "queued_for_council": queued,
        "cap": max_council_queue,
        "backlog": backlog,
    }
    try:
        data_dir = Path(getattr(memory_store, "data_dir", "data/memory")).expanduser()
        await _atomic_append_jsonl(data_dir / "conflict_arbitration.jsonl", summary)
    except Exception as e:
        log.warning("[CONFLICT-ARB] failed to persist summary: %s", e)

    # 6. Log
    log.info(
        "[CONFLICT-ARB] %d conflicts found, %d linked, %d queued for council",
        len(all_conflicts),
        linked,
        queued,
    )

    # 7. Update stats
    if isinstance(stats, dict):
        stats["last_conflict_arbitration"] = ts
        stats["conflicts_detected_lifetime"] = stats.get("conflicts_detected_lifetime", 0) + len(
            all_conflicts
        )
        stats["conflicts_linked_lifetime"] = stats.get("conflicts_linked_lifetime", 0) + linked
        stats["conflicts_queued_lifetime"] = stats.get("conflicts_queued_lifetime", 0) + queued

    return summary


# ── Scheduler integration spec ───────────────────────────────────────────────
INTEGRATION_SPEC = """
SCHEDULER INTEGRATION — add as Loop 18 (`ncl-conflict-arbitration`).
Do NOT touch scheduler.py from a sub-agent — the wiring below should be
applied by a human or top-level Claude in a single targeted patch.

1. At the top of runtime/autonomous/scheduler.py, add the import:

    from ..memory.conflict_resolver import run_conflict_arbitration_cycle

2. Add the loop method on AutonomousScheduler (near _alert_dispatch_loop):

    async def _conflict_arbitration_loop(self) -> None:
        '''LOOP 18 — Conflict arbitration (15m cadence).'''
        log.info('[CONFLICT-ARB] loop started (900s cadence)')
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical('[CONFLICT-ARB] emergency stop — halting')
                break
            try:
                await run_conflict_arbitration_cycle(self.brain, self._stats)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error('[CONFLICT-ARB] cycle failed: %s', e, exc_info=True)
            try:
                await asyncio.sleep(900)
            except asyncio.CancelledError:
                raise

3. In the start() method, after the other 2026-05-21 loops, add:

    self._tasks.append(
        asyncio.create_task(self._conflict_arbitration_loop(),
                            name='ncl-conflict-arbitration')
    )

4. In self._task_factories dict, add:

    'ncl-conflict-arbitration': self._conflict_arbitration_loop,

5. Update CLAUDE.md autonomous-task table to show 18 active tasks.

The supervisor will pick the new loop up automatically because it derives
its watch list from self._task_factories.
"""
