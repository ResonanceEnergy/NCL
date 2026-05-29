# NCL AWAREBOT Mandate v1.0

**Effective**: 2026-05-29 (Wave 14X-Y)
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Camp**: INTEL (entertainment + verifier pool)
**Owns**: `data/intelligence/`, scoring + tier routing inside `runtime/awarebot/`

---

## 1. Identity

AWAREBOT is the **intel-camp agent**. It scrapes, scores, and surfaces signals about what's happening *outside* NATRIX's portfolio. It is intentionally **loose** — high tolerance for noise — because its job is to be a wide net for organic discovery, sentiment, and verifier-confirmation, not to make trading decisions.

The other camp — **TRADERAGENT** — owns trading decisions and has tight, audit-trailed gates. The two camps share the same NCL data substrate but answer different questions:

| AWAREBOT asks | TRADERAGENT asks |
|---|---|
| What is the world buzzing about today? | What should I trade with NATRIX's capital? |

The bridge between them is the **Cross-Reference Engine** (`runtime/cross_reference/`), which promotes converging AWAREBOT signals into PROMOTED_CANDIDATEs that TRADERAGENT can evaluate. See `docs/CROSS_REFERENCE_MANDATE.md`.

## 2. Mission

> Surface what the world is buzzing about, in a way NATRIX can browse for ideas and TRADERAGENT can mine for converging signals — without flooding either with decision-grade noise.

## 3. Sources + priority order

Per NATRIX's stated priority (2026-05-29):

| Priority | Source | Role | Authority |
|---|---|---|---|
| **#1** | **YouTube Council (YTC)** | Deep-analysis lane — per-video council debate | 0.7 |
| **#2** | **Reddit** | Sentiment lane — retail mood, narrative discovery | 0.5 |
| **#3** | **X / Twitter** | Real-time pulse — PAUSED (subscription) | 0.6 |
| #4 | YouTube (raw scraping) | Channel-watch feeding YTC | 0.5 |
| **#5** | **MARKETS + POLYMARKET** (merged) | Ambient market context | 0.4 |
| #6 | Google Trends | Verifier-only — popularity confirmation | 0.4 (capped) |
| #7 | News (RSS) | Verifier-only — "in the press too?" | 0.5 (cross-ref only) |
| — | Crypto / CoinGecko | DEFER — future XRP/crypto phase | — |
| — | City events | OUT (moved to CALENDAR lane) | — |

## 4. Scoring — 7-factor composite (Wave 14X-Y)

| Factor | Weight | Source |
|---|---|---|
| Context Relevance | 30% | BM25 against watch queries + working-context match |
| Freshness | 20% | HN-gravity decay |
| Cross-Source | 15% | Token overlap with other sources |
| Source Confidence | 15% | Authority + engagement |
| Actionability | 10% | Direction, %change, URL, tags |
| Novelty | 5% | SimHash near-dupe (was 10%, halved for Wave 14X-Y) |
| **Situational Relevance** | **5%** | **NEW** — matches NATRIX's journal/calendar context |

Bands: CRITICAL ≥ 0.75 · HIGH ≥ 0.65 · MEDIUM ≥ 0.30 · LOW < 0.30.

## 5. Pre-gate rules (write-time)

1. Score ≥ 0.30 (LOW band dropped at ingest)
2. HIGH threshold = 0.65 (was 0.55 pre-Wave-14W)
3. CRITICAL threshold = 0.75
4. Authority cap on popularity sources: google_trends ≤ 0.4
5. News-fan-out forbidden (news has no own queries; cross-ref weight only)
6. 24h SimHash fingerprint dedup
7. **Memory write-gate**: signal persists to MemoryStore only on CRITICAL OR cross_source ≥ 2 (everything else stays in `agent_signals.jsonl` rotation)

## 6. Authority ceiling

AWAREBOT signals can never write above `LLM_SINGLE` (40) authority tier. Council-grade content from YTC is exception — it writes at COUNCIL (80).

## 7. Cadence

| Task | Cadence |
|---|---|
| Per-source scan | 5 min (rate-limited per source) |
| YTC dedicated | hourly during YouTube active hours |
| YTC nightshift rollup | 03:00 local nightly |
| Cross-reference scan | 5 min (Wave 14X-Y Phase 1B-3) |

## 8. Cost ceiling

Daily budget: **$5/day** (anthropic share of YTC + signal enrichment). Per `runtime/cost_tracker.py` budget enforcement.

## 9. What AWAREBOT IS NOT

- A trading decision-maker (that's TRADERAGENT)
- A memory store (Memory lane gates writes via Section 5.7)
- A push-notification dispatcher (AlertDispatcher owns that)
- A calendar (Calendar lane owns time-anchored events)

## 10. Failure mode

Quiet INTEL tab — acceptable. AWAREBOT producing nothing means the world is quiet, not that the system is broken. (Compare: TRADERAGENT going quiet pages NATRIX immediately.)

## 11. Version

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-29 | Split from INTEL_MANDATE.md. Codifies AWAREBOT-camp identity, 7-factor scoring with new SITUATIONAL factor, source priority order per NATRIX direction. |
