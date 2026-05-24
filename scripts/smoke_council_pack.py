"""Smoke the universal council pack against live data — no LLM cost.

Run from outside the Brain process. We mock the FusedRetriever with a
candidate set built from RECENT entries in data/memory/units.jsonl (read
directly, no MemoryStore acquisition) so we exercise every piece of the
pack pipeline against real production text — entity overlap, authority
tier mapping, MMR diversity, temporal split, contradicts_index surfacing,
position trick, 40% utilization cap, MapReduce trigger.

Then call write_back_council against a temporary AsyncMemoryWriter
backed by a throwaway MemoryStore so the 3-tier persist path runs end
to end with the same code paths the autonomous loop will hit.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


NCL_ROOT = Path("/Users/natrix/dev/NCL")
sys.path.insert(0, str(NCL_ROOT))

# Real data directory — read-only access to contradicts_index + source_authority.
os.environ["NCL_BASE"] = str(NCL_ROOT)


def _load_recent_units(jsonl_path: Path, hours_back: int = 24, limit: int = 80) -> list[dict]:
    """Tail-read the units.jsonl and return units from the last ``hours_back``."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    rows: list[dict] = []
    if not jsonl_path.exists():
        return rows
    # Stream — last lines first by reading the whole file then reversing.
    # Production units.jsonl can be large; we cap at limit*5 candidates.
    with jsonl_path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        block = min(size, 4_000_000)  # last 4MB is usually enough for 24h
        fh.seek(size - block)
        lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        if len(rows) >= limit * 5:
            break
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            ts = datetime.fromisoformat(str(obj.get("created_at") or "").replace("Z", "+00:00"))
            if ts < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        rows.append(obj)
    return rows[:limit]


def _unit_to_candidate(unit: dict) -> dict:
    """Reshape a units.jsonl row into the FusedRetriever-output schema."""
    return {
        "unit_id": unit.get("unit_id") or unit.get("id"),
        "content": unit.get("content") or "",
        "source": unit.get("source") or "",
        "authority_tier": (unit.get("metadata") or {}).get("authority_tier"),
        "fused_score": float(unit.get("importance") or 50.0) / 100.0,
        "created_at": unit.get("created_at"),
        "tags": list(unit.get("tags") or []),
        "metadata": unit.get("metadata") or {},
        "signal_id": (unit.get("metadata") or {}).get("signal_id"),
    }


class RealCandidatesRetriever:
    """Mock FusedRetriever that returns real recent units. Read-only on
    units.jsonl, no MemoryStore lock contention with the running Brain.
    """

    def __init__(self, units_path: Path):
        self._units = [_unit_to_candidate(u) for u in _load_recent_units(units_path)]
        print(f"[retriever] loaded {len(self._units)} recent units from {units_path.name}")

    async def retrieve(self, query: str, top_k: int = 10, weights=None):
        # Naive relevance: keyword overlap between query and content. Good
        # enough for a smoke — the real assembler uses MMR + temporal split
        # downstream so the exact relevance score doesn't matter much.
        q_tokens = {t.lower() for t in query.split() if len(t) >= 3}
        scored: list[tuple[float, dict]] = []
        for cand in self._units:
            content = (cand.get("content") or "").lower()
            overlap = sum(1 for t in q_tokens if t in content)
            base = cand.get("fused_score") or 0.0
            scored.append((base + overlap * 0.05, cand))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, c in scored[: max(top_k, 10)]:
            c = dict(c)
            c["fused_score"] = round(score, 4)
            out.append(c)
        return out


class _ThrowawayMemoryStore:
    """A tiny in-memory persist sink so AsyncMemoryWriter has somewhere to
    drain to without touching the live MemoryStore.
    """

    def __init__(self) -> None:
        self.persisted: list[dict] = []
        # AsyncMemoryWriter checks for these attrs.

    async def create_unit(self, **kwargs):
        from types import SimpleNamespace

        self.persisted.append(kwargs)
        # Return a unit-shaped object
        return SimpleNamespace(
            unit_id=f"smoke-{len(self.persisted)}",
            content=kwargs.get("content", ""),
            source=kwargs.get("source", ""),
            importance=kwargs.get("importance", 50.0),
        )

    async def persist_units_batch(self, units):
        # Pretend success — write to the in-memory list
        for u in units:
            self.persisted.append({"_batch": True, **u.__dict__})
        return len(units)


