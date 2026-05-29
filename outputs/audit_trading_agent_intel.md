# Auto-Trader Intel Consumption + Request Audit

**Scope:** What intel the auto-trader currently consumes per tick, what facilities it has to request more, and the wiring gaps blocking NATRIX's vision of an agent that actively orchestrates brain services (Awarebot / Memory / Calendar / Scheduler / Council) ad-hoc rather than just receiving them.

**Live state checks (2026-05-29 03:17 UTC):**
- `GET /portfolio/auto-trader/dashboard` → 15-key rollup, agent ACTIVE, last tick 03:17:41Z, 0 evaluated / 0 opened / 0 rejected today, last_seen_trade_idea_id = 2026-05-28T13:35Z
- `GET /portfolio/auto-trader/research/topics` → `{count: 0, topics: []}` (no clusters yet — only 2 closed paper trades in the bandit)
- `GET /portfolio/auto-trader/capabilities` → 11 tracked, 10 ok, 1 gap (`finnhub: FINNHUB_API_KEY missing`)
- `GET /portfolio/auto-trader/brief-context-packet` → 530 chars; LCB ranking section header but EMPTY body (n_observed < 3 filter strips every strategy) + capability-gaps section
- Last 3 `reasoning_chains.jsonl` rows (2026-05-28) → all REJECTS: `no source citations` (XLE options), `R:R 1.00 below 1.5 floor` (pairs MSFT/XLK), `invalid stop_type 'atr_2x'` (GOAT APLD). Zero successful opens in the trailing window.

---

## 1. Current decision-loop intel consumption (one 60s tick)

Gate order inside `loop.auto_trader_loop` (verbatim from `runtime/portfolio/auto_trader/loop.py` lines 180-733):

| # | Gate / Check | Reads | Purpose |
|---|------|-------|---------|
| 0a | **cycle_watcher** (every 60 ticks ≈ 1h) | `runtime.intelligence.cycle_phase.build_cycle_phase_snapshot()` → `data/rotation/cycle-*.json` + own state file `cycle_watcher_state.json` | Detect phase transition (early/mid/late/recession). On transition, decays `strategy_bandit` priors x0.3 for regime-sensitive strategies (`goat/bravo/momentum/pairs/mean_reversion/factor/crypto_carry`); writes importance-90 MemUnit |
| 0b | **drawdown_bucket** (wrapped in CB `auto_trader:drawdown_bucket`) | `await bucket.get_state()` — reads `current_nav_cad`, `band` (green/amber/red/halt). Treats `nav<100 + band=halt` as data-unavailable | Sets `state.set_drawdown_halt()`. Hard-stop if `band==halt` |
| 0c | **state.is_active()** | own state.json — AND of (active, !paused, !drawdown_halt) | Skip tick if paused |
| 1 | **day-cap** | `policy.max_opens_per_day` (default 12) vs `state.ideas_opened_today` | Skip if cap reached |
| 2 | **tracker.list_by_strategy(None)** (CB `auto_trader:trade_idea_tracker`) | JSONL ledger of every emitted trade idea ever | Filter to `outcome=="emitted" AND issued_at > state.last_seen_trade_idea_id` |
| 3 | **sanity_gate** (per idea) | yfinance fast_info (current price + 52w high/low + average volume) | 4 checks: ticker exists, price in 52w range +/- slack, daily move <30%, volume >0 |
| 4 | **risk_governor** (CB `auto_trader:risk_governor`) | Per-strategy heat caps + NAV + drawdown band → sizing multiplier | Returns approved/rejected + `effective_R_dollars` + heat dict |
| 5 | **calendar_gate** | `runtime.calendar.events_compiler.compile_brain_events(today, today+14)` cached 24h to `calendar_cache.json` + `runtime.stocks.enrichments.get_earnings_map(tickers=[ticker])` cached 24h | Blanket-blocks for FOMC (1d), OPEX/quad-witch (1d), VIX expiry (0d); per-ticker earnings within 2d |
| 6 | **working_context_gate** | `data/working_context/today.json` cached 300s. Filter to `importance >= 80` (NATRIX + COUNCIL tier). Regex-extract tickers from pinned content. Match BLOCK_PATTERNS ("do not trade", "avoid", "ban", "skip") and ALIGN_PATTERNS ("watch", "bullish", "load up") | Block if NATRIX-tier item explicitly bans ticker; annotate `aligned_with`/`contradicted_by` |
| 7 | **policy.auto_open_eligible** | Idea + governor decision + policy.json (20+ thresholds: `min_R_R_ratio=1.5`, valid stop_types, source citations required, counter-trend off by default) | Hard policy check — most current rejects fire here |
| 8 | **tax_sizing** | TaxLotLedger (last-30d closed lot ledger) + earnings proximity from `get_earnings_map` | Block on wash-sale conflict if `NCL_AT_WASH_BLOCK=1`; multiplier for earnings proximity |
| 9 | **beta_cap** | yfinance 60d return correlation vs SPY + open positions snapshot from `PaperTradingEngine._trades` | Reject if portfolio beta-weighted exposure breaches per-direction cap |
| 10 | **sector_cap** | `WATCHLIST_MAP` ticker → sector + open positions snapshot | Reject if per-sector concentration breaches cap |
| 11 | **friction_profile** | `friction_profiles.json` per-strategy slippage_bps + partial_fill | Mutates entry price + qty before paper.create_trade |
| 12 | **council_check** (only if `effective_R >= $1000`) | Internal: spawns `CouncilQuorum` (Sonnet 4 + Haiku 4.5), 2-LLM ~$0.05 | "Is this trade sane?" — VETO token in either response → block |
| 13 | **paper.create_trade** (CB `auto_trader:paper_engine`) | PaperTradingEngine JSONL | Opens position |
| 14 | **observability.record_reasoning_chain** | own JSONL | Persists prompt + governor + policy + council + paper_trade_id |
| 15 | **observability.update_paper_trade_id** + **tracker.update_outcome("taken")** + `mem.create_unit("portfolio:auto_trade_opened", importance=75)` | Memory write only (fire-and-forget) | Stitches idea→paper trade + journal |

