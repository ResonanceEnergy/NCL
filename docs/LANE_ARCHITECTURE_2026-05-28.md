# NCL Lane Architecture — pre-organization, pre-gating, coherent mandates

**Date**: 2026-05-28
**Trigger**: NATRIX — "i am the other consumer. ensure the ui gets served as well. do we have categories? do we have a lane for portfolio/intel/memory/calendar/journal? are we organizing? pre-organizing? memory gating? pre-gating? i want coherent goals and mandates."

This doc answers each question directly first, then specs what should be true.

---

## Part 1 — Direct answers

### Do we have categories?

**Sort of, useless.** The `Signal` dataclass has a `category: str` field but it is:
- A **freeform string** (no enum, no validation)
- Source-derived (`"news"`, `"options_flow"`, sometimes a YouTube insight category)
- **Not used for destination routing** — nothing checks `if category == X: route_to_lane_Y`
- Not displayed to the user

So categories exist as a tag in the data but mean nothing in practice. **No.**

### Do we have a lane for Portfolio / Intel / Memory / Calendar / Journal?

**No, we have one big pool and 5 readers.** All Awarebot signals land in:
- `_recent_signals` deque (in-memory)
- `agent_signals.jsonl` (disk)
- `units.jsonl` via MemoryStore (disk + Chroma + BM25)

Then 5 separate consumers each scan the pool and pick out what they think is theirs:
- iOS Intel tab → reads `/intelligence/signals/top`, `/context/{focused,micro,macro}`
- iOS Memory tab → reads `/memory/search/fused`, `/memory/timeline`
- iOS Calendar tab → reads `/calendar/*` (a separate pool entirely; calendar IS its own lane)
- iOS Portfolio tab → reads `/portfolio/*` (a separate pool entirely; portfolio IS its own lane)
- iOS Journal tab → reads `/journal/*` (a separate pool entirely; journal IS its own lane)
- Trading agent → reads the pool + working_context + tracker + scanner pools
- Morning brief → reads the pool via `brief_prep`

Calendar / Portfolio / Journal are clean lanes today because they have their own producers + their own storage + their own consumer. **Intel and Memory are not lanes — they're two overlapping projections of the same Awarebot pool.**

### Should we have lanes?

**Yes.** Lanes solve the "competing for space" problem at the source. Today every consumer competes for the same scarce attention budget (the user's eyes, the agent's tick budget) and each one re-sorts the pool independently. If every signal is **routed to exactly one primary lane at ingest**, the four-overlapping-systems problem goes away.

### Are we organizing?

**Not at the producer side.** Every Awarebot scan dumps into one undifferentiated pool. Organization happens at the **consumer side**:
- Working context salience formula
- Intel tier routing (focused/micro/macro)
- Brief planner (mode selection + section selection)
- Trading-agent gate chain (15 stages)

This is **post-organization**, and it's why the system feels overloaded: each consumer pays the full sorting cost on every read. The user pays it as cognitive load (9 Intel sub-tabs all showing slices of the same pool).

### Are we pre-organizing?

**No.** There is no `LaneRouter` at ingest. A signal does not get stamped with "this is INTEL-lane / memory:permanent" or "this is PORTFOLIO-lane / agent:high-priority" before it hits storage. **This is the highest-leverage thing missing.**

### Are we memory-gating?

**Partially, wrong end.** Today's memory gating happens at *retrieval*:
- `working_context._pull_from_memory()` queries with `importance >= 30 AND days_back=7`
- `/memory/by-authority?min_tier=council` filters at read
- `FusedRetriever` ranks and RRF-blends at read

What we **don't do**: gate at *write*. Every Awarebot signal at importance ≥ 30 (the floor) gets written, regardless of whether it will ever be read. **88% of MemoryStore is Awarebot exhaust** because the gate is on the wrong end of the pipe.

### Are we pre-gating?

**No.** Awarebot scores → routes → writes. There's no "should this even be persisted?" decision separate from the score. The Wave 14V research notes proposed gating at write ("persist to memory only on CRITICAL or cross_source ≥ 2") — that's pre-gating and it's not built yet.

### Do we have coherent goals and mandates per lane?

**Calendar yes, Portfolio yes, Journal yes, Intel no, Memory no.** Calendar's mandate is clear (events + lunar + local + watchlist). Portfolio's is clear (broker positions + NAV + agent activity). Journal's is clear (NATRIX's writing + reflections + quizzes + life plan). But:
- **Intel's mandate is "show everything Awarebot saw, projected 9 ways"** — that's not a mandate, that's a default
- **Memory's mandate is "all units ever, organized 4 ways"** — same problem

