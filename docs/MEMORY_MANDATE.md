# NCL Memory Lane Mandate v1.0

**Effective**: 2026-05-28
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Lane**: MEMORY — recall anything NATRIX or the trading agent has decided is worth remembering.
**Owns**: `data/memory/` (units.jsonl, chromadb/, knowledge_graph/, working_context/, bm25_index/)

---

## 1. Identity

Memory is the **permanent retrieval substrate**. It is NOT the Intel cache (that's the Intel lane, time-bounded), NOT a duplicate of journal/portfolio (cross-references only), and NOT the same thing as Working Context (WC is today's agenda; Memory is everything ever).

Memory's job is to answer: *"NATRIX or agent — recall X from when?"*

If a recall is needed beyond 7 days, it must be in Memory. If it cannot be recalled, it should not have been written.

## 2. Capacity

| Metric | Value |
|---|---|
| Max units in store | 25,000 (was 10K pre-Wave 13; raised to stop eviction thrashing) |
| Current count (audit baseline) | ~24,770 → target ≤ 15,000 post Wave 14W |
| Authority tiers | 7 — NATRIX 100 / COUNCIL 80 / BRAIN 60 / CALENDAR 50 / LLM_SINGLE 40 / SCANNER 20 / RAW 10 |
| Memory types | 7 — semantic / episodic / procedural / signal / decision / preference / default |
| Decay | LML 0.999/day (facts, decisions, preferences, procedures) ; SML 0.95/day (signals, episodes) |

## 3. Write-time gate (THE KEY POLICY)

A write attempt is **rejected** unless ONE OF:

1. **Authority tier ≥ COUNCIL (80)** — Council outputs are always preserved
2. **NATRIX-tier write** (importance ≥ 95) — operator-emitted directly
3. **Composite score ≥ 0.75** — CRITICAL Awarebot signals only
4. **Cross-source ≥ 2** — Awarebot signals confirmed by ≥ 2 independent producers
5. **Operator explicit pin** via `POST /memory/working-context/pin`
6. **Trading-agent reasoning chain** — per-decision audit (CFTC Reg AT-grade)
7. **Journal entry with importance ≥ 50** — non-ephemeral journal content
8. **AutoTrader close event** at importance 80
9. **Cycle phase transition** memory unit at importance 90
10. **Portfolio significant move** at importance ≥ 85

Everything else stays in its source lane only. This is the **memory-gate-at-write** rule that fixes the 88%-awarebot-exhaust problem.

## 4. Promotion paths into Memory

| Source lane | Promotion trigger | Importance |
|---|---|---|
| Intel | CRITICAL signal | 65-85 |
| Intel | cross_source ≥ 2 | 60 |
| Intel | operator pin | 75 |
| Portfolio | AutoTrader open | 75 |
| Portfolio | AutoTrader close | 80 |
| Portfolio | Significant move (>3% NAV daily) | 85 |
| Portfolio | Cycle phase transition | 90 |
| Journal | Entry with importance ≥ 50 | 50-100 (echo) |
| Calendar | Never (calendar IS recall; use the calendar tab) | — |

## 5. Working context (WC) is part of Memory lane

WC is the assembled subset of Memory loaded for today. It is NOT a separate lane. It IS:

- A daily-rolling 50-item view assembled at 06:00 / 12:00 / 23:00 ET
- Salience-scored = `0.25·recency + 0.35·importance + 0.25·relevance + 0.15·authority`
- Pinned items survive day rollover (`_carry_forward_pinned`)
- Themes extracted from high-importance recent units

**Wave 14W-B fix**: per-source diversity cap so `narrative_thread:$TICKER` aggregations stop monopolizing 100% of slots. Demote thread aggregate importance 100 → 60.

WC's UI surface lives in the **Intel** lane (Intel→AGENDA), not the Memory lane (Memory→PINNED becomes user-pins-only after Wave 14W-D).

## 6. Consumer contracts

### 6.1 iOS Memory tab
- **TIMELINE** ← `GET /memory/timeline` (recent units, source-family-capped)
- **GRAPH** ← `GET /memory/knowledge-graph/*` (NetworkX visualization)
- **SEARCH** ← `GET /memory/search/fused` (vector + BM25 + KG)
- **PINNED** ← `GET /memory/working-context?pinned_only=true` (after Wave 14W-D, this is the only WC display in Memory tab)

### 6.2 Trading agent
- **READ via fused-search** (NEW Wave 14W-E): `intel_request("memory.fused_search", q=...)` returns relevant prior decisions, losses, council outputs
- **READ via by-authority**: `intel_request("memory.by_authority", min_tier=council)` for high-trust context
- **WRITE on every decision**: reasoning chain at importance 75 (open) or 80 (close)
- **WRITE on cycle change**: importance 90

### 6.3 Morning brief
- Reads top recent memory units via `_pull_from_memory(themes=...)` for context packet
- Cites unit_ids in citations when the brief references prior episodes

## 7. Cadence

| Task | When |
|---|---|
| Memory consolidation | Hourly (`ncl-memory`) |
| ChromaDB reindex | After consolidation |
| BM25 rebuild | Every 30min (`ncl-bm25-rebuild`) |
| Working context assemble | 06:00 ET (full), 12:00 ET (refresh), 23:00 ET (EOD reinforce) |
| Knowledge graph entity prune | Hourly |
| Memory eval (50 Q/A regression) | Sun 03:00 ET |
| Async writer drain | Continuous (4 drainers) |
| Staleness re-verification | 6h (importance ≥ 70 facts) |
| Narrative threads | 6h (cap aggregations at importance 60 per Wave 14W-B) |

## 8. Governance

| Action | Authority | Mechanism |
|---|---|---|
| Manually create unit | NATRIX | `POST /memory/store` |
| Manually pin/unpin | NATRIX | `POST/DELETE /memory/working-context/pin` |
| Hard-delete unit | NATRIX | `DELETE /memory/unit/{id}` (rare; use cautiously) |
| Promote tier | NATRIX | `POST /memory/retag-authority` (already used Wave 13) |
| Adjust write-gate thresholds | NATRIX | env vars `NCL_MEMORY_GATE_*` |
| Force refresh WC | NATRIX | `POST /memory/working-context/refresh` |
| Force assemble WC | NATRIX | `POST /memory/working-context/assemble` |

## 9. Audit + Self-* obligations

The Memory lane IS:
- **Self-decaying**: two-speed FadeMem (LML/SML)
- **Self-deduping**: conflict resolver + fingerprint
- **Self-evicting**: salience floor + max-capacity LRU
- **Self-attributing**: every unit carries `authority_tier` and provenance
- **Self-evaluating**: weekly 50 Q/A regression eval against held-out test set
- **Self-redacting**: PII redactor on every write (10 patterns + Tailscale-IP allowlist)
- **Self-aware of cost**: budget tracker per tier

The Memory lane IS NOT:
- An Intel cache (Intel signals only land here if they earn it via Section 3)
- A Journal echo (journal entries bridge here at importance ≥ 50, not always)
- A Calendar archive (Calendar lane owns its events)
- A Portfolio history (Portfolio lane owns broker positions + paper trades)

## 10. Coherent goal (one sentence)

> Recall anything NATRIX or the agent has decided is worth remembering — gated at write so nothing earns slot it doesn't deserve.

If a write fails the gate (Section 3), the source lane must handle storage itself. Memory is a privilege, not a default.

## 11. Version + audit

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-28 | NATRIX + NCL Wave 14W-A | Initial Memory lane mandate; codifies write-time gating |

Ingested as procedural memory at importance 95 (NATRIX tier) on every Brain boot.