**On CLOSE** (separate `outcome_attributor` loop, not in `loop.py`): triggers `strategy_bandit` posterior update + `drift_detector` Page-Hinkley check + every 10 closes `shap_attribution` + `profit_ladder` (rolls fraction of realized profit into longer-dated recipe at ≥configured R threshold) + auto-calibrates `friction_profile` from observed slippage.

---

## 2. PUSH vs REQUEST

### Pushed TO the agent
- **Trade ideas** — written into `trade_idea_tracker` by external producers (brief executor, GOAT/BRAVO scanners, quant scanners `mean_rev/pead/factor/pairs/whale_flow/crypto_carry/polymarket_kelly`, scout). Agent polls; producers never call agent.
- **NAV / portfolio state** — `portfolio_manager` sync loop writes `data/portfolio/snapshots.jsonl`; agent reads via `drawdown_bucket`.
- **Working-context pins** — `working_context` 6am/noon/11pm assembly writes `today.json`; agent reads via `working_context_gate` (read-only filter at importance≥80).
- **Calendar events** — `CalendarAgent` continuously writes; agent reads via `calendar_gate`.
- **Rotation / cycle / style snapshots** — `ncl-rotation` writers; agent reads via `cycle_watcher`.

### What the agent PUSHES BACK (the only feedback wire that exists)
- **`brief_context_packet()`** — text block injected into morning-brief executor prompt at `runtime/api/routers/intel/brief_pipeline.py:597`. Compiled live: 530 chars containing strategy LCB rankings (currently empty body — `n_observed < 3` filter strips everything because only 2 closed trades exist), recent SHAP findings (none yet), open research topics (none), profit-ladder activity, quant-scanner emits, scout activity, capability gaps (`finnhub`). The brief uses this to bias next morning's trade ideas. THIS IS THE ENTIRE FEEDBACK SURFACE.

