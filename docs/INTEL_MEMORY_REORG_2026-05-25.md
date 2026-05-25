# Intel + Memory Tab Reorg — Audit & Plan

**Date**: 2026-05-25
**Trigger**: NATRIX flagged the Intel→Brief executive summary as weak. Quick screenshot review surfaced systemic IA problems across Intel (9 sub-tabs) + Memory (4 sub-tabs) that have accumulated over Waves 8-13.
**Scope**: Full audit + ship-now fixes + deferred reorg roadmap.

---

## TL;DR (what's actually broken)

The Intel tab is **one Awarebot signal pool projected through seven redundant lenses**, none of which fully own their layer of the stack. The "executive summary" is degenerate because it's literally the highest-scoring signal's text echoed verbatim. Risk Alerts is `top_signals.filter(level == CRITICAL)` of the SAME list Key Signals reads from, so the two cards are guaranteed to overlap. Memory's PINNED, Intel's FOCUS, and Brief's "Fed by N context signals" are three UI surfaces over the same `DailyContextWindow`. Night Watch produces a daily narrative brief that **no iOS view consumes**.

Three concepts have collapsed into each other:

| Concept | What it actually is | Where it leaks |
|---|---|---|
| **Working Context** | Capped 50-item DailyContextWindow, hot-set prepended to LLM prompts | Memory→PINNED, Brief footer, FOCUS top-cards |
| **Focus (the tier)** | Awarebot's `route_to_tiers()` FOCUSED tier — signals ≥0.75, <4h | Intel→FOCUS, Brief Key Signals |
| **Focus (the config)** | `/focus/queries` + `/focus/subreddits` JSON — what scanners watch | Intel→FOCUS gear, Reddit gear, three editors |

These are **three different things wearing the same word**. Same story for Pinned: signal pins (`POST /memory/working-context/pin` with `signal:<id>`) and memory unit pins (with `mem:<unit_id>`) both write the same `ContextItem.pinned=True`, but iOS keeps a parallel `@AppStorage("intel.pinnedSignalIDs")` shadow so unpinning from Memory→PINNED doesn't update the Intel chip.

---

## Current State Map

### Intel tab — 9 sub-tabs (`IntelView.swift`, 3,341 LOC, 28 `@State`)

| Sub-tab | What it should be | What it currently is | Problems |
|---|---|---|---|
| **Predictions** | Forward-looking ensemble forecasts + accuracy | Topic chips, convergence cards, prediction cards | Convergence section is duplicate prediction list filtered by topic equality. Hardcoded breadcrumb `Sources → Context → Briefs → Predictions` links to nothing. Local regex re-derives `direction` even though backend ships it. |
| **Brief** | Narrative synthesis of "what's happening now" | One-sentence echo of top signal + 3-tile badge row that duplicates the same triple in the header + KEY SIGNALS list + RISK ALERTS that re-filters KEY SIGNALS | `executive_summary` = `briefHeaderLine` = 3-tile badge counts → same data three ways. RISK ALERTS ⊂ KEY SIGNALS guaranteed. "Informs 0 predictions" footer is always 0 on first open. |
| **Focus / FOCUS** | Top-priority actionable signals | Tier-routed cards (rich `IntelSignalCard`) | Duplicates Brief KEY SIGNALS. The word "Focus" also means the config sheet behind the gear icon. |
| **Focus / MICRO** | 24h velocity, grouped by sector/ticker | Same signal pool, grouped | 24h/7d toggle exists only in DEAD `microSection` code path (~600 LOC of redundant rendering across `focusedSection`/`microSection`/`macroSection`/`signalRow`). |
| **Focus / MACRO** | Persistent narratives | Sector-grouped low-velocity signals | Collides with Memory's `narrative_threads` loop output. |
| **YTC** | YouTube council deep-dives | Today / nightshift / past briefs | Same `/councils/reports` files surface under Brief→Council too. Embedded mode duplicates parent tab chrome. |
| **Reddit** | Reddit feed + sub editor + tickers | Embedded sub-app with own picker | Subreddit editor is a 3rd surface (also in FocusContextView gear + RedditView gear). Tickers heatmap = X tickers heatmap with different source. |
| **X** | X feed + accounts + tickers | Same structure as Reddit, always empty | Scanner is 402-disabled (per CLAUDE.md). Three empty sub-sections persist. |
| **Trends / Markets / News** | Per-source readouts | Compact `signalRow` lists | All three use DEAD rendering code. Polymarket loader enriches yes/no/volume fields that the renderer drops. |

### Memory tab — 4 sub-tabs

