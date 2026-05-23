# Council Context Assembler — Design Doc

Status: PROPOSED · 2026-05-23 · awaiting NATRIX scope approval

## Problem

Today every "Council" button (Prediction · Signal · Brief · Journal · Ticker) hits `/council/spawn` with a thin prompt (topic + 500 chars). The council debates blind. Result: shallow conclusions that ignore memory, ignore prior councils on the same topic, ignore disagreeing signals, fail to cite sources, and produce no feedback signal for source-quality learning.

NATRIX intent: every Council convene should first sweep all available memory + intel, build the most coordinated relevant evidence pack, then convene with full context. Same behavior across every Council button in the app.

## Solution overview

One module — `runtime/council/context_assembler.py` — sits between every convene surface and the council orchestrator. It produces a JSON `council_pack` and the runner fans the pack to N members in parallel, runs anonymized peer review, then synthesizes.

```
┌─────────────────────────────────────────────────────────────────────┐
│  CONVENE SURFACES (iOS)                                             │
│  · Prediction card · Signal card · Brief card · Journal entry       │
│  · Ticker · Portfolio event · Calendar event                        │
└────────────────────────────┬────────────────────────────────────────┘
                             │  POST /council/spawn { trigger, trigger_id }
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ContextAssembler.assemble(trigger, trigger_id) → council_pack      │
│                                                                     │
│  1. Anchor entity extraction (what's THE subject)                   │
│  2. Cross-session memory sweep (FusedRetriever — vec+BM25+KG+RRF)   │
│  3. MMR diversity rerank (λ=0.5)  ◄── kills echo chamber            │
│  4. Pull recent: signals (4h+7d), briefs, predictions, journal,     │
│     portfolio events, calendar events                               │
│  5. Surface conflicts from contradicts_index.jsonl                  │
│  6. Pull prior councils on same/adjacent topic + their outcomes     │
│  7. Detect narrative threads (entity + 6h windows)                  │
│  8. Force base rates (Tetlock superforecaster discipline)           │
│  9. Compress if pack > 30K tokens (MapReduce per section)           │
│ 10. Stamp citation IDs on every evidence item                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │  council_pack JSON
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CouncilRunner — Karpathy 3-stage pattern                           │
│  Stage 1: Parallel fan-out (Claude · Grok · Gemini · GPT · Perp)    │
│           — each gets pack + structured-output schema               │
│  Stage 2: Anonymized peer review (strip model labels, members rank) │
│  Stage 3: Chairman synthesis (Claude with full transcript)          │
└────────────────────────────┬────────────────────────────────────────┘
                             │  decision + cited evidence + verbalized conf
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Hierarchical write-back (Reflexion/H²R pattern)                    │
│  · 1-line takeaway → working_context                                │
│  · 200-token summary → semantic memory                              │
│  · Full transcript → episodic memory                                │
│  · Citations recorded → outcome feedback loop                       │
└─────────────────────────────────────────────────────────────────────┘
```

## council_pack JSON schema

```python
{
  "topic": "TSLA Q3 guidance miss reaction",
  "trigger_id": "prediction-abc123",
  "trigger_type": "prediction",        # prediction|signal|brief|journal|ticker|portfolio
  "convened_at": "2026-05-23T10:00:00Z",
  "anchor_entity": "TSLA",
  "anchor_tickers": ["TSLA"],
  "anchor_sectors": ["automotive", "energy"],

  "base_rates": [
    {"question": "S&P 500 post-earnings drift", "prior": 0.62, "source_id": "memory:bf04...."},
    {"question": "TSLA earnings-day vol", "prior": 0.34, "source_id": "memory:7d12...."}
  ],

  "evidence": [
    {
      "id": "signal:8a3f4...",
      "source": "polymarket",
      "content": "TSLA above $400 by EOM 2026 at 31%",
      "timestamp": "2026-05-23T09:14:00Z",
      "authority_tier": 85,
      "salience": 0.78,
      "stance": "supports"                     // supports|refutes|orthogonal
    },
    ...
  ],

  "conflicts": [
    {
      "claim": "Tesla margins improved Q3",
      "supporters": ["memory:abc...", "signal:xyz..."],
      "refuters":   ["memory:def...", "brief:rst..."]
    }
  ],

  "narrative_threads": [
    {
      "name": "TSLA robotaxi reality-check arc",
      "summary": "Brighter with Herbert + J Bravo + 2 reddit threads
                  flag scaling-claim gap between marketing + delivered units.",
      "member_ids": ["signal:...", "signal:...", "memory:..."]
    }
  ],

  "prior_councils": [
    {
      "session_id": "council-2026-05-18-...",
      "topic": "TSLA Q2 reaction",
      "consensus": "near-term bear, long-term bull on autonomy",
      "outcome": "PARTIAL: bear played out 3 days, bull thesis still pending",
      "lesson": "Don't conflate near-term sentiment with long-term tech adoption"
    }
  ],

  "hot_window_4h": "...",          // §4 of research recommendations
  "narrative_arc_30d": "...",      // §4 of research recommendations

  "budget": {"pack_tokens": 18432, "budget_remaining": 11568},
  "compression_applied": false
}
```

