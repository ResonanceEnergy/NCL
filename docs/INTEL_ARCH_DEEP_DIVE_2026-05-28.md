# NCL Intel Architecture Deep-Dive + Reorg Proposal

**Date**: 2026-05-28
**Compiled from**: 3 parallel subagent audits — Awarebot ingest, Working-Context/Focus/Memory overlap, Trading-agent intel consumption.
**Trigger**: NATRIX's concern that "working context, signals, focus, and Awarebot are all competing for the same space" + the vision that "Intel/Memory/Calendar should serve the Portfolio and trading agent."

The short answer: **yes, you're getting in your own way**. There are four scoring systems acting on overlapping inputs, the same underlying signal is written to disk up to 6 times, and 88% of MemoryStore is Awarebot exhaust. The trading agent is a write-heavy emitter, not an orchestrator. The good news: the surfaces NATRIX wants (WC in Intel, Rotation in Portfolio, agent-as-orchestrator) are mostly half-built already.

---

## Part 1 — Quantity audit (the actual data flows)

### Signal volume (last 24h, on disk truth from `agent_signals.jsonl`)

| Source | 24h | Status | Notes |
|---|---|---|---|
| reddit | **3,394** (45%) | LIVE | 55 subs (T1=10 + T2=16 every cycle; T3=29 rotating 5/cycle) + 6 queries; seeds news fan-out |
| options_flow (UW) | **2,385** (32%) | LIVE | also independently feeds /portfolio/options-flow |
| google_trends | 669 | LIVE | authority 0.8 → "denzel washington"-class spikes score HIGH |
| youtube | 372 | LIVE | + per-video council insights |
| polymarket | 316 | LIVE | also read by brief_prep.collect_polymarket_leading direct |
| news | 294 | LIVE | **no own queries** — fans top-3 from each watch-source ⇒ structural cross-source inflation |
| city_events (7 cities sum) | 71 | LIVE | ticketmaster authority 0.6 → "Calgary Transit Hiring event" scores HIGH |
| x_twitter | 0 | DISABLED (402) | 8 queries still in config |
| crypto/coingecko | 0 | DISABLED | rate-limit retired |

**24h total = 7,544 signals**. **Lifetime in file = 18,668 rows (117 MB across active + .1 + .2 rotation).**

### Storage footprint (where each signal lands)

Every routed signal lands in up to **6 places**:

1. Three Awarebot context deques (focused/micro/macro, in-memory)
2. `data/intelligence/agent_signals.jsonl` (117 MB after rotation)
3. `data/memory/units.jsonl` via AsyncMemoryWriter + ChromaDB vector + BM25 + KG
4. `data/intelligence/latest_brief.json` (top-50 subset)
5. `data/memory/narrative_threads.jsonl` (aggregation)
6. `data/night-watch/` dedup ledger

**Concrete proof**: the Polymarket BTC question "Will the price of Bitcoin be above $74,000 on May 28?" appears **64 times in `agent_signals.jsonl` and 54 times in `units.jsonl`**. The fingerprint flips daily (settlement price body changes) so dedup misses it.

**`awarebot:*`-sourced units = 21,747 of 24,770 = 88% of MemoryStore.** Memory grew from 9.7K → 24.7K units in one week, driven almost entirely by Awarebot persists.

### Score distribution (lifetime)

- **CRITICAL ≥0.75** = 1,069 (5.7%)
- **HIGH 0.55-0.75** = 11,235 **(60.2%)** — band has lost discrimination
- MEDIUM 0.30-0.55 = 6,364 (34.1%)
- LOW <0.30 = 0 persisted

Causes of HIGH band compression:
- News fans Reddit/YouTube/X/Trends terms → structural cross-source inflation on every topical hit
- google_trends authority 0.8 + high novelty + freshness fires spurious spikes into HIGH
- city_events ticketmaster authority 0.6 → community events score as intel
- 50/50 BM25↔keyword blend halves the only factor that genuinely discriminates relevance

**Actionable ratio**: of 7,544 24h signals, fewer than **~30 (<0.5%)** are framed enough to back a trade decision. The brief pipeline (Wave 14H council+critic) correctly distills to 6 trade ideas/day, so output quality is OK; the ingest is **99.5% noise carrying weight in cross-source + KG + narrative-thread pipelines**.

---

## Part 2 — Are you "competing for the same space"? Yes, 4 ways.

### 4A. Two scorers on overlapping input, neither wins

**Awarebot 6-factor** vs **WorkingContext salience** are independent scorers fed by overlapping data:

- Awarebot scores `0.30 ctx + 0.20 fresh + 0.15 xsrc + 0.15 auth + 0.10 act + 0.10 nov`
- WC scores `0.25 recency + 0.35 importance + 0.25 relevance + 0.15 auth_floor`