### The "capability registry" mechanism — what it actually does
Not an active request channel — it's a **passive observability layer**:
1. Scanners/loops call `check_and_request(name, brain, requesting_module=...)` before attempting a data lookup.
2. The check probes `import_probe`, `env_required`, and `file_marker` staleness (e.g., `data/rotation/{today}.json` max 2d old).
3. On gap, it writes an importance-95 MemUnit tagged `tool_request, capability_gap, capability:<name>, requested_by:<module>` — **deduped to once per ET date per (capability, module)**.
4. The operator reads the MemUnit via Memory tab; nobody downstream auto-acts on it.

So the "tool request" pattern exists in spirit but the channel terminates at the human. Today's check shows 1 gap (`finnhub: FINNHUB_API_KEY missing`); it's the only entry that would emit a request MemUnit. The other 10 dependencies are all green.

### Self-research clustering — closes a loop or just emits topics?
Half-closes. `generate_research_topics()` (in `self_research.py:240`) clusters losing trades by `(sector_etf, source, stop_type, rotation_quadrant)`, persists topics to `research_topics.json` if cluster ≥ 3 losses, and `brief_context_packet` surfaces them in the next morning brief prompt under "OPEN RESEARCH TOPICS." That's the only loop closure: brief LLM is *told* what's failing but is not *asked* to research anything specific — there's no follow-up that confirms a topic was addressed in the next brief, no `resolve_research_topic` auto-call when the brief explicitly answers a topic, and the topic stays open until an operator hits `POST /auto-trader/research/topics/{id}/resolve` manually. Also K4a (`apply_shap_to_authority_learner`) pushes SHAP per-source lifts into the SourceAuthorityLearner Beta-Bernoulli, which DOES close a loop into the next-brief signal scoring — that's the cleanest existing feedback wire.

---

## 3. Facilities that EXIST but are underused

| Capability | Built | Used by agent? |
|---|---|---|
| `brain.memory_store.create_unit` | Yes — 18 call sites across loop / cycle_watcher / outcome_attributor / shap_attribution / capability_registry / profit_ladder / tax_sizing / monthly_review / portfolio_drift / scout | **Write-only.** Agent emits importance-75 MemUnits on every open + 80 on every close + 90 on cycle transition + 95 on capability gap. Never reads back. |
| `brain.memory_store.fused_search` / `by_authority` / KG query | Yes (FusedRetriever fully implemented) | **Zero call sites in `runtime/portfolio/auto_trader/`** — `grep -r memory_store\.search auto_trader/` returns nothing. The agent could read its OWN prior failure memory but doesn't. |
| `working_context` pin write | Yes (POST `/memory/working-context/pin`) | **Read-only via gate.** Agent could `pin` a flag like `auto_trader:drift_detected:bravo` so the next brief sees it explicitly without going through SHAP — but doesn't. |
| `CouncilQuorum.run_quorum` | Yes (used in `council_check.py` for high-R opens) | **One trigger only**: `effective_R >= $1000`. Could also fire on `drift_detector` DRIFT_DOWN, on cycle transition, on a research-topic cluster forming, on a contradicting NATRIX pin — none currently wired. |
| Full council session spawn (`brain.spawn_council_session`) | Yes — exists for `/pump` ingest | **Never called from auto_trader.** A drift, regime change, or 3-loss cluster should be able to queue a real Delphi-MAD debate. No call site exists. |
| Manual rotation/cycle refresh | `POST /intelligence/rotation/fire` exists | Agent only READS `cycle_phase` via `cycle_watcher`. Never POSTs the refresh endpoint when the file marker is stale (would let it self-heal a stale snapshot instead of emitting a capability-gap MemUnit). |
| `apply_shap_to_authority_learner` | Yes | Fires on every SHAP attribution (every 10 closes per strategy). DOES close back to brief — best-working wire in the system. |

---

