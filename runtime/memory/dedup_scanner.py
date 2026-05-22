"""
Sliding-Window Semantic Dedup Scanner
=====================================

Background
----------
Night Watch Phase 2 Task M1 (semantic duplicate detection) was wedging the
entire nightly cycle. On the last cycle it timed out at 30 minutes and reported
11,521 duplicates among 9,710 units — far more "duplicates" than units, because
the per-unit ChromaDB query was double-counting both directions of every pair
(A→B and B→A) and counting up to 4 matches per query.

This module lifts M1 out of Night Watch into its own dedicated loop
(``ncl-dedup-scan``) and rewrites it with three guardrails:

1. **Sliding window** — scope is the 500 newest units, not the full store.
   The change frontier is where new duplicates land; the older corpus has
   already passed through Phase 4 consolidation.

2. **One-directional comparison** — for each pair (A, B), count exactly once.
   Implemented by storing every match as a sorted-pair tuple in a set; the
   pair is processed and counted on its first sighting only.

3. **Bounded merge budget** — even with the windowed scope a noisy ingest can
   yield hundreds of matches; we cap merges per cycle at ``DEDUP_MAX_MERGES``
   to keep the cycle predictable and avoid hammering the write-lock under
   a flood.

Public API:
    ``run_dedup_scan(brain, window_size=500, max_merges=200) -> dict``

Returns:
    {
        "candidates_checked": int,    # # units we scored
        "dupes_found": int,           # unique pairs above similarity threshold
        "merged": int,                # pairs actually consolidated
        "duration_s": float,
        "errors": list[str],
    }
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("ncl.memory.dedup_scanner")


# ── Tunables ─────────────────────────────────────────────────────────────
DEDUP_WINDOW_DEFAULT = 500
DEDUP_MAX_MERGES_DEFAULT = 200
SIMILARITY_THRESHOLD = 0.92         # cosine sim above this counts as duplicate
QUERY_N_RESULTS = 5                 # how many neighbors to fetch per unit
PER_CYCLE_TIMEOUT_SECONDS = 600     # 10-minute hard cap


_CONSOLIDATION_RE = re.compile(r"\[CONSOLIDATED[^\]]*\]\s*")


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    """Return a stable tuple for a pair — sorted so (A,B) == (B,A)."""
    return (a, b) if a < b else (b, a)


async def _find_duplicate_pairs(
    memory_store: Any,
    window: list,
    task_t0: float,
) -> tuple[set[tuple[str, str]], list[str]]:
    """Walk the window, query ChromaDB for each unit's nearest neighbors,
    return the de-duplicated set of (unit_a, unit_b) pairs above threshold.

    Pairs are stored as a set of sorted tuples so each duplicate is
    counted exactly once even if it appears in both A→B and B→A queries.
    """
    errors: list[str] = []
    pairs: set[tuple[str, str]] = set()

    if not memory_store._init_vector_db():
        errors.append("chromadb_unavailable")
        return pairs, errors

    if not hasattr(memory_store, "_chroma_collections"):
        errors.append("no_chroma_collections")
        return pairs, errors

    window_ids = {u.unit_id for u in window}

    for unit in window:
        # Hard cycle timeout
        if time.monotonic() - task_t0 > PER_CYCLE_TIMEOUT_SECONDS:
            errors.append("timeout")
            log.warning("[DEDUP-SCAN] hit %ds timeout — aborting query phase",
                        PER_CYCLE_TIMEOUT_SECONDS)
            break

        mem_type = getattr(unit, "memory_type", "episodic")
        collection = memory_store._get_collection_for_type(mem_type)
        if collection is None:
            continue

        try:
            results = await asyncio.to_thread(
                collection.query,
                query_texts=[unit.content[:500]],
                n_results=QUERY_N_RESULTS,
            )
        except Exception as e:
            log.debug("[DEDUP-SCAN] ChromaDB query for %s: %s",
                      unit.unit_id[:8], e)
            continue

        if not results or not results.get("ids") or not results["ids"][0]:
            continue
        if not results.get("distances") or not results["distances"][0]:
            continue

        for match_id, distance in zip(
            results["ids"][0], results["distances"][0]
        ):
            if match_id == unit.unit_id:
                continue
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            similarity = 1.0 - (distance / 2.0)
            if similarity < SIMILARITY_THRESHOLD:
                continue
            # ONE-DIRECTIONAL: count pair once
            pair = _normalize_pair(unit.unit_id, match_id)
            pairs.add(pair)

    return pairs, errors


def _plan_merge(keep: Any, drop: Any) -> Any:
    """Compute the merged ``keep`` state in-memory (no I/O).

    Mirrors `MemoryStore.consolidate()`'s cluster-merge math but pure:
    returns the updated ``keep`` object so the caller can batch many of
    these together and persist with ONE file rewrite.
    """
    keep_text = _CONSOLIDATION_RE.sub("", keep.content or "").strip()
    drop_text = _CONSOLIDATION_RE.sub("", drop.content or "").strip()
    if drop_text and drop_text not in keep_text:
        merged_content = (keep_text + " | " + drop_text)[:2000]
        keep.content = merged_content

    merged_tags = list({*(keep.tags or []), *(drop.tags or [])})[:20]
    keep.tags = merged_tags

    keep.importance = min(100.0, float(keep.importance) * 1.05)
    keep.reinforcement_count = int(
        getattr(keep, "reinforcement_count", 0) or 0
    ) + int(getattr(drop, "reinforcement_count", 0) or 0) + 1
    keep.last_accessed = datetime.now(timezone.utc)
    return keep


async def _apply_merges_batch(
    memory_store: Any,
    merges: list[tuple[Any, Any]],
) -> int:
    """Apply a batch of (keep, drop) merges with ONE rewrite + ONE embedding purge.

    A prior implementation called `_persist_reinforcement(keep)` per pair
    (full ~20MB file rewrite each) AND then a second `_acquire_write` +
    `_rewrite_units` per pair to drop `drop`. At 200 pairs that's 400 full-
    file rewrites of a 9.4K-unit jsonl — wall-clock-minutes of disk I/O
    inside the write lock. Now we batch.

    Returns: number of pairs successfully applied.
    """
    if not merges:
        return 0

    drop_ids: set[str] = {d.unit_id for _, d in merges}
    keep_by_id: dict[str, Any] = {k.unit_id: k for k, _ in merges}

    # Pre-mutate keeps in-memory
    for keep, drop in merges:
        try:
            _plan_merge(keep, drop)
        except Exception as e:
            log.warning("[DEDUP-SCAN] plan_merge failed (keep=%s,drop=%s): %s",
                        keep.unit_id[:8], drop.unit_id[:8], e)

    await memory_store._acquire_write()
    try:
        units = await memory_store._load_all_units()
        survivors = []
        for u in units:
            if u.unit_id in drop_ids:
                continue  # remove duplicate
            if u.unit_id in keep_by_id:
                survivors.append(keep_by_id[u.unit_id])  # replace with updated keep
            else:
                survivors.append(u)
        await memory_store._rewrite_units(survivors)
    finally:
        memory_store._release_write()

    # Outside the lock — purge the dropped embeddings in one chunked call.
    try:
        from .chroma_gc import delete_unit_embeddings
        await delete_unit_embeddings(memory_store, list(drop_ids))
    except Exception as e:
        log.debug("[DEDUP-SCAN] batched embedding delete failed: %s", e)

    return len(merges)


async def run_dedup_scan(
    brain: Any,
    window_size: int = DEDUP_WINDOW_DEFAULT,
    max_merges: int = DEDUP_MAX_MERGES_DEFAULT,
) -> dict:
    """One full sliding-window dedup pass.

    Args:
        brain: the NCL brain (we use brain.memory_store)
        window_size: how many of the newest units to scan (default 500)
        max_merges: hard cap on merges per cycle (default 200)

    Returns: stats dict for the scheduler / API.
    """
    task_t0 = time.monotonic()
    out = {
        "candidates_checked": 0,
        "dupes_found": 0,
        "merged": 0,
        "duration_s": 0.0,
        "errors": [],
        "window_size": window_size,
        "max_merges": max_merges,
    }

    memory_store = getattr(brain, "memory_store", None)
    if memory_store is None:
        out["errors"].append("no_memory_store")
        out["duration_s"] = time.monotonic() - task_t0
        return out

    try:
        units = await memory_store._load_all_units()
    except Exception as e:
        out["errors"].append(f"load_all_units: {e}")
        out["duration_s"] = time.monotonic() - task_t0
        return out

    if not units:
        out["duration_s"] = time.monotonic() - task_t0
        return out

    # Sliding window — sort newest-first by created_at, take first N
    def _ts(u):
        ts = getattr(u, "created_at", None)
        if ts is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)
        return ts

    units_sorted = sorted(units, key=_ts, reverse=True)
    window = units_sorted[:window_size]
    out["candidates_checked"] = len(window)

    if not window:
        out["duration_s"] = time.monotonic() - task_t0
        return out

    log.info(
        "[DEDUP-SCAN] starting Phase 1: querying %d-unit window against ChromaDB",
        len(window),
    )

    # ── Phase 1: find pairs (one-directional, deduped) ────────────────
    pairs, errors = await _find_duplicate_pairs(memory_store, window, task_t0)
    out["dupes_found"] = len(pairs)
    out["errors"].extend(errors)

    log.info(
        "[DEDUP-SCAN] Phase 1 complete: %d pairs found in %.1fs",
        len(pairs), time.monotonic() - task_t0,
    )

    if not pairs:
        out["duration_s"] = time.monotonic() - task_t0
        log.info("[DEDUP-SCAN] no duplicate pairs — cycle done")
        return out

    # ── Phase 2: plan merges (resolve keep/drop), then apply in batch ──
    # Resolve each pair to its two MemUnits, picking keep/drop by importance.
    # All planning happens in-memory; the actual write happens ONCE at the
    # end so we don't take the write-lock 200 times.
    units_by_id = {u.unit_id: u for u in units}
    merge_plan: list[tuple[Any, Any]] = []
    seen_drops: set[str] = set()
    for (id_a, id_b) in sorted(pairs):  # deterministic order
        if len(merge_plan) >= max_merges:
            log.info("[DEDUP-SCAN] hit max_merges=%d cap — deferring rest "
                     "to next cycle", max_merges)
            break
        if time.monotonic() - task_t0 > PER_CYCLE_TIMEOUT_SECONDS:
            out["errors"].append("merge_phase_timeout")
            break

        a = units_by_id.get(id_a)
        b = units_by_id.get(id_b)
        if a is None or b is None:
            continue

        # Skip a pair whose unit is already scheduled for drop in this batch
        # (otherwise we'd "merge" a phantom that won't exist after the rewrite).
        if id_a in seen_drops or id_b in seen_drops:
            continue

        # Higher importance wins; tie → older (smaller created_at) wins
        if (float(a.importance), -_ts(a).timestamp()) >= (
            float(b.importance), -_ts(b).timestamp()
        ):
            keep, drop = a, b
        else:
            keep, drop = b, a

        # Also skip if keep is in seen_drops (would write a stale keep)
        if keep.unit_id in seen_drops:
            continue

        merge_plan.append((keep, drop))
        seen_drops.add(drop.unit_id)

    log.info("[DEDUP-SCAN] Phase 2 planning complete: %d merges queued", len(merge_plan))

    merged = await _apply_merges_batch(memory_store, merge_plan)

    out["merged"] = merged
    out["duration_s"] = time.monotonic() - task_t0

    log.info(
        "[DEDUP-SCAN] checked=%d, pairs=%d, merged=%d, duration=%.1fs%s",
        out["candidates_checked"], out["dupes_found"], out["merged"],
        out["duration_s"],
        f", errors={out['errors']}" if out["errors"] else "",
    )
    return out
