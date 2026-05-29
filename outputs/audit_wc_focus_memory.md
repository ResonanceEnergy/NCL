# Audit — Working Context / Focus / Memory / Awarebot

Date: 2026-05-29. Live read against `http://100.72.223.123:8800`. Code paths inspected:
`runtime/memory/working_context.py`, `runtime/memory/authority.py`, `runtime/memory/dashboard_bridge.py`,
`runtime/api/routers/memory.py`, `runtime/api/routers/intel/__init__.py` (focus block @ L2769–2962),
`Sources/Views/Memory/{MemoryView,MemoryPinnedView,MemorySearchView,MemoryTimelineView,MemoryDetailView}.swift`,
`Sources/Views/IntelView.swift`.

---

## 1. Working Context — what it is today

### Pull sources (six explicit pulls in `assemble()` at `working_context.py:506-669`)

| # | Method | What it ingests | Live count today |
|---|--------|-----------------|------------------|
| 1 | `_pull_from_memory(themes)` | `MemoryStore.search_units(importance>=30, days_back=7)`, caps at 100 candidates | 100 |
| 2 | `_pull_from_councils()` | Council reports under `intelligence-scan/council-reports/*.json` over last 48h, summary + top-5 insights each | 20 |
| 3 | `_pull_from_signals()` | Three sub-streams: alert JSONs (`intelligence-scan/alerts/*.json` last 24h), latest intel brief top-8 signals, today's morning brief topics | 20 |
| 4 | `_pull_from_mandates()` | `data/mandates.json` rows with status in `(in_progress, pending, approved)` | 0 (mandate file empty of active rows) |
| 5 | `_carry_forward_pinned(today)` | Yesterday's pinned + items above CARRY_FORWARD_THRESHOLD=0.40 | 0 (no pins) |
| 6 | `_pull_portfolio_candidates(max=6)` | Latest `portfolio:snapshot` + top 5 `portfolio:*` events from MemoryStore | (counted within memory pull) |

Result today: **146 candidates → 50 selected** (cap is `MAX_CONTEXT_ITEMS=50`, floor `MIN_SALIENCE_SCORE=0.25`).
`assembly_stats={memory:100, council:20, signal:20, mandate:0, carried:0, avg_salience:0.6}`.

### Salience formula — `compute_salience()` at `working_context.py:411-439`

```
base     = α·recency + β·importance + γ·relevance      # in [0, α+β+γ] = [0, 0.85]
salience = base · authority_weight + 0.15 · authority_weight
```

The CLAUDE.md doc's stated weights (0.30/0.40/0.30) are **wrong**. Real constants in code:
`ALPHA_RECENCY=0.25, BETA_IMPORTANCE=0.35, GAMMA_RELEVANCE=0.25, AUTHORITY_FLOOR=0.15`. Authority floor
is multiplied through (a NATRIX dud at recency=importance=relevance=0 still scores `0.15·1.0=0.15`,
beating a scanner peak at `(0.85·0.2)+(0.15·0.2)=0.20` only when authority gap is wide).

### Cap + refresh schedule

- `MAX_CONTEXT_ITEMS=50` hard cap, lowest-salience non-pinned items evicted on overflow.
- `MIN_SALIENCE_SCORE=0.25` floor (pinned items always pass).
- Lifecycle loop = `ncl-working-ctx` (3x daily): 6am assemble, noon refresh, 11pm EOD.
- EOD reinforces accessed items (`unit.importance *= 1.15`), penalizes untouched (`*= 0.85`).
- Carry forward: pinned OR salience >= 0.40 survives day rollover.

### Where iOS surfaces it

**Memory tab → PINNED sub-tab** (`MemoryPinnedView.swift`). Single fetch `MemoryAPI.workingContext`
which calls `GET /memory/working-context`. Renders two sections: items where `pinned==true` (sorted
by `pinned_at` desc), and the top-10 unpinned by salience under header "CURRENT WORKING CONTEXT".