**Live WC today**: **50 of 50 items are `narrative_thread:$TICKER`** aggregations (Wave 13 ncl-narrative-threads loop, 4,241 unit aggregates each, importance ~100). Zero Awarebot signals survived selection. So Awarebot's `_inject_working_context()` call on every HIGH/CRITICAL signal is **dead work** — salience evicts them immediately. The 6am/noon/11pm WC refresh writes a thread-monoculture every time.

### 4B. Focus is mis-positioned in the UI

`/focus/queries` and `/focus/subreddits` are CRUD on `watch_queries.json` — the input config Awarebot reads at scan time. iOS positions Focus as a sub-tab beside Predictions/Brief/YTC, so the user sees it as an output lane (another source) when it's actually the **search terms feeding all sources**.

The iOS Focus sub-tab is doing **three jobs at once**:
1. A tier filter on Awarebot signals (FOCUS = focused green, MICRO = orange, MACRO = blue)
2. A glance at working context items (FROM CONTEXT strip, only in FOCUS sub-mode)
3. A scanner-config editor (gear icon → query + subreddit CRUD)

**This is the root of NATRIX's "competing for space" feeling.**

### 4C. iOS hits both `/intelligence/*` and `/memory/*` for the same data

- 6 of 9 Intel sub-tabs (Brief / Focus / YTC / Reddit / X / News) plus 4 of 4 Memory sub-tabs read slices of the same Awarebot pool, projected differently
- **No surface tells the user "this is the same item you saw on another tab"**
- `/intelligence/digest` (Wave 14A) was built explicitly to be the unified read — iOS still doesn't consume it

### 4D. `brief_prep` is a third independent reader

`brief_prep.collect_headlines` + `collect_polymarket_leading` reach directly into `brain._awarebot._recent_signals` — a third reader alongside Awarebot's own `route_to_tiers` and the MemoryStore signal pull.

### Plus: Working context is broken today, not just misplaced

- CLAUDE.md says WC salience weights are 0.30/0.40/0.30; code is **0.25/0.35/0.25 + 0.15 authority floor** — doc drift
- 50 of 50 WC items are `narrative_thread:$TICKER` rows at saturated salience=1.00
- 0 pinned items
- 14 of 15 themes are opaque `thread:UUID` strings (useless for relevance)
- Memory→PINNED currently shows the same data as Intel→Focus's "FROM CONTEXT" strip with different chrome

---

## Part 3 — Trading agent intel consumption: a passive receiver

### Per-tick gate chain (15 stages)
cycle_watcher (every 60 ticks ≈ 1hr) → drawdown_bucket → state.is_active → day-cap → tracker fetch → **sanity_gate** → risk_governor → **calendar_gate** → **working_context_gate** → policy.auto_open_eligible → tax_sizing → **beta_cap** → **sector_cap** → friction → council_check (only if effective_R ≥ $1000) → paper.create_trade → reasoning_chain + memory write.

### Push vs Request asymmetry

| Direction | Count | Mechanism |
|---|---|---|
| Pushed TO agent | 5 streams | trade_idea_tracker (poll), portfolio_manager (NAV file), working_context (file), calendar_agent (file), rotation/cycle (file) |
| Agent PUSHES back | 1 channel | `brief_context_packet()` — 530 chars in next morning brief's executor prompt. **That's the entire feedback surface.** |
| Agent REQUESTS ad-hoc | **0** | No request bus exists. Capability registry only deduped-emits importance-95 MemUnits to the operator. |

**The agent has 18 `create_unit` write sites and ZERO `fused_search` read sites.** It writes about every decision but never queries its own prior failure memory.

### Facilities that EXIST but the agent never invokes

- `brain.memory_store.fused_search` / `by_authority` / KG query — agent could search its own prior loss clusters, never does
- `POST /memory/working-context/pin` — agent could pin `auto_trader:drift_detected:bravo` so next brief sees it explicitly, never does
- `brain.spawn_council_session` — exists for `/pump` ingest, agent never calls
- `POST /intelligence/rotation/fire` — agent could self-heal stale cycle file, never POSTs
- `POST /council/queue` — Memory-tab "Council This" button exists, agent never uses

### NATRIX's vision gaps (capabilities that don't exist)

| Vision capability | Status |
|---|---|
| Agent → Awarebot "scan now for X" | NOT BUILT. Awarebot.run() is a closed scheduler loop. No `awarebot.request_scan(query, urgency)` entry point. |
| Agent → Calendar "block 3pm for review" | NOT BUILT. CalendarAgent is read-only producer. |
| Agent → Memory "fused-search prior tech losses" | API exists; agent never calls. |
| Agent → Scheduler "fire ad-hoc council at 9:30am" | `POST /council/queue` exists; no auto-trader caller. |
| Agent → Brief "regenerate with focus on Y" | `POST /intelligence/morning-brief/pro/fire` is manual-only. |
| Drift → contrarian council debate | drift_detector terminates at MemUnit. Council never spawned. |
| Research topic → automatic deep dive | research_topics.json sits until operator resolves. |
| Capability gap → self-heal | finnhub gap just sits there; no retry, no fallback. |