The deep-dive (commit `545a5e8`) called these out. This doc gives each lane an explicit mandate.

---

## Part 2 — The 5-lane architecture (proposed)

Each lane has 4 things: **purpose**, **producer mandate**, **consumer mandate**, **pre-gate rules**. The trading agent and NATRIX-as-UI-user are equally first-class consumers.

### LANE 1 — PORTFOLIO

**Purpose**: the state of NATRIX's money. What is owned, what was traded, what the agent is doing with it.

**Producer mandate**:
- Broker adapters (IBKR, Moomoo, SnapTrade, NDAX, MetaMask, Polymarket) sync positions + NAV
- PaperTradingEngine writes paper trades, opens/closes, R-multiples
- AutoTrader writes decisions, reasoning chains, paper opens
- Scanners (GOAT, BRAVO, quant suite) write trade ideas

**Consumer mandate**:
- iOS Portfolio tab → live NAV + positions + agent state + paper trades + scanner results + rotation widget
- Trading agent → reads NAV, positions, paper-trade state
- Morning brief → reads NAV + held positions

**Pre-gate rules**:
- Broker syncs always pass (source of truth)
- Trade ideas must carry stop + target + R + thesis + source citations (already enforced)
- Reject ideas with `score < 50` at scanner level (don't pollute the lane)

**Owns**: `data/portfolio/`, `data/paper/`, `data/portfolio/auto_trader/`
**Mandate file**: `docs/AUTO_TRADER_MANDATE.md` (already exists, Wave 14U)

### LANE 2 — INTEL

**Purpose**: what's happening **right now** outside NATRIX's portfolio that he should know about. Time-bounded, action-oriented, distinct from long-term memory.

**Producer mandate**:
- Awarebot collects from 8 sources, scores, routes
- Rotation tracker writes sector RRG + style ratios + cycle phase
- Brief Pro produces a daily synthesized read at 06:00 ET
- IntelligenceEngine writes predictions

**Consumer mandate**:
- iOS Intel tab → RIGHT NOW (digest) + AGENDA (working context) + drill-down sources + PREDICTIONS + YTC + ROTATION-LIVE-FEED
- Trading agent → consumes `brief_context_packet` (push) + `intel_request("awarebot.scan_now")` (pull, NEW)
- Morning brief → consumes its own production yesterday

**Pre-gate rules**:
- Awarebot at ingest: score 6-factor; **HIGH band threshold 0.55 → 0.65** (tighten); drop `news`-as-derivative (it inflates cross-source on every topical hit)
- Lower google_trends authority 0.8 → 0.4 (popularity, not editorial)
- **Remove city_events from Awarebot entirely — they belong in CALENDAR lane**
- Stop `_inject_working_context()` from Awarebot — WorkingContext is a different lane

**Owns**: `data/intelligence/`, `data/rotation/`, `data/morning-brief-pro/`, `data/predictions/`
**Mandate file** (proposed): `docs/INTEL_MANDATE.md` — needs writing

### LANE 3 — MEMORY

**Purpose**: what NATRIX (or the agent) should be able to **recall**. Permanent retrieval substrate. NOT a duplicate of what's already in Intel/Portfolio/Calendar/Journal.

**Producer mandate**:
- Promote-on-demand from any other lane (`POST /memory/working-context/pin`)
- Council outputs at importance 80 (COUNCIL tier)
- Journal entries (importance 50-100 depending on type)
- AutoTrader closures at importance 80
- **Awarebot signals ONLY when**: CRITICAL (≥0.75) OR cross_source ≥ 2 OR explicitly promoted

**Consumer mandate**:
- iOS Memory tab → Timeline / Graph / Search / **user-pins only** (working-context display moves to Intel→AGENDA)
- Trading agent → `intel_request("memory.fused_search", q=...)` (NEW; currently 0 read sites)
- Morning brief → consumes for context packet

**Pre-gate rules** (the heart of the redesign):
- **Memory-gate at WRITE, not at read**
- A signal passes the gate when ONE OF:
  - Authority tier ≥ COUNCIL (80) — never gate council output
  - Composite score ≥ 0.75 (CRITICAL only)
  - Cross_source ≥ 2 (confirmed across sources)
  - Operator explicit pin
  - Trading-agent reasoning chain (per-decision audit)
- Everything else stays in Intel cache + agent_signals.jsonl rotation only

**Owns**: `data/memory/`
**Mandate file** (proposed): `docs/MEMORY_MANDATE.md` — needs writing

### LANE 4 — CALENDAR

**Purpose**: time-anchored events that affect trading or life. Already clean — needs minor tightening.

**Producer mandate**:
- Lunar engine (Skyfield + Meeus)
- Market event calendar (FOMC, OPEX, quad-witch, VIX, earnings)
- 7-city local-events scanners (CURRENTLY IN AWAREBOT, should move here)
- Watchlist correlator (lunar + predictions + scanners + paper + portfolio)

**Consumer mandate**:
- iOS Calendar tab → 7DAY / 30DAY / TODO / CITIES / MOON / SUN
- Trading agent → `calendar_gate` (current) + `intel_request("calendar.add_followup")` (NEW)
- Morning brief → consumes economic calendar + earnings

**Pre-gate rules**:
- Events must have ISO date + impact level + region
- City events filtered to "high-quality cultural" (concerts, festivals, sports) — NOT "Calgary Transit Hiring event"

**Owns**: `data/calendar/`
**Mandate file** (proposed): `docs/CALENDAR_MANDATE.md` — needs writing

### LANE 5 — JOURNAL

**Purpose**: NATRIX's own writing + reflections + life plan + morning quiz + agent's reflections. Personal, not shared with the wider system.

**Producer mandate**:
- NATRIX writes entries via iOS
- ReflectionEngine produces nightly synthesis (Sonnet 4 at 22:00 ET)
- Morning quiz scheduler writes quiz responses + nudges
- LifePlan editors write Vision/NorthStar/Goals/Plans
- Monthly review writes auto-trader reflection (Wave 14U-2/10)

**Consumer mandate**:
- iOS Journal tab → Quiz / Life / Write / Search / Tips / Insights
- Working context promotes morning_quiz Q2 + Q5 (already happens)
- Trading agent → reads quiz for daily posture (via working-context indirectly)
- Memory lane absorbs by promotion at importance 80-95

**Pre-gate rules**:
- Free-form entries always pass (NATRIX's voice)
- Auto-reflections gated by `entry_type` enum
- Importance floor 50 (below that = ephemeral, don't bridge to memory)

**Owns**: `data/journal/`, `data/life_plan/`
**Mandate file** (proposed): `docs/JOURNAL_MANDATE.md` — needs writing

---

## Part 3 — How the lanes interact

```
                ┌────────────────────────────────────┐
                │                                    │
   Awarebot ───►│   INTEL lane (transient, sorted)   │
                │                                    │
   Brief Pro ──►│                                    │
                └─────┬───────────────────┬──────────┘
                      │                   │
              (CRITICAL or               (always)
               x-source≥2)                │
                      │                   ▼
                      ▼            iOS Intel tab
                ┌─────────────┐         + Trading agent
                │             │
                │   MEMORY    │
                │   lane      │◄──── user pins
                │             │◄──── council outputs (importance 80+)
                │             │◄──── journal promotions (importance 50+)
                │             │◄──── agent reasoning chains
                └──────┬──────┘
                       │
                       ▼
               iOS Memory tab + agent fused_search

                ┌─────────────┐
                │  CALENDAR   │ ◄── time-anchored events only
                │  lane       │
                └─────────────┘

                ┌─────────────┐
                │  PORTFOLIO  │ ◄── broker positions + agent decisions
                │  lane       │
                └─────────────┘

                ┌─────────────┐
                │  JOURNAL    │ ◄── NATRIX writes + reflections + quiz
                │  lane       │
                └─────────────┘
```

**The key invariant**: every piece of data has exactly ONE primary lane. Cross-references are secondary.

**Promotion paths** (lane → lane):
- Intel → Memory: pre-gate (CRITICAL or cross_source ≥ 2 or operator pin)
- Journal → Memory: importance 50 floor + bridge_to_memory call
- Portfolio → Memory: AutoTrader reasoning chain + paper-close attribution
- Calendar → Memory: never (calendar IS the calendar; recall is what calendar tab is for)

---

## Part 4 — Coherent goals + mandates

### One sentence per lane

| Lane | Coherent goal |
|---|---|
| **PORTFOLIO** | "Show NATRIX what he owns right now and what the agent is doing with it." |
| **INTEL** | "Show NATRIX what's happening outside his portfolio that he should know about today." |
| **MEMORY** | "Recall anything NATRIX or the agent has decided is worth remembering." |
| **CALENDAR** | "Tell NATRIX what time-anchored events affect his trading or his life this week." |
| **JOURNAL** | "Capture NATRIX's voice + reflections + life plan + daily ritual." |

### Cross-cutting principles

1. **One primary lane per datum**. Promotion to another lane is explicit + gated.
2. **Pre-gate at the producer**. By the time a signal is on disk, it has earned its slot.
3. **Pre-organize at the producer**. By the time a signal hits storage, it knows which lane it's in.
4. **Consumers don't re-sort**. iOS tabs and the trading agent read from their lane, not from a shared pool.
5. **The trading agent and NATRIX-as-user are equally first-class consumers**. Every lane serves both.
6. **The agent can request anything across lanes via `intel_request()`** (Wave 14W) but doesn't normally read other lanes' raw data.

---

## Part 5 — Implementation order (Wave 14W)

**Phase A — Mandates (this week, doc work, no code)**
1. Write `docs/INTEL_MANDATE.md`, `docs/MEMORY_MANDATE.md`, `docs/CALENDAR_MANDATE.md`, `docs/JOURNAL_MANDATE.md` from Part 2 above
2. Ingest each as procedural memory at importance 95 on brain boot (same hook as `AUTO_TRADER_MANDATE.md`, Wave 14U)

**Phase B — Pre-gating (next sprint, surgical backend)**
1. Awarebot: drop `news`-as-derivative source, lower google_trends authority 0.8→0.4, remove city_events (move to Calendar), raise HIGH threshold 0.55→0.65, stop `_inject_working_context()`
2. MemoryStore: persist Awarebot signals only on CRITICAL or cross_source ≥ 2
3. Working context: fix narrative-thread monoculture (per-source diversity cap, demote thread aggregate importance 100→60)

**Phase C — Pre-organization (next sprint, new module)**
1. Build `runtime/lane_router/__init__.py` — single `route(datum) -> {primary_lane, secondary_refs, gate_decisions}` function
2. Wire every producer (Awarebot, brief_prep, brief_council, scanners, journal_store, calendar_agent, portfolio_manager) through it at write-time
3. Add a `lane: str` field to every storage record so consumers can filter by lane

**Phase D — UI reorg (iOS, presentation)**
1. Move WC display from Memory→PINNED to Intel→AGENDA (Intel→FOCUS already loads it)
2. Move Rotation/RRG widget from Intel→Rotation to Portfolio→Rotation (already a working widget)
3. Move scanner-config CRUD from Intel→Focus gear to Settings→Watch Plan
4. Adopt `/intelligence/digest` as Intel→RIGHT NOW unified read
5. Memory→PINNED becomes user-pins-only

**Phase E — Agent orchestrator (next sprint, biggest)**
1. Build `runtime/agent_bus/intel_request.py` dispatcher (6 handlers per the deep-dive)
2. Wire `drift_detector` → council spawn
3. Wire research-topic clusters → automatic deep dive (fused-search + Awarebot focused scan + Sonnet synthesis)
4. Wire `capability_registry` gap → self-heal attempt

---

## Part 6 — Crisp recap of the answers

| Question | Answer |
|---|---|
| Do we have categories? | Field exists, useless |
| Lane for portfolio/intel/memory/calendar/journal? | 3 yes (Portfolio/Calendar/Journal), 2 no (Intel/Memory overlap as projections of one pool) |
| Should we? | Yes |
| Are we organizing? | Yes, but post-organizing at consumer side |
| Are we pre-organizing? | No |
| Are we memory gating? | At read, not at write |
| Are we pre-gating? | No |
| Coherent goals + mandates? | 3 yes, 2 no — write the missing two mandates first |

The lane architecture is the answer to "are we getting in our own way?" — yes, because every consumer (NATRIX, agent, brief) shoulders the full sorting cost on every read. Move the sort to the producer, gate at write, label at ingest, and the system stops competing with itself.

---

## Sources

- [docs/INTEL_ARCH_DEEP_DIVE_2026-05-28.md](computer:///Users/natrix/dev/NCL/docs/INTEL_ARCH_DEEP_DIVE_2026-05-28.md) — quantity audit + reorg proposal
- [outputs/audit_awarebot.md](computer:///Users/natrix/dev/NCL/outputs/audit_awarebot.md)
- [outputs/audit_wc_focus_memory.md](computer:///Users/natrix/dev/NCL/outputs/audit_wc_focus_memory.md)
- [outputs/audit_trading_agent_intel.md](computer:///Users/natrix/dev/NCL/outputs/audit_trading_agent_intel.md)
- [docs/AUTO_TRADER_MANDATE.md](computer:///Users/natrix/dev/NCL/docs/AUTO_TRADER_MANDATE.md) — template for the missing 4 lane mandates