## 4. Facilities that DO NOT EXIST today (NATRIX's vision gaps)

| Vision capability | Status |
|---|---|
| **Agent → Awarebot "scan now for X"** | NO. `Awarebot.run()` is a closed scheduler-driven loop. No `awarebot.request_scan(query, urgency)` entry point. Agent cannot say "the brief mentioned XLE breakout — give me last-hour signals on energy." |
| **Agent → Calendar "block 3pm for review"** | NO. `CalendarAgent` is a read producer. No `calendar.add_followup(event_id, reason)`. Topic-resolution could schedule itself but doesn't. |
| **Agent → Memory "fused-search prior losses in tech"** | NO call site exists in auto_trader. The retrieval API is wired (`GET /memory/search/fused?q=...`), the agent simply never invokes it. `generate_research_topics` could enrich each topic with "prior similar episodes" via a fused search but doesn't. |
| **Agent → Scheduler "fire ad-hoc council at 9:30am"** | NO. No queue endpoint the agent calls. Wave 13 added `POST /council/queue` for the Memory-tab "Council This" button; agent could theoretically POST to it but no module does. |
| **Agent → Brief "regenerate with focus on Y"** | NO. `POST /intelligence/morning-brief/pro/fire` exists as a manual trigger. The agent has the `brief_context_packet` push but cannot say "re-run today's brief with extra weight on XLE — this is a new live opportunity." |
| **Agent → Brain orchestrator** (the real ask) | NO unified `request(facility, payload)` tool surface. Each gap above is a separate missing wire. The closest analog is `capability_registry.check_and_request` which only emits MemUnit to operator — there's no machine-routed handler that picks up the MemUnit and acts. |
| **Drift → contrarian council debate** | NO. `drift_detector.py` flips `state.paused_by="drift_detector"` + emits importance-90 MemUnit `portfolio:strategy_drift`. That's where it terminates. A "spawn full council on this drift" wire would be one new function call inside `drift_detector._on_drift_down`. |
| **Research topic → automatic deep dive** | NO. Topics sit in `research_topics.json` until operator resolves. The vision: each new topic auto-spawns (a) a fused memory search for prior similar clusters, (b) an Awarebot focused scan on the cluster's sector_etf/source for last 7d, (c) a single-LLM (Sonnet) research synthesis writing back to the topic as `resolution_notes`. |
| **Capability gap → self-heal attempt** | NO. `finnhub` gap today just sits there. No retry, no fallback-source attempt, no operator-nudge escalation. |

---

## 5. The "agent orchestrator" pattern

What it would look like if the auto-trader became the brain's primary consumer of services rather than a parallel system reading shared files:

```
┌─── auto_trader.loop (60s tick) ────────────────────────────┐
│                                                            │
│ each tick collects gate inputs via a unified request bus:  │
│                                                            │
│   intel_request(                                           │
│     kind="memory.fused_search",                            │
│     query="prior $XLE energy breakouts H4",                │
│     max_results=20)                                        │
│                                                            │
│   intel_request(                                           │
│     kind="awarebot.scan_now",                              │
│     focus="energy sector last 60min",                      │
│     urgency="high")                                        │
│                                                            │
│   intel_request(                                           │
│     kind="council.spawn",                                  │
│     reason="drift_detected:bravo",                         │
│     topic="Why is bravo strategy losing edge?",            │
│     panel="delphi_mad_4")                                  │
│                                                            │
│   intel_request(                                           │
│     kind="calendar.add_followup",                          │
│     when="today 15:00 ET",                                 │
│     payload={"review_topic_id": "topic:source=brief"})     │
│                                                            │
│   intel_request(                                           │
│     kind="brief.regenerate_focus",                         │
│     reason="rotation flipped mid-day",                     │
│     focus_tickers=["XLE","XLK"])                           │
│                                                            │
└────────────────────────────────────────────────────────────┘
                  │
                  ▼
       ┌─── request_bus.dispatch ───┐
       │ - rate limits per kind      │
       │ - cost gates                │
       │ - dedup window              │
       │ - routes to provider        │
       └─────────────────────────────┘
                  │
       ┌──────────┼─────────────┬──────────────┬────────────┐
       ▼          ▼             ▼              ▼            ▼
   memory.    awarebot.    council.       calendar.    brief.
   fused_     focused_     spawn_         add_event    regenerate
   search     scan         session                     _focused
```