---

## Part 4 — Proposed reorganization

### 4.1 The information architecture problem in one diagram

```
TODAY:                                                         PROPOSED:
─────────────────────────────────────                         ────────────────────────────────
INTEL    Brief / Focus / Reddit / X / YT       INTEL          RIGHT NOW (digest)
         / Trends / News / Markets /                          AGENDA (working context + pins)
         PREDICTIONS                                          ROTATION ──► moves to PORTFOLIO

MEMORY   Timeline / Graph / Search / PINNED    MEMORY         Timeline / Graph / Search
         (← WC ends up here today)                            (PINNED becomes Intel→AGENDA)

CALENDAR 7DAY / 30DAY / TODO / CITIES /        CALENDAR       (unchanged)
         MOON / SUN

PORTFOLIO PORTFOLIO / AGENT / PAPER /          PORTFOLIO      + ROTATION sub-tab
          GOAT / BRAVO / OPTIONS / CRYPTO /                   (sector RRG, breadth, cycle phase
          PLYMKT                                              under the same tab as positions)

JOURNAL  Quiz / Life / Write / Search /        JOURNAL        (unchanged)
         Tips / Insights
```

**The wiring is half-built already**:
- Intel→FOCUS sub-mode already loads `/memory/working-context` and renders "FROM CONTEXT" header strip (`IntelView.swift:222`)
- `/intelligence/digest` already returns `working_context_top` field
- Memory→PINNED currently duplicates Intel→Focus's FROM CONTEXT strip with different chrome
- `/intelligence/rotation` and `RotationRRGView` already exist; just need to render them under Portfolio instead of (or in addition to) Intel

### 4.2 Decouple the four overlapping systems

| System | Today | Proposed role | Action |
|---|---|---|---|
| **Awarebot** | Scans + scores + routes + writes 6 places | **Just** scans + scores + emits to Intel cache | Stop double-writing to MemoryStore; persist to memory only on CRITICAL or cross_source ≥ 2 |
| **Working Context** | 6am/noon/11pm assemble, 50-item cap, currently 100% thread-monoculture | **Agent agenda**: NATRIX pins + active research topics + open trades + today's priorities (NOT a top-N memory list) | Fix narrative-thread monoculture (per-source diversity cap + demote thread aggregate importance from 100→60) |
| **Focus** | 3 jobs in one tab: tier filter + WC strip + scanner-config editor | **Just** Awarebot tier display (HOT/WARM/COOL) | Move scanner-config CRUD to Settings; move WC strip to Intel→AGENDA |
| **Memory** | Long-term storage + 4 dashboard sub-tabs + accidentally hosts WC | **Just** retrieval substrate | Memory→PINNED becomes user-pins-only (no top-N WC display) |

### 4.3 The unified intel-request bus for the trading agent

NATRIX's core ask: the agent should be able to **request** services from Awarebot/Memory/Calendar/Scheduler/Council rather than just receive what they push. The pattern:

```
agent.intel_request(
    kind="memory.fused_search",
    query="prior $XLE energy breakouts H4",
    max_results=20)

agent.intel_request(
    kind="awarebot.scan_now",
    focus="energy sector last 60min",
    urgency="high")

agent.intel_request(
    kind="council.spawn",
    reason="drift_detected:bravo",
    topic="Why is bravo strategy losing edge?",
    panel="delphi_mad_4")

agent.intel_request(
    kind="calendar.add_followup",
    when="today 15:00 ET",
    payload={"review_topic_id": "topic:tech_breakout_review"})

agent.intel_request(
    kind="brief.regenerate_focus",
    focus_ticker="XLE",
    reason="live opportunity flagged")
```

One dispatcher (`runtime/agent_bus/intel_request.py`), six handlers (one per kind), bounded fire-and-forget so request failures never break the tick loop.

---

## Part 5 — Wave 14W backlog (ordered by leverage)

### Architectural cleanup (P0 — fixes the "competing for space" problem)
1. **Fix narrative-thread monoculture in WC** — per-source diversity cap in `_pull_from_memory`, demote thread aggregate importance from 100 → 60. Without this, moving WC to Intel just relocates a broken view. ~30 LOC.
2. **Move WC display from Memory→PINNED to Intel→AGENDA** — adopt `/intelligence/digest` for the unified read. Memory→PINNED becomes user-pins-only. ~150 iOS LOC.
3. **Move Rotation/RRG widget from Intel→Rotation sub-tab to Portfolio→Rotation sub-tab** — wire alongside positions where it informs sizing. ~100 iOS LOC.
4. **Move Focus scanner-config CRUD from Intel→Focus gear to Settings→Watch Plan** — leaves Intel→Focus as a clean Awarebot tier filter. ~80 iOS LOC.