**Also already in Intel → FOCUS sub-mode** (`IntelView.swift:222, 2351-2363`). The
`focusWorkingContext` `@State` array loads the SAME endpoint, takes `pinned + top-3 unpinned`,
caps at 8, and renders inside the Focus body as a "FROM CONTEXT" header strip above the
focused-signals list. **This was the Wave 14A pre-work** for the migration NATRIX is asking about
— the surface already exists, it's just duplicated in Memory→PINNED.

### Live state today

```
date=2026-05-29  total_items=50  pinned_count=0  themes_count=15  avg_salience=0.60
by_category={'memory': 50}     # all 50 items are category=memory
top_sources (each =1):
   narrative_thread:$AI, $NVDA, $BTC, $TSLA, $GME, $AMD, $ETH, $MSFT,
   $AMZN, $US, $PLTR, $PATH, $INTC, $XRP, $TSM …
salience: min=1.00 median=1.00 max=1.00
themes: ['council_youtube', 'thread:c03f47c2-…', 'thread:2b4cbbcb-…',
         'thread:f88b695a-…', …]  (14 of 15 are opaque thread:UUIDs)
authority_tier_dist: {'?': 50}   # tier never projected onto the wire
```

**Monoculture finding**: the Wave-13 `narrative_threads.py` loop has so dominated MemoryStore
(thread tags account for 6 of the top-10 tags in /memory/stats, each at 4,241 occurrences)
that every memory pull surfaces `narrative_thread:$TICKER` units at importance ~100, which
saturates salience at 1.00. Council reports (20 candidates) + signals (20 candidates) collected
but **none made the cut**. Mandates always 0 since file rows lack active status. Themes are
mostly thread UUIDs — useless for relevance scoring of new content.

This is the actual user pain. WC today shows 50 thread-ticker stubs, not "what NATRIX is working on".

---

## 2. Focus — what it is today

`GET /focus/queries` and `GET /focus/subreddits` (`intel/__init__.py:2803-2829`) both read
`watch_queries.json` from disk and shape it for iOS.

### Live state

```
queries.x:        8   (e.g. "AI automation business revenue", "prediction markets Polymarket")
queries.youtube:  6   (e.g. "AI business automation 2026", "crypto trading strategies algorithmic")
queries.reddit:   6
subreddits.tier_1: 10  (wallstreetbets, Superstonk, options, stocks, StockMarket, …)
subreddits.tier_2: 16  (thetagang, amcstock, DeepFuckingValue, investing, …)
subreddits.tier_3: 29  (ethereum, CryptoMoonShots, economics, economy, …)
last_updated: 2026-05-17     # static editor file, not derived from runtime
```

### Wiring

`/focus/queries` and `/focus/subreddits` are **edit endpoints for the scanner config**:
- `_save_watch_queries_to_disk` + `_reload_awarebot_queries` after any mutation push the
  new list into `Awarebot._watch_queries` at runtime.
- Awarebot's per-source scan loops iterate these lists every cycle. So Focus IS Awarebot's
  scan plan.

### iOS surface

Intel tab → FOCUS sub-tab (`IntelView.swift:248-251, 614-742`). Three-button mode picker:
- **FOCUS** mode → renders `focusWorkingContext` strip + focused-tier signals from
  `/context/focused`, with a gear icon opening `FocusContextView` (the watch-queries editor
  sheet).
- **MICRO / MACRO** modes → load from `/context/{micro,macro}`.

So "Focus" the tab is **really three things at once**:
1. A tier filter on Awarebot signals (FOCUS = green tier, MICRO = orange, MACRO = blue)
2. A glance at working context items (FROM CONTEXT strip, only in FOCUS sub-mode)
3. A scanner-config editor (gear icon → query + subreddit CRUD)

### Overlap with Awarebot's source list

Yes, complete and intentional: the T1/T2/T3 subreddit tiers ARE the list Awarebot iterates.
The X / YouTube / Reddit search queries are the same queries Awarebot's per-source scan loops
execute. Focus is not "another data source" — it's the editor for Awarebot's mandate.

---

## 3. Memory store — the layer below

Live `/memory/typed-stats` + `/memory/stats`:

