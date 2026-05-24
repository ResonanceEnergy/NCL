# Council Architecture — Current State + Migration Roadmap

**Last updated**: 2026-05-23 (Wave 3 — Agent B remaining-surface routing)
**Status**: 4 parallel council systems exist in this repo. **Wave 3 closed the migration — all 4 surfaces now route through `council_pack` first with full fallback.** The 3 redundant systems are still standalone for now; prune is queued as the next wave once burn-in confirms no regressions.

---

## TL;DR — Which System Owns What

| Call site | Routes through | Implementation under the hood |
|-----------|----------------|-------------------------------|
| `POST /pump` (iOS pump → strike-point auto-flow) | **council_pack** (Wave 2) | `ncl_brain/council.py` (CouncilEngine, Delphi-MAD) |
| `POST /council/spawn` (manual convene) | **council_pack** (Wave 2) | `ncl_brain/council.py` (CouncilEngine, Delphi-MAD) |
| `_council_auto_loop` (autonomous trigger) | **council_pack** (Wave 1) | `ncl_brain/council.py` (CouncilEngine, Delphi-MAD) |
| `POST /council-runner/run` (v1 alt API) | **council_pack** (Wave 3) | Pack chair → synthetic `CouncilRunRecord` (legacy `run_parallel_council` is the fallback) |
| YouTube per-video council rollup (autonomous loop + `POST /councils/run`) | **council_pack** (Wave 3) | Pack chair synthesis around `synthesize_rollup` (legacy is fallback) |
| X liked-video council | **council_pack** (Wave 3 best-effort) | `analyze_posts` runs as canonical extractor, pack-augmenter runs alongside for calibration + write-back |

**Rule**: `council_pack` is the *wrapper* — assembles the universal pack, runs the calibration parse, peer-review round, and 3-tier write-back. The *underlying engine* that actually calls the LLMs is `ncl_brain/council.py` (CouncilEngine). The pack runner piggybacks on `council_engine.spawn_session() + run_debate()` — it does not replace them.

---

## The 4 Systems

### 1. `runtime/ncl_brain/council.py` — CouncilEngine (Delphi-MAD)
**Status**: **KEEP** — this is the only system that actually dispatches to the LLM APIs (`_call_claude`, `_call_grok`, `_call_gemini`, `_call_perplexity`, `_call_gpt`, `_call_copilot`) and has the Ollama fallback path.

- ~1,500 LOC
- 6-member roster with role assignments (CHAIR / STRATEGIST / ANALYST / RESEARCHER / CREATIVE / ENGINEER)
- Multi-round debate (POSITION → REBUTTAL → CONSENSUS → SYNTHESIS)
- Cost-gated per call (`check_budget("anthropic", 0.25)`)
- Persistence: brain owns `council_sessions: OrderedDict`, file-backed at `data/council_sessions.json`

### 2. `runtime/council_runner/` — Parallel Planner/Skeptic/Risk + Replay
**Status**: **CONSOLIDATE** — has its own store (`CouncilRunStore`, file-backed JSONL), its own RAG, its own replay engine. Useful pieces:
- `replay.py` (re-run a past session against new evidence)
- `store.py` (queryable history with provenance)

Hot path used today: `POST /councils/run` and `GET /councils/runs` (routes.py:4790, 4905).
Recommendation: harvest `replay.py` + `store.py` into `council_pack` (or `ncl_brain/`) as helpers, then retire the rest of the directory.

### 3. `runtime/councils/` — YouTube + X intel councils
**Status**: **CONSOLIDATE WITH CAUTION** — these are *domain-specific* (per-video transcript analysis, per-liked-video deep dive). They directly write to `council:youtube:*` and `council:x:*` source-tagged units. The actual debate is single-Claude (Sonnet 4) rather than multi-LLM, so the pack overhead may not pay off here.

Recommendation: leave alone for now (Wave 3+). When migrating, pass the transcripts as `pack.document_blocks` via the Anthropic Citations API so quotes are character-anchored back to the source.

### 4. `runtime/council_pack/` — Universal Context Pack (this PR's primary wrapper)
**Status**: **KEEP** — this is the canonical entry point.

Twelve fixes shipped together (May 2026):
1. Citation grounding via Anthropic Citations API
2. Conflict surfacing from `contradicts_index.jsonl`
3. MMR diversity over candidates
4. Temporal split (LAST 4H HOT / 30D NARRATIVE ARC)
5. Calibrated verbalized confidence + base-rate forcing
6. Anonymized peer-review round (Karpathy stage 2) — **wired Wave 2**
7. Hierarchical 3-tier write-back (gist / summary / transcript)
8. Outcome → authority feedback (Beta-Bernoulli)
9. Position trick (top-3 duplicated at start AND end)
10. 40% context utilization cap
11. Universal entry point (this module)
12. MapReduce compression for >30K-token packs