| Sub-tab | What's there | Problem |
|---|---|---|
| **TIMELINE** | Day-grouped MemoryRow list, `?limit=50` | No pagination, no filters (Search has chips, Timeline doesn't), two API calls per refresh just to color pin badges. |
| **GRAPH** | A second full-screen view-within-a-view — own header, own `FSSectionPicker`, own refresh button. KG stats + entity ranked list + path finder | **The big one.** Two stacked picker strips (pink + green) appear simultaneously. Untyped `[[String: Any]]`. Memory references in entity detail don't open `MemoryDetailView`. |
| **SEARCH** | Smart (fused) / Keyword toggle + source chips | Source filter is CLIENT-SIDE substring match. Smart/Keyword label confuses. No tier/importance/date filter. |
| **PINNED** | Two stacked sections (PINNED + AUTO top-10) | Single endpoint call. Same data the Intel pin chip writes to, with a parallel iOS persistence store. |

### Backend brief generators — three of them, all Sonnet 4

| Source | Length | When used | Notes |
|---|---|---|---|
| `runtime/intelligence/engine.py:1306` | 600 tokens, 6-8 sentences | `IntelBrief.executive_summary`, `/intelligence/latest` | Has "no generic filler" rules + cross-source convergence pre-pass. Best of the three. |
| `runtime/api/routers/intel/__init__.py:471` | 5,000 tokens, 120s timeout, 12-section structured | `POST /intelligence/morning-brief` `full_brief` | What iOS renders via `BriefRenderer`. |
| `runtime/awarebot/agent.py:3093` | 300 tokens, 3-4 sentences | `data/intelligence/agent_briefs.jsonl` (Awarebot's own stream) | What the iOS Brief sub-tab "Past Briefs" reads from. |

All three have a deterministic fallback that walks `top_signals[:3]` and echoes one-line stubs — this is what NATRIX is seeing when the brief feels like "just the top signal again."

### Night Watch — 6 phases, one human artifact, zero iOS exposure

`data/night-watch/daily-YYYY-MM-DD.md` — the only human-readable nightly artifact. Has STATUS GREEN/YELLOW/RED + KEY FINDINGS + COST REPORT + SYSTEM HEALTH + RECOMMENDATIONS sections. NATRIX only sees this via the ntfy push. Phase 6 (Portfolio Analyst) IS surfaced (Portfolio→AGENT tab); Phase 5 (the cross-system Opus synthesis) is invisible.

**Bug found in passing**: `runtime/autonomous/night_watch/analyst.py:481-482` uses `claude-opus-4-6` (non-existent model) and `claude-sonnet-4` (missing `-20250514` suffix). Same class of bug Wave 13 EOD swept for Sonnet but missed for Opus. Today's 2026-05-25 brief hit 4× HTTP 404 because of this.

### Endpoints NOT consumed by iOS (low-hanging fruit)

`/memory/by-authority`, `/memory/budget`, `/memory/conflicts/pending`, `/memory/authority/history/*`, `/memory/ab-test/summary`, `/system/memory-profile`, `/system/health/rollup`, `/predictions/{id}/provenance`. All exist on Brain. Some are ops surfaces, but `/system/health/rollup` and `/predictions/{id}/provenance` are user-meaningful and unused.

---

## The Mental Model the Reorg Restores

There are only **two** things that legitimately deserve separate UI:

1. **NOW** — the live priority feed. Fusion of `DailyContextWindow` + Awarebot tier-routing + signal-card pinning. ONE backing store, ONE scoring pipeline, ONE pin verb. Render as: a single scrollable feed with chips for ≤4h / ≤24h / ≥24h time bands, plus a small "pinned" header row that's always at the top.

2. **WATCH SOURCES** — what should the scanners pay attention to? Pure config (queries + subreddits + accounts). Belongs in Settings, not in the Intel tab.

Everything else is a **rendering** of #1:
- The **Brief / Digest** is a narrative pass over #1 (Sonnet synthesis with explicit dedup-against-prior-call).
- The **Memory tab** is the audit surface for #1 (where did things come from, who said them, when do they decay, how do they connect).
- The **Night Watch brief** is the daily story about how #1 was tended overnight.

The current tabs are projections of this two-thing model that ended up making each projection feel like a separate feature.

---

## Recommended IA (post-reorg)

```
Dashboard       — unchanged (gear icon → Settings → Watch Sources moved here)
Portfolio       — unchanged
INTEL                                  MEMORY
 ├── NOW (was Focus/Brief Key Signals)  ├── BROWSE (timeline + search merged)
 ├── DIGEST (was Brief — synth only)    ├── GRAPH (own first-class home)
 ├── NIGHT WATCH (new)                  └── AUDIT (PII / conflicts / authority history)
 ├── PREDICTIONS
 ├── YTC                                IN SCOPE drawer (was Memory PINNED + Intel pin chips)
 ├── REDDIT                              accessible from gear-icon header from anywhere
 ├── X
 └── SOURCES (Trends + Markets + News merged with source filter)
Calendar / Journal — unchanged
```

Net change: **Intel goes from 9 sub-tabs to 8**, but the redundancy across them drops by ~70% because the dead `signalRow` paths get deleted, the three sources merge, FOCUS/MICRO/MACRO collapse to NOW with chip filters, and the gear sheet moves to Settings. **Memory goes from 4 to 3** because PINNED becomes the global drawer.

---

## Ship-now scope (this session)

The full IA restructure (rename tabs, move gear sheets, kill the AppStorage shadow, merge sources) is multi-day work that should land as its own wave with a fresh build verification pass per change. **This session ships the four highest-value fixes** that match NATRIX's three explicit asks (better exec summary, working context integrated with focus, surface night watch) plus the bugs the audit found while I was in there:

### A. Backend

1. **New `/intelligence/night-watch/{latest,by-date,history}` endpoints** — parse `data/night-watch/daily-*.md` into `{date, status, key_findings, cost_report, system_health, recommendations, raw_appendix, markdown_full}`. iOS renders these as a new NIGHT WATCH section.
2. **Brief dedup at source** — `intel/__init__.py` morning-brief handler dedups `risk_alerts` against `top_signals[:5]` before returning. Adds explicit "different from key signals" semantic — risk_alerts are signals critical AND not already top-N.
3. **Authority filter at brief boundary** — `top_signals` filtered out anything below `LLM_SINGLE(40)` tier when surfacing in the brief callouts. Reddit r/depression posts stop reaching Key Signals. (Configurable via `NCL_BRIEF_MIN_AUTHORITY`, default 40.)
4. **Fix Night Watch analyst.py model IDs** — `claude-opus-4-6` → `claude-opus-4-20250514` (or kill Opus + fall through to Sonnet), `claude-sonnet-4` → `claude-sonnet-4-20250514`. Stops the nightly 4× HTTP 404.
5. **New `/intelligence/digest` endpoint** — single endpoint returning `{headline, summary, key_signals, risk_alerts, working_context_top, night_watch_status, generated_at, source_breakdown}`. Powers a future single-call "what's happening" view; ship the endpoint now even if iOS calls it later.

### B. iOS

1. **New NIGHT WATCH sub-tab in Intel** — STATUS pill (green/yellow/red), KEY FINDINGS bullets, RECOMMENDATIONS bullets, COST + HEALTH chips, "view raw markdown" drawer for the full .md. Calls `/intelligence/night-watch/latest`.
2. **Brief sub-tab cleanup** — Risk Alerts no longer re-filters Key Signals (consumes the deduped backend payload). "Informs N predictions" footer fetches `/predictions` count on view appear (currently relies on session state). Remove the redundant 3-tile badge row that mirrors `briefHeaderLine` (one or the other).
3. **Working-context integration in FOCUS sub-tab** — top of the FOCUS list shows a "FROM CONTEXT" section with the pinned + top-3 unpinned working-context items. Today FOCUS shows tier-routed signals; this lifts the pinned-and-AUTO-salience set into the same view so NATRIX sees "what's in the brain's head" + "what the scanners are surfacing" together.
4. **Fix Brief "Informs 0 predictions"** — fetch `/predictions` on Brief view appear instead of waiting for Predictions tab visit.

### C. What's deferred (next wave)

- Rename FOCUS/MICRO/MACRO → NOW (with chip filters), BRIEF → DIGEST
- Move FocusContextView from gear icon → Settings → Watch Sources
- Kill `@AppStorage("intel.pinnedSignalIDs")` shadow; make server authoritative
- Merge Trends + Markets + News into one SOURCES sub-tab with filter chips
- Pull Memory PINNED into a global drawer accessible from any tab
- Add Memory AUDIT sub-tab consuming `/memory/conflicts/pending` + `/memory/authority/history/*` + `/memory/budget`
- Promote KnowledgeGraphView to a sibling tab of Memory (kill the double-header)
- Unify Awarebot `route_to_tiers()` with Working Context salience into one scorer
- Add `/predictions/{id}/provenance` signal→unit resolver (currently `unit_id: None`)
- Delete dead `signalRow`/`focusedSection`/`microSection`/`macroSection` (~600 LOC)
- Consolidate the three brief generators into one canonical writer

This is a 2-3 wave roadmap. Tracked in this doc; next-wave kickoff should reference these bullets.

---

## File-level change list (ship-now)

**Backend** (`/Users/natrix/dev/NCL/`):
- `runtime/autonomous/night_watch/analyst.py` — fix model IDs
- `runtime/api/routers/intel/__init__.py` — add night_watch endpoints, dedup brief, authority filter, add `/intelligence/digest`
- (optional) `runtime/api/routers/intel/night_watch.py` — extract night_watch endpoints into their own router file if intel router is already too large

**iOS** (`/Users/natrix/Projects/FirstStrike/`):
- `Sources/Models/IntelModels.swift` (or new `NightWatchModels.swift`) — NightWatchBrief struct
- `Sources/Services/NCLBrainClient.swift` — `fetchNightWatchLatest()` + `fetchNightWatchHistory()`
- `Sources/Views/Intel/NightWatchView.swift` — new
- `Sources/Views/IntelView.swift` — add `.nightWatch` enum case + sub-tab pill, fix Brief dedup, fix Informs link, add FROM CONTEXT section to FOCUS body
- `Sources/Models/NCLCommand.swift` — register `night_watch_latest` command id

---

## Wave tag

`Wave 14A — Intel + Memory IA reorg (ship-now slice)`

Next wave when scheduled: `Wave 14B — IA restructure (rename + drawer + merge)`.