async def main() -> int:
    from runtime.council_pack import assemble_council_pack, write_back_council
    from runtime.feedback.source_authority_learner import get_learner

    print("=== universal council pack smoke ===")
    print(f"date: {datetime.now().isoformat()}")
    print(f"ncl base: {NCL_ROOT}")
    print()

    retriever = RealCandidatesRetriever(NCL_ROOT / "data" / "memory" / "units.jsonl")

    # Source authority learner — uses singleton (state file at
    # data/feedback/source_authority.json; may or may not exist).
    learner = get_learner()
    n_known = len(learner.all_sources())
    print(f"[learner] {n_known} sources tracked")
    print()

    t0 = time.perf_counter()
    pack = await assemble_council_pack(
        topic="AAPL momentum next 5 trading days",
        query="AAPL Apple stock earnings options flow",
        fused_retriever=retriever,
        working_context=None,
        learner=learner,
        hot_top_k=6,
        arc_top_k=10,
        enable_mapreduce=True,
        contradicts_lookback_days=14,
    )
    dt = time.perf_counter() - t0

    print(f"=== pack assembled in {dt*1000:.0f}ms ===")
    print(f"sections        : {len(pack.sections)}")
    print(f"items in pack   : {pack.pack_size_items}")
    print(f"token estimate  : {pack.token_estimate}")
    print(f"utilization     : {pack.utilization_fraction:.1%}")
    print(f"map-reduce fired: {pack.mapreduce_applied}")
    print(f"surfaced conflicts: {len(pack.surfaced_conflicts)}")
    print(f"document blocks : {len(pack.document_blocks)}")
    print(f"notes           : {pack.notes}")
    print()
    print("=== section labels ===")
    for s in pack.sections:
        print(f"  - {s.label}  (items: {len(s.items)})")
    print()
    if pack.surfaced_conflicts:
        print("=== surfaced conflicts ===")
        for c in pack.surfaced_conflicts[:3]:
            print(f"  [{c.get('severity')}] {c.get('entity')} — {c.get('reason','')[:120]}")
        print()

    print("=== first 2500 chars of rendered prompt ===")
    print(pack.prompt_text[:2500])
    print("...")
    print()

    # ── Now exercise the 3-tier write-back path. Build an AsyncWriter
    #    against a throwaway store so the call is real but doesn't pollute
    #    the running Brain's units.jsonl.
    print("=== write-back smoke ===")
    from runtime.memory.async_writer import AsyncMemoryWriter

    store = _ThrowawayMemoryStore()
    writer = AsyncMemoryWriter(memory_store=store, max_queue=100, drainer_concurrency=2)
    await writer.start()

    fake_session = {
        "session_id": "smoke-cp-001",
        "topic": "AAPL momentum next 5 trading days",
        "consensus": "Smoke test consensus — AAPL likely range-bound with options skew bullish.",
        "decision": "Hold, watch for breakout above the 50-day. Council confidence: 0.55.",
        "headline": "AAPL: range-bound, modest bullish skew.",
        "confidence": 0.55,
        "calibrations": [
            {
                "member": "claude",
                "base_rate": 0.40,
                "confidence": 0.55,
                "disconfirmers": ["Earnings beat by >5%", "Fed surprise cut"],
            }
        ],
        "surfaced_conflicts": pack.surfaced_conflicts,
        "citations": [],
        "rounds": [],
        "members": ["claude", "grok", "gemini"],
    }
    wb = await write_back_council(
        async_writer=writer,
        session=fake_session,
        council_type="smoke",
    )
    # Give the drainer pool ~2s to consume the queue
    for _ in range(20):
        await asyncio.sleep(0.1)
        if len(store.persisted) >= 3:
            break
    print(f"writeback gist     : {wb['gist'][:120]}")
    print(f"writeback summary  : {wb['summary'][:200]}")
    print(f"writeback transcript_len: {wb['transcript_len']}")
    print(f"persisted units in store: {len(store.persisted)}")
    for u in store.persisted[:3]:
        # u may be a dict (create_unit kwargs) — show metadata
        meta = u.get("metadata") or {}
        print(
            f"  - tier={meta.get('writeback_tier')} source={u.get('source')} importance={u.get('importance')}"
        )
    await writer.stop()

    print()
    print("=== SMOKE COMPLETE ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