Public API: `runners.run_council_with_pack(...)` is the one function every Council surface should call.

---

## Wave 2 — Routing Pass (Agent 07)

4-of-4 surfaces routed: 2 in Wave 2, +2 in Wave 3 (Agent B).

| File | Change |
|------|--------|
| `runtime/ncl_brain/brain.py` | Added `_run_council_with_pack_or_fallback()` helper mirroring `scheduler._run_council_with_pack_or_fallback`. `receive_pump_prompt(auto_flow=True)` now calls the pack path instead of bare `spawn_council_session`. On ANY exception falls back to the legacy path so the production pump pipeline NEVER regresses. |
| `runtime/api/routes.py` | `POST /council/spawn` now calls `brain._run_council_with_pack_or_fallback()` instead of bare `spawn_council_session`. |
| `runtime/council_pack/runners.py` | Added `peer_review: bool = True` (and `peer_review_targets: int = 2`) kwargs to `run_council_with_pack`. When enabled, runs `run_peer_review_round` post-debate; critiques + tag map land in `session_dict["peer_reviews"]` and the return dict. Adapter `_dispatch_member(name, prompt)` resolves string member-name → `CouncilMember` enum and calls `council_engine._get_member_response_safe`. |

Verification: `python3 scripts/smoke_council_pack.py` passes end-to-end on real data (`data/memory/units.jsonl`) — pack assembles, 8 conflicts surfaced, write-back persists 3 tiers (gist / summary / transcript).

---

## Wave 3 — Remaining Surfaces (Agent B)

Two final surfaces routed through `run_council_with_pack`. Both wrap with full fallback so legacy behavior is preserved on ANY pack-path failure.

| File | Change |
|------|--------|
| `runtime/api/routes.py:4789` | `POST /council-runner/run` body now runs the pack path first. The pack session is projected into a synthetic `CouncilRunRecord` (one `AgentOutput` per pack member, consensus + provenance from pack) so `_council_store.save_run()` + `/council-runner/runs`/`/replay`/`/search` continue to work unchanged. Falls back to `run_parallel_council(topic, prompt)` on any failure. New `import time` added at top of file. |
| `runtime/councils/runner.py` | Added 3 helpers: `_build_pack_runtime()` (best-effort runtime accessor — pulls `brain.council_engine`, `memory_store`, `FusedRetriever`, `get_async_writer()`, `get_learner()` — returns `(None,...)` when not in-process so CLI invocations gracefully fall through), `_run_youtube_rollup_with_pack_or_fallback()` (replaces the cross-video rollup synthesis in `run_youtube_council` — chair synthesizes via pack with calibration + peer review + 3-tier write-back, falls back to legacy `synthesize_rollup` on failure), and `_run_x_pack_augmenter()` (called after `analyze_posts` returns — runs pack augmentation alongside, never blocks the canonical report). The per-video analysis loop in `run_youtube_council` is unchanged — only the rollup synthesis was wrapped. |

**Wave 3 Agent A note**: Citations API plumbing into `_call_claude` is being patched in parallel by Wave 3 Agent A. When that lands, every pack-routed council surface (now all 4) automatically picks up Citations grounding for free — no further changes needed on the routing side. The `pack.document_blocks` already flow through `runners.run_council_with_pack`; they're just dropped at `_call_claude` until Agent A's patch.

---

## Known Gap — Citations API Document Blocks NOT Reaching the LLM

**Location**: `runtime/ncl_brain/council.py:723` (`CouncilEngine._call_claude`).

The assembler produces `pack.document_blocks` in the exact shape the Anthropic Citations API wants:

```python
{
    "type": "document",
    "source": {"type": "content", "content": [{"type": "text", "text": "<verbatim>"}]},
    "title": "<unit_id>",
    "context": "authority:COUNCIL | recency:hot_4h | source:...",
    "citations": {"enabled": True}
}
```

But `_call_claude` accepts only a string prompt and sends it as:

```python
"messages": [{"role": "user", "content": prompt}]
```

The string-only path strips the document blocks. As a result:
- The Citations preamble in the assembler's prompt text DOES travel to the model.
- The structured `document_blocks` DO NOT — they're built and then dropped.
- `parse_citations(response_json)` always returns `[]` because no citation annotations come back.