## What you might be missing (research findings, May 2026)

| # | Concept | Why it matters | NCL has it? |
|---|---|---|---|
| 1 | **Citation grounding** — every claim cites a `memory_unit_id` or `signal_id` | Anthropic reports source-hallucination drops 10% → 0% with their Citations API | NO |
| 2 | **Conflict surfacing** before debate (ConRAG/MADAM-RAG) | Members engage disagreement instead of reproducing it | PARTIAL (contradicts_index exists but unused) |
| 3 | **Source diversity** (MMR/DIVERGE) before packing | Stops the "all 5 sources agree because they paraphrase" failure | PARTIAL (MMR shipped in tier router, not in retrieval) |
| 4 | **Calibrated verbalized confidence + forced base rates** | RLHF models are systematically miscalibrated — verbalized "90% confident" is usually wrong; forcing base rates first (Tetlock) cuts ECE | NO |
| 5 | **Anonymized peer review round** (Karpathy stage 2) | Removes model-identity bias, prevents Claude from deferring to GPT just because GPT spoke first | NO |
| 6 | **Hierarchical write-back** (Reflexion/H²R) | Next council benefits from this council's reasoning; 3 tiers: 1-line takeaway + 200-token summary + full transcript | NO |
| 7 | **Outcome → authority feedback** | When prediction resolves, ±1 weight on cited sources; closes the loop the Beta-Bernoulli learner was built for | NO (learner exists, no feedback signal yet) |
| 8 | **Temporal split** — hot 4h + narrative arc 30d as SEPARATE sections | Models attend better when recency and persistence are not blended | NO |
| 9 | **Position trick** — most-critical evidence at start AND end of context | Mitigates "lost in the middle"; works even on Claude 4 | NO |
| 10 | **40% context utilization rule** | Performance degrades past ~40% of context window; rest is for reasoning | NO (we don't measure) |
| 11 | **Universal entry-point** for every convene surface | One assembler + one council runner instead of bespoke prompt per surface | NO |
| 12 | **MapReduce compression** when pack exceeds budget | Per-section parallel summary by Sonnet, then merge | NO |

## Phased implementation

### Phase 0 — Immediate (shipped today)

- iOS PredictionDetailView Council button: fixed endpoint + surfaced result toast. (NCL commit pending; FirstStrike `75be499`.)

### Phase 1 — Quick wins (~2-3 hrs)

1. Inline a small `_assemble_context()` helper inside `runtime/council/runner.py` that runs before the existing prompt builder:
   - Top-15 FusedRetriever hits on anchor entity
   - Recent signals from awarebot tier buffers
   - Conflicts pulled from `contradicts_index.jsonl`
2. Stamp signal/memory IDs in the evidence list; require members to cite IDs in output (structured-output schema).
3. MMR rerank (already in `mmr.py`) on the FusedRetriever output before packing.

### Phase 2 — Full MVP (~3-5 days, recommended)

4. New `runtime/council/context_assembler.py` as the single entry-point producing the §2 `council_pack` JSON.
5. Refactor `/council/spawn` to accept `(trigger_type, trigger_id)` and call assembler before runner.
6. iOS: every Council button across the app emits `{trigger_type, trigger_id}` instead of bespoke prompts.
7. Karpathy 3-stage runner: parallel fan-out → anonymized peer review → Chairman synthesis (replaces current single-shot per-member).
8. Hierarchical write-back: each council produces 1-line + 200-token + full-transcript memory units.

### Phase 3 — Strategic (~2 weeks)

9. Outcome → Beta-Bernoulli authority feedback (Phase 1 of the learner already attached, just needs the hook).
10. MapReduce compression for packs > 30K tokens.
11. Verbalized confidence + base-rate forcing in member prompt schema; 9-axis member scoring (TurQUaz 2025).
12. Late chunking on council transcripts via Jina v3.
13. Cross-council pattern recognition (Reflexion meta-memory).

## Open questions for NATRIX

1. **Scope** — Phase 1 only, Phase 2 (recommended), or Phase 3?
2. **Trigger types** — Beyond Prediction/Signal/Brief, do you want Journal entries, Ticker symbols, Portfolio events, and Calendar events to spawn councils too? Or stay focused on the intel surfaces?
3. **Async vs sync** — Today /council/spawn is fire-and-forget. With context assembly + 3-stage runner, end-to-end is 30-90s. Do you want iOS to wait (with progress UI) or kick off async + push notification when ready?
4. **Cost cap** — Full 3-stage Karpathy + Sonnet enrichment runs ~$0.15-0.30 per council. At 10 councils/day that's $1.50-3/day on top of current Anthropic spend. Acceptable?

## References

Full source citations are in the deep-research result from 2026-05-23 (45+ papers/blogs cited including Anthropic Citations API, MADAM-RAG, ConRAG, Karpathy llm-council, Reflexion, H²R, Anthropic multi-agent research system, Zep/Graphiti, AuthorityBench).