The mental shift: instead of `loop.py` being a sequence of *reads* from shared file outputs, every gate is a *request* whose result is awaited (or cached if recent). The agent becomes a thin orchestration shell over the brain's capabilities. The capability_registry already names the seam — it just terminates at the operator. Turning it into a real router needs (a) a `intel_request` function with `provider_for_kind` dispatch, (b) handlers on each provider that accept ad-hoc work (Awarebot needs a request queue; Council already has `spawn_council_session`; Memory already has search; Calendar already has `POST /calendar/events`).

---

## 6. Top 5 wiring gaps to close

1. **Agent → Memory fused-search (read path).** Zero call sites today. Add `runtime/portfolio/auto_trader/memory_query.py` with a thin wrapper: `await brain.memory_store.fused_search(query, top_k, min_authority)`. Call it from `generate_research_topics` to enrich each new topic with `prior_similar_episodes`, and from `working_context_gate` to expand pinned-item context to its semantic neighborhood instead of just regex matching. **This alone unlocks "the agent learns from its own memory."**

2. **Drift / cycle / 3-loss cluster → spawn real council session.** Today `drift_detector` and `cycle_watcher` write importance-90 MemUnits and stop. Wire `brain.spawn_council_session(topic=..., context=...)` from three sites:
   - `drift_detector._on_drift_down` (Delphi-MAD: "why did bravo lose its edge?")
   - `cycle_watcher.check_and_decay` post-decay (Delphi-MAD: "which strategies stay sensitive in $new_phase?")
   - `generate_research_topics` new-topic creation (single Sonnet research turn writing `resolution_notes` back via `resolve_research_topic`)

3. **Awarebot scan-now request endpoint.** Awarebot today is closed-loop. Add `POST /intelligence/awarebot/scan-now {focus, lookback_min, urgency}` and a queue inside `Awarebot.run()` that drains on next tick. Agent calls when a brief idea fires but the agent has no recent signals for the ticker's sector, when council debate completes, when scout flags regime shift. Pairs with capability_registry — instead of a gap MemUnit, the agent fires a scan-now and retries.

4. **Brief regenerate-focused endpoint + agent caller.** `POST /intelligence/morning-brief/pro/fire?focus_tickers=...&theme=...` exists as the firehose; add `?regen_reason=...` and have the agent call it when (a) intraday rotation flips mid-day (cycle_watcher detects), (b) NATRIX pins a new high-conviction ticker, (c) drift halts a strategy. Today the only way to refresh a brief mid-day is the operator's manual fire.

5. **Promote `capability_registry.check_and_request` into a real router.** Add an in-process subscriber that watches for `tool:capability_request` MemUnits and either (a) fires the matching brain task to refresh the stale marker (e.g. `POST /intelligence/rotation/fire` when `rotation_snapshot` is stale), (b) calls a fallback provider (e.g. yfinance economic calendar when `finnhub` env missing), or (c) escalates to a council session if no automatic path exists. The data structure is there; the dispatcher is missing.

---

**Closing observation.** The auto-trader was built as a write-heavy emitter of MemUnits and a read-heavy consumer of file artifacts. Every "request" facility that does exist (`capability_registry.check_and_request`, `generate_research_topics`, `brief_context_packet`) terminates either at the operator (MemUnit → human) or at the next morning's brief (packet → LLM prompt). There is no machine-actionable request bus. Wiring the 5 gaps above would turn the agent from "system that observes itself and writes notes about it" into "system that asks the brain for things and acts on the answers" — which is what NATRIX's vision describes.