```
total_units: 24,770  (CLAUDE.md says 25K cap, 24,144 backfill figure — drifting up)
by_tier (memory_tier, FadeMem two-speed): LML=2,725  SML=22,045
by_type: signal=19,912 (importance 52)
         episodic=2,471 (63)
         semantic=2,090 (94)   <-- highest avg importance
         procedural=141 (69)
         decisions=75 (70)
         decision=29 (52)      <-- two type buckets, schema drift
         preference=52 (45)

ChromaDB collections: episodic=2,474 semantic=2,089 procedural=141
                      signal=19,916 decision=29 preference=52 default=97

avg_importance: 57.09

top source frequencies:
   awarebot:reddit          10,769
   awarebot:options_flow     4,545
   council:youtube:insight   1,809
   awarebot:google_trends    1,670
   awarebot:youtube          1,088
   awarebot:city_events:*    1,793 (4 cities)
   awarebot:polymarket         612
   awarebot:news               346
   scanner:goat                200
   scanner:bravo               198
```

7-tier authority (`authority.py`): NATRIX(100) / COUNCIL(80) / BRAIN(60) / CALENDAR(50) /
LLM_SINGLE(40) / SCANNER(20) / RAW(10) — applied multiplicatively on salience. Fused retrieval
(vector + BM25 + KG via RRF) backs `/memory/search/fused`.

The store is dominated by **awarebot:reddit (43%) + awarebot:options_flow (18%) +
awarebot:city_events:* (7%)** = 68% pure scanner ingestion. The high-trust semantic-type bucket
is only 2,090 units — but it's the one with avg importance 94. That's where briefs, predictions,
and reflections land.

---

## 4. iOS surface map

| Tab | Sub-tab | Backend endpoint | Underlying subsystem |
|-----|---------|------------------|----------------------|
| Memory | TIMELINE | `GET /memory/timeline` → `dashboard_bridge.get_timeline` | MemoryStore full scan, source-diversity cap |
| Memory | GRAPH | `GET /memory/knowledge-graph/{top-entities,stats,entity/...,path}` | NetworkX KG (31K+ nodes / 54K+ edges) |
| Memory | SEARCH | `GET /memory/search/fused` (Smart) or `POST /memory/search` (Keyword) | FusedRetriever / SQLite units_index |
| Memory | PINNED | `GET /memory/working-context` | **WorkingContext (DailyContextWindow)** |
| Intel | PREDICTIONS | `GET /predictions` | predictor + R-series writer |
| Intel | BRIEF | `GET /intelligence/morning-brief` (P14D fallback) + `/morning-brief/pro` | Wave 14H 3-stage pipeline |
| Intel | NIGHT WATCH | `GET /intelligence/night-watch/latest` | nightly maintenance brief |
| Intel | ROTATION | `GET /intelligence/rotation` | Wave 14I capital rotation RRG |
| Intel | FOCUS · FOCUS submode | `/context/focused` + `/memory/working-context` (FROM CONTEXT strip) | Awarebot focused tier + WC |
| Intel | FOCUS · MICRO/MACRO | `/context/{micro,macro}` | Awarebot tier routing |
| Intel | FOCUS · gear sheet | `GET/POST/DELETE /focus/{queries,subreddits}` | watch_queries.json editor → reload Awarebot |
| Intel | YTC | `GET /youtube/reports/recent` | YTC dedicated loop |
| Intel | REDDIT | `POST /intelligence/reddit/run` | Awarebot reddit scan |
| Intel | X / TRENDS / MARKETS / NEWS | `sourceSection(source="...")` | per-source signal lists |