### Quality cleanup (P1 — fixes the noise problem)
5. **Stop Awarebot's `_inject_working_context()` on HIGH/CRITICAL** — salience evicts them anyway; saves CPU and clarifies WC semantics. ~10 LOC.
6. **Persist to MemoryStore only on CRITICAL or cross_source ≥ 2** — cuts MemoryStore growth ~10x. ~20 LOC.
7. **Drop `news`-as-derivative source + lower google_trends authority 0.8 → 0.4 + remove city_events from Awarebot** (they belong in Calendar). Shrinks HIGH band from 60% to ~40%. ~30 LOC.
8. **Raise HIGH threshold 0.55 → 0.65** — restores discrimination. ~5 LOC.

### Agent-as-orchestrator (P1 — fixes the passive-receiver problem)
9. **Build `runtime/agent_bus/intel_request.py`** — unified dispatcher with 6 handlers (memory.fused_search / awarebot.scan_now / council.spawn / calendar.add_followup / brief.regenerate_focus / scheduler.queue). ~300 LOC.
10. **Wire `drift_detector` DRIFT_DOWN to spawn a contrarian council debate** instead of terminating at MemUnit. ~20 LOC.
11. **Wire `generate_research_topics` cluster creation to auto-spawn a fused-memory search + Awarebot focused scan + Sonnet research synthesis writing back as `resolution_notes`**. ~150 LOC.
12. **Wire `cycle_watcher` phase transition to spawn a rotation-snapshot manual refresh + 1 council debate "what changes in {new_phase}?"**. ~50 LOC.
13. **Wire `capability_registry` gap detection to attempt self-heal** (env hint via memory, fallback provider attempt, retry+backoff). ~80 LOC.

### Wiring (P2 — closes loops)
14. **Adopt `/intelligence/digest` in iOS Intel→RIGHT NOW** as the single read. ~50 iOS LOC.
15. **Show one badge per signal** ("rank N in Focused" / "cited in Brief" / "memory thread $TICKER") so the user sees one item = one underlying signal. ~80 iOS LOC.
16. **Pin a flag like `auto_trader:drift_detected:bravo` in WC** so next brief sees it explicitly without going through SHAP. ~10 LOC.

---

## Part 6 — Does it make sense? Yes.

**The vision is correct and most of the surfaces NATRIX wants are half-built**:
- WC moving to Intel = correct because Intel→FOCUS already loads `/memory/working-context`; we just need to delete the duplicate Memory→PINNED display
- Rotation moving to Portfolio = correct because it informs sizing decisions, not signal browsing
- Intel/Memory/Calendar serving the agent = correct because the agent is currently a passive consumer of files; promoting it to an orchestrator that requests services is the architecturally right move
- Trading agent able to request council/queries/tools/memories/intel/research = correct because all the underlying capabilities exist; they just aren't dispatchable

**The "getting in our own way" feeling is real**:
- 4 scorers on overlapping inputs (Awarebot 6-factor, WC salience, Memory authority, focus_tiers)
- Same signal stored 6 times
- iOS Intel tab fragments same data across 9 sub-tabs
- Memory tab grew 88% Awarebot-exhaust
- Brief 15h stale by default, no live single read endpoint adopted

**The cleanest reorg path**:
1. Fix WC narrative-thread monoculture (otherwise moving it doesn't help)
2. Move WC display Memory→Intel + Rotation Intel→Portfolio
3. Reduce Awarebot's storage write fanout
4. Build the unified intel-request bus so the agent can be an orchestrator instead of a polling consumer

Once these four moves land, the four-systems-competing problem becomes one system (intel) with one consumer (the trading agent) and one storage (memory). Everything else is presentation.

---

## Sources

- [outputs/audit_awarebot.md](computer:///Users/natrix/dev/NCL/outputs/audit_awarebot.md) — Awarebot architecture + signal volume
- [outputs/audit_wc_focus_memory.md](computer:///Users/natrix/dev/NCL/outputs/audit_wc_focus_memory.md) — WC + Focus + Memory overlap
- [outputs/audit_trading_agent_intel.md](computer:///Users/natrix/dev/NCL/outputs/audit_trading_agent_intel.md) — Trading agent intel consumption
- [docs/FULL_SYSTEM_AUDIT_2026-05-28.md](computer:///Users/natrix/dev/NCL/docs/FULL_SYSTEM_AUDIT_2026-05-28.md) — Prior tab-level system audit