**Why we didn't fix this in Wave 2**: `_call_claude` is shared by 4 rounds × 5 members × every active call site. Changing its signature to accept `content` blocks would touch every `_get_member_response*` path and risks breaking the Ollama-fallback shape (Ollama doesn't speak Citations). Owed to its own PR with proper testing.

**Wave 3 fix shape**:
1. Add `_call_claude_with_documents(prompt: str, documents: list[dict]) -> tuple[str, dict]` returning `(text, raw_response_json)`.
2. Plumb `pack.document_blocks` from `runners.run_council_with_pack` through `council_engine.run_debate(session, documents=pack.document_blocks)` to `_get_member_response_safe(member, prompt, session_id, documents=...)`.
3. Branch inside `_get_member_response`: Claude path uses the new doc-aware call; non-Claude members keep the string-only path (they don't speak Citations).
4. Return `response_json` from the Claude call so `runners.py` can pass it to `parse_citations(response_json)` and surface the per-claim citations in write-back.

---

## Migration Roadmap — Remaining Moves for the Next Agent

Ordered by impact / risk. Wave 3 Agent B (this pass) ticked off items #2 + #4 from the previous roadmap; Agent A is shipping item #1 in parallel. The remaining items are renumbered below.

1. ~~**Plumb `pack.document_blocks` into `_call_claude`** (the Citations gap above).~~ **In-flight (Wave 3 Agent A).** When it lands, every pack-routed surface (all 4) auto-picks up Citations grounding. Estimated diff: ~80 LOC across `council.py` + `runners.py`. Regression test asserts the response carries `citations[]` annotations.

2. ~~**Migrate `POST /councils/run` to the pack runner**.~~ **DONE — Wave 3 Agent B.** `routes.py:4789 run_council_runner` now routes through `run_council_with_pack` first; pack session projects into a synthetic `CouncilRunRecord` for v1 store compatibility. Falls back to `run_parallel_council` on any failure.

3. ~~**Run the YouTube council through `council_pack`**.~~ **DONE — Wave 3 Agent B.** The cross-video rollup in `runtime/councils/runner.py:run_youtube_council` is now pack-routed via `_run_youtube_rollup_with_pack_or_fallback`. Per-video Sonnet calls in `councils/youtube/analyzer.py:analyze_single_video` are unchanged (separate work item — see #5 below). X council has a best-effort pack augmenter alongside `analyze_posts`.

4. **Retire `council_runner/`** once #1 is in burn-in. Move `replay.py` + `store.py` into `council_pack/`, delete the rest of the directory, drop the 4 imports from `routes.py:139-142`. The synthetic `CouncilRunRecord` projection in `/council-runner/run` will need to be reworked to write into whichever store lands in `council_pack/`.

5. **Pack-route the per-video YouTube analysis** (`councils/youtube/analyzer.py:analyze_single_video`). This is the natural fit for Citations API — feed each transcript chunk as `pack.document_blocks` so the model returns character-anchored citations back to specific transcript lines. Deferred to after item #1 lands so the wire format is settled.

6. **Delete the `_dispatch_to_ncc()` vestigial sink** in `brain.py` and the `PillarType.NCC` enum value. They're dead code post-Strike-Point-merger (see CLAUDE.md:35-43). Not strictly a council change, but it's lurking in `brain.py` next to the council pump path and confuses anyone reading the file.

7. **Retire `runtime/councils/` shared infra** once #5 is done. The directory will be down to scrapers + transcribers + report writers; the council debate part will be fully owned by `council_pack`. Move scrapers/transcribers into a new `runtime/intel_scrapers/` module and delete the rest.

---

## Quick Reference — How To Call A Council Now

**Recommended (Wave 2+)**:
```python
session = await brain._run_council_with_pack_or_fallback(
    topic="...",
    prompt="...",
    trigger="my_caller",
    members=None,  # full council
    session_id=None,  # auto-generated
)
```

**Legacy (still works, no pack improvements)**:
```python
session = await brain.spawn_council_session(topic, prompt, members)
```

**Direct pack call (when you want the full return dict, not just the session)**:
```python
from runtime.council_pack import run_council_with_pack
result = await run_council_with_pack(
    council_engine=brain.council_engine,
    topic=...,
    base_prompt=...,
    fused_retriever=fused,
    working_context=...,
    learner=get_learner(),
    async_writer=get_async_writer(),
    peer_review=True,
)
# result: {session, pack, calibrations, peer_review, peer_review_tag_map, writeback}
```