Notable existing rollups not yet consumed by iOS:
- `GET /intelligence/digest` — Wave 14A built this as the single read for "what's happening right
  now". Live today: `{headline, summary, key_signals(8), risk_alerts, working_context_top(10),
  night_watch_status, source_breakdown}`. iOS still calls 4-5 endpoints to assemble the
  same view.

---

## 5. Overlap analysis — the actual concern

### Is Intel→FOCUS conceptually the same as Memory→PINNED?

**Largely yes.** Both surface "what's on the brain right now". Specifically:

- Memory→PINNED renders the full 50-item working-context window with explicit pins on top.
- Intel→FOCUS (FOCUS sub-mode) already renders a 8-item FROM CONTEXT strip ABOVE focused signals,
  drawn from the SAME `/memory/working-context` endpoint.

The conceptual difference is supposed to be: PINNED shows the durable "my brain's day", FOCUS
shows "the agent's currently-hot lens onto my brain". But because they both read the same
WC and there's no distinct datatype, users see identical content with different chrome.

### Is FOCUS really an editing tool for the scanner list, not an intel surface?

In its third sub-form (gear icon → `FocusContextView` sheet) — **yes, exclusively config**. The
endpoints under `/focus/*` are CRUD for `watch_queries.json`, not an intel feed. The Wave-14A-EOD
redesign moved this off the main Focus body into a gear sheet, but it's still wired up.

So "Focus" the tab name now refers to three different things:
1. Awarebot tier filter (signals routing layer)
2. Working-context preview (memory layer)
3. Scanner config editor (Awarebot mandate layer)

### Does WC try to do the job of BOTH "active research priorities" (Intel) AND "things you've pinned for later" (Memory)?

**Yes**, and the live data shows it failing both:
- As "active research priorities" — themes are 14/15 opaque `thread:UUID` strings; categories are
  100% memory; salience saturated at 1.00. No signal of what's actually "active".
- As "pinned for later" — pinned_count=0. The cross-day reinforcement mechanism is intact but
  pinning is the user gesture nobody is making (the pin chip is buried in Intel signal cards and
  Memory→TIMELINE; PINNED tab itself shows the gesture-receiver, not the gesture).

### Where is the conceptual boundary that's blurry?

Five layers all overlap on "what should I look at":

| Layer | Lives in | What it represents |
|-------|----------|--------------------|
| **Awarebot tier routing** | `runtime/awarebot/` | scored signals; one of {focused, micro, macro} |
| **Watch queries / subreddits** | `watch_queries.json` (focus endpoints) | the mandate scanners execute |
| **WorkingContext daily window** | `runtime/memory/working_context.py` | top-50 salience selection of memory+council+signal+mandate+portfolio |
| **Pinned items (subset of WC)** | same `today.json` with `pinned=True` | what user explicitly kept |
| **Memory store** | `data/memory/units.jsonl` | the 24,770-unit pool everything draws from |

The boundary that's blurry: **WC** simultaneously claims to be "today's research agenda" (via
themes + auto-extracted from candidates) AND "your durable pin board" (via `_carry_forward_pinned`
+ EOD reinforcement). Today it's serving neither well because the narrative-thread crowding
collapsed both signals.

---

## 6. iOS surface friction — why "WC should be in Intel"

NATRIX is right, and here's the concrete why:

**Memory→PINNED conflates two things the user thinks of separately.** The PINNED tab shows the
50-item WC (top 10 unpinned + all pinned). Today that's 50 `narrative_thread:$TICKER` rows with
no pins. To the user this looks like a generic "interesting memory recently" list — not their
pin board.

**Memory tab is the "look back" tab.** TIMELINE / GRAPH / SEARCH are all retrospective: what's
in the brain, where it came from, find an item. Sticking the "what to think about today" view
inside that tab makes it feel passive. It also competes with TIMELINE for the same slot in the
user's head.

**Intel tab is the "look forward / look out" tab.** Predictions, briefs, focus signals, rotation
regime, night watch. WC fits this mental model — it's the brain's current agenda. And the wiring
is half-built: `focusWorkingContext` already loads the same payload inside Intel→FOCUS as a
FROM CONTEXT strip. The Wave 14A backend (`/intelligence/digest` returning `working_context_top`)
was the architectural prep for exactly this move.

**Memory→PINNED currently shows things that should live elsewhere:**
- Narrative threads → belong in Memory→GRAPH (they're a knowledge-graph concept)
- High-importance recent units → belong in Memory→TIMELINE (chronological view)
- Council insights from last 48h → belong in Intel→BRIEF or Intel→PREDICTIONS
- Active mandates → belong in Dashboard / Strike Point workspace
- Portfolio events → already in Portfolio tab

The genuine "pin board" surface (explicit user pins) is small enough to live as a header strip
inside Intel→FOCUS (where it already does). The remaining 40 items in WC are auto-curated and
should drive scanner relevance under the hood, not be shown as a list.

---

## 7. Top 3 reorg recommendations

### Reco 1 — Move WC display into Intel, redefine Memory→PINNED as "user pins only"

- Delete the WC monoculture list from Memory→PINNED. Replace with **only** items where
  `pinned==true` AND with explicit cross-day intent. Today that's zero, and that's fine — the
  empty state should say "Pin a memory unit from Timeline/Search/Intel to keep it here."
- Promote Intel→FOCUS's existing `focusWorkingContext` strip from the FOCUS sub-mode header
  into a dedicated **Intel→AGENDA** sub-tab (or fold into BRIEF). Render all 50 WC items with
  category badges + salience + themes — that's what NATRIX actually wants the Intel tab to show.
- iOS work: swap MemoryPinnedView's data source from `/memory/working-context` to a filtered
  `pinned==true` slice; add IntelView.IntelSection.agenda case backed by the same endpoint.
- Backend: zero change needed — `/memory/working-context` already exposes pinned-only filter
  client-side, and `/intelligence/digest` is the rollup if we want a denser surface.

### Reco 2 — Rename "Focus" tab to disambiguate the three jobs

The word "Focus" is doing three jobs (Awarebot tier filter + WC preview + scanner editor) and
nobody can name the contents from the tab name. Concretely:

- Rename Intel→FOCUS to Intel→**LENS** (or **SCAN**). The three sub-modes become tier filters:
  HOT (focused/green) / WARM (micro/orange) / COOL (macro/blue). That's all this section is.
- Move the gear-sheet (`FocusContextView` watch-queries editor) to **Settings → Scanner Plan**.
  It's config, not intel.
- Move the FROM CONTEXT strip out (it goes to AGENDA per Reco 1).
- This separates: scanned-signal viewer (Intel→LENS), agenda viewer (Intel→AGENDA),
  scanner-plan editor (Settings → Scanner Plan).

### Reco 3 — Fix the WC monoculture before any surface move

Whatever surface WC lives on, today it's broken: 50/50 items are `narrative_thread:$TICKER`
at salience 1.00. Root cause is `narrative_threads.py` writing 4,241-unit threads at importance
~100 with `narrative_thread:$AI` style sources. Two surgical fixes:

- In `working_context.py::_pull_from_memory`, add a per-source diversity cap (mirror the
  `dashboard_bridge.get_timeline` family-prefix selector). Cap any single source family at
  5/cap of MAX_CONTEXT_ITEMS so narrative threads can't crowd out councils/signals/portfolio.
- Tag `narrative_thread:*` sources with `BRAIN(60)` in `authority.py::SOURCE_TIER_MAP` (today
  they fall through to RAW(10) but the importance=100 floor overrides the authority weight).
  Better: demote thread aggregates to importance 50 in `narrative_threads.py` itself — they're
  meta-aggregates, not first-order facts.
- Also: `themes` should drop `thread:UUID` from the extraction (already filters
  `auto_ingested/autonomous/intelligence_signal/council_report/council_insight/high/medium`;
  add `narrative_thread` and `thread:`).

Without this, moving WC to Intel just relocates the broken view.

---

### Appendix — quick code pointers

- WC salience constants: `runtime/memory/working_context.py:75-86`
- WC pulls + assembly: `working_context.py:506-669`
- WC pin endpoint (with auto-promote): `runtime/api/routers/memory.py:1071-1135`
- Focus CRUD: `runtime/api/routers/intel/__init__.py:2803-2962`
- Intel FROM CONTEXT strip: `Sources/Views/IntelView.swift:217-222, 2322, 2351-2363, 2511-2530`
- Memory→PINNED full: `Sources/Views/Memory/MemoryPinnedView.swift` (entire file, 238 LOC)
- Authority tier map: `runtime/memory/authority.py:98-214`
- Live digest rollup (Wave 14A, not yet consumed): `runtime/api/routers/intel/__init__.py` →
  `/intelligence/digest`
