# NCL (NUREALCORTEXLINK) — Standalone Personal-AI Brain

**Status**: Authoritative spec, rewritten 2026-05-23, updated 2026-05-25 (Wave 14A-G arc: intel reorg, morning brief multi-stage pipeline, journal redesign with morning quiz + life plan, LLM goal synth + vision board + review wizards, native macOS desktop with system monitor + multi-window mirror) — supersedes pre-retirement docs in `archive/docs-pre-retirement/`.

**Recent wave summary (2026-05-26)**:

- Wave 14H — Morning Brief Pro (flagship). NATRIX flagged the morning brief as one of the app's flagship features and wanted a serious overhaul: "night watch agent to prep morning brief and send it to council to do research and presentation brief... detailed plan for market open and what to watch for and indicators for movement direction and momentum... full effort, full performance, focused effort so I can make profitable trades". Built as three serialized stages:
  1. **PREP (02:30 ET)** — `runtime/intelligence/brief_prep.py`. Overnight data collector. Fires concurrent yfinance + Awarebot signal queries to build a context pack: futures (ES/NQ/RTY/YM), VIX term structure (^VIX/^VIX9D/^VIX3M curve shape: backwardation/contango/mixed), overnight movers (top 20 gainers + 20 losers from watchlist pre-market), headlines (last 12h Awarebot news/RSS dedup'd to 25), options_flow_yesterday (GOAT/BRAVO top 10 from yesterday's JSONLs), economic_calendar (Finnhub if key set), earnings_today, polymarket_leading (active-leading-only per P17-D), held_positions, working_context, night_watch_summary. Persists to `data/morning-brief-prep/YYYY-MM-DD.json`. Loop = `ncl-brief-prep` in scheduler.
  2. **COUNCIL (05:00 ET)** — `runtime/intelligence/brief_council.py`. Delphi-MAD style 4-LLM panel + chair: Macro Analyst (Claude Sonnet 4 — futures/cross-asset/VIX direction call), Real-Time Pulse (sentiment/breaking/Polymarket shifts), Flow Detective (options/dark pool/GEX/institutional positioning), Technical Tactician (per-ticker setups + momentum + RVOL + ORB candidates). All 4 members run in parallel with `asyncio.gather` each getting a domain-tailored slice of the prep pack. Chair (Claude Sonnet 4 ext-thinking) receives all 4 outputs + resolves contradictions, applies rule 7a ETF quota + date recency + price sanity from P17, writes final brief JSON with market_open_plan section. Cost ~$0.26/run vs P14D's $0.045 — 5x but it's the flagship. Persists to `data/morning-brief-council/YYYY-MM-DD.json`. Loop = `ncl-brief-council`.
  3. **PRESENTATION (05:30 ET)** — `runtime/intelligence/brief_presenter.py`. Pure-Python renderer (no LLM). Renders chair's synthesis into plain-text brief with MARKET OPEN PLAN section pinned to top — four sub-blocks: WHAT TO WATCH (3-5 specific catalysts with reaction triggers), DIRECTION INDICATORS (ES futures levels, VIX shape, breadth, SPY put/call — read at open), MOMENTUM SIGNALS (gap-up-watch with >2% pre-mkt + vol >1.5x, gap-down reversal candidates, RVOL >3x list, ORB candidates), RISK FLAGS (severity-tagged). Below the plan: EXECUTIVE SUMMARY, KEY MOVEMENTS, EMERGING OPPORTUNITIES & RISKS, PRE-MARKET TRADE IDEAS (max 6, ≤1 ETF), POLYMARKET WATCH, TODAY'S RESEARCH TOPICS. Persists to `data/morning-brief-pro/YYYY-MM-DD.json`. Loop = `ncl-brief-render`.
  
  API surface: `GET /intelligence/morning-brief/pro` (today's rendered brief), `GET /intelligence/morning-brief/pro/prep` (raw prep pack debug), `GET /intelligence/morning-brief/pro/council` (raw council outputs debug), `POST /intelligence/morning-brief/pro/fire` (manual end-to-end trigger). Existing `/intelligence/morning-brief` (P14D pipeline) kept as fallback. Scheduler: 3 new named tasks `ncl-brief-prep` (02:30 ET), `ncl-brief-council` (05:00 ET), `ncl-brief-render` (05:30 ET) — total scheduler count 35 → 38 named tasks.
  
  Failure modes: prep fails → council runs against yesterday's prep; council fails → renderer falls through to P14D pipeline; chair fails → returns last-good brief. Live-fired end-to-end: 71s wall, 4/4 members succeeded, 6 trade ideas with rule 7a quota intact, council confidence 0.79, contradictions_resolved surfaced in meta. Full architecture doc at `docs/MORNING_BRIEF_PRO_2026-05-26.md`.

- Wave 14G P19 — GOAT/BRAVO scanner gate restoration. P18 audit found 3 of 4 gates (IVR, earnings, held-portfolio) silently non-functional + 1 top GOAT pick (NNE) with 9% stale price. P19-A fixes: (1) yfinance-based earnings calendar fallback when FINNHUB_API_KEY is missing — `get_earnings_map(tickers=...)` now falls through to per-ticker `yfinance.Ticker(t).get_earnings_dates(limit=4)` before declaring unavailable; (2) hardened `_yf_iv_blocking` with 3-tier spot price fetch (fast_info → info.currentPrice → 1d history) since fast_info shape changed in newer yfinance; (3) `ivr_status: "available"|"unavailable"` tag on every result so the gate is HONEST about whether IVR was actually evaluated (previously silently bypassed when data was missing). P19-B polish: score=0 results dropped from response (was shipping 11 noise rows in BRAVO), `sector` populated from WATCHLIST_MAP join, `scan_started_at` + `scan_completed_at` + `scan_duration_s` added to `_meta` for operator visibility.

- Wave 14G P17 — Five morning-brief quality gates. NATRIX QA report after P15/P16 surfaced: ETFs dominating trade ideas, pre-2026 dates framed as forward catalysts, stale Polymarket events anchoring claims, hallucinated ticker prices, planner picking "short" mode with 978 signals. P17-A (HIGH) — rule 7a ETF-quota enforcement in `_local_critique`: 25-ticker broad-ETF blocklist (SPY/QQQ/IWM/DIA/XLF/XLK/XLE/XLV/XLI/XLP/XLY/XLB/XLU/XLC/XLRE/GLD/SLV/USO/UNG/ARKK/SMH/SOXX/VTI/VOO/VXX/TLT/IEF/DIA); fails brief if >1 idea ticker matches. P17-B (HIGH) — date-recency check: executor prompt rule 7b ("today is 2026, do NOT cite pre-2026 dates as forward catalysts"); critic stale-year scanner that walls 'by 2025'/'through 2024'/'mid-2025'/'upcoming 2023' against forward-tense framing. P17-C (LOW) — Python override after planner: if total_signals > 300 AND source_count >= 3 AND mode=='short', force mode='full' + trade_idea_count_target=6. P17-D (MED) — Polymarket lifecycle tagging in collector: `metadata.lifecycle_status` = 'resolved' (end_date < now) / 'leading' (active + outcome >= 60%) / 'active'; executor prompt rule 7c prefers 'leading' over 'resolved' so resolved May-24 events stop anchoring next-day briefs. P17-E (MED) — price sanity-check in critic: regex `\b([A-Z]{2,5})\b[^.$\n]{0,60}?\$(\d{1,5}(?:\.\d{1,2})?)(?![MKB%])` extracts (ticker, claimed_price) tuples; lazy yfinance 52-week range lookup; flags brief if claim outside range +/- 2% slack. Context blockers (`premium`, `volume`, `flow`, `mcap`, `p/c ratio`, etc) prevent false positives on "$485M premium" being read as "$485 price". Live verified: critic score dropped from blind 100 → meaningful 92 with 1 honest "trade_ideas count below target" reason. Caught the rule-7a violation on regenerate cycle, pipeline now shows `regenerated:true` + critic_reasons in pipeline_meta.

- Wave 14G P14 + P15 — Earlier morning-brief polish: executive_summary markdown strip (Wave 14C only covered topics_text); Coinpaprika fallback for crypto when CoinGecko rate-limits (free ~25k calls/month, no key); SQLite cutover audit (DB lives at `data/persistence/ncl.db` 28MB, NOT `data/mandates.sqlite` per prior doc; mandates 70 rows, cost_ledger 2,911, units_index 33,005 — all 3 gates live); generated_at timestamp surfaced in API response (was persisted to disk only); rule 7a/7b/7c (above) enforcing individual-stock preference over sector ETFs.

**Recent wave summary (2026-05-25)**:

- Wave 14G — NCL Desktop (native SwiftUI macOS) full arc, **thirteen phases shipped 2026-05-25**. Per `docs/DESKTOP_OPTIONS_2026-05-25.md` recommendation: native SwiftUI Mac target sharing FirstStrike Swift sources via multi-platform `project.yml`, augmented by MenuBarExtra for ambient admin, `OpsView` window for Brain-correlated host+process+network monitoring, and a new `runtime/system_monitor/` backend module sampling sysctl/vm_stat/netstat/tailscale/cost-ledger every 5s into a 720-entry ring buffer (60min @ 5s) exposed via `GET /system/ops/{snapshot,history}` + `WS /system/ops/stream`. **Phase 1** (commits NCL `b65f2fd`, FirstStrike `0f1a0eb`) — `runtime/system_monitor/` package (models/collectors/sampler ~500 LOC), 1 new router, `ncl-ops-monitor` 5s loop, MenuBarApp.swift ~300 LOC with status pill (`🟢 NCL · $X · N/M loops`) + OpsPanel expand panel + admin actions (Refresh, Bounce Brain, Open Logs). **Phase 2** (commits NCL `4c35d99`, FirstStrike `a7d8f8e`) — collector polish: top regex → vm_stat for memory (was 0.0/64GB, now 46.3/64GB), Tailscale CLI path detection with 4-candidate probe including `/Applications/Tailscale.app/Contents/MacOS/Tailscale` (was 0/0 peers, now 2/2 online), cost ledger schema fix `amount_usd` + `metadata.model` (was $0.00/23 calls, now $0.3257/62 calls). Plus `MacSources/OpsView.swift` ~400 LOC: WebSocket binding to `/system/ops/stream`, Host/Brain/Tailscale cards with Swift Charts sparklines (CPU/RSS/cost), scheduler activity chip grid (FlowLayout), LLM per-model breakdown, recent ticks ring; `Window("NCL Ops", id: "ops")` scene with Cmd+O shortcut, OpsSnapshot/LLMCallSummary extended with `schedulerActivity` + `byModel`. **Phase 3** (commits NCL `dbd5a6f`, FirstStrike `687574d`) — Tailscale parser polish: handshake `0001-01-01T00:00:00Z` (never) renders -1 sentinel instead of ~63B seconds, peer name fallback chain `HostName (skip if 'localhost') → DNSName leftmost → OS-pkey → pkey` (now renders `ipad-pro-11-gen-1` + `iphone-15-pro-max`). New `LogStreamView` (~200 LOC): `tail -F` on `~/Library/Logs/ncl-brain.log` with filter, Pause (Cmd+P), Clear (Cmd+K), level-color coding, 5K-line FIFO cap — opens via Cmd+L. New `QuickAddJournalView` (~210 LOC): floating Cmd+Shift+J HUD with text editor + drop target + kind picker + importance slider; POST `/journal/entries` then auto-dismiss; `hiddenTitleBar` + `windowResizability(.contentSize)`. **Phase 4** (commits NCL `1b62408`, FirstStrike `9b2c44e`) — multi-window iOS mirror. New `Sources/App/PlatformShim.swift` Platform enum with setPasteboard/dismissKeyboard/primaryWindowSize + PlatformImage typealias + PlatformImageView, walls UIKit on iOS / AppKit on Mac; 9 view files migrated off direct UIKit (UIPasteboard → Platform.setPasteboard, UIApplication.sendAction → Platform.dismissKeyboard, UIImage → PlatformImage, ChatBubble.shareText walled with Mac-pasteboard else-branch). LifePlanEditors (uses navigationBarLeading + keyboardType + ForEach($collection)) wrapped in `#if os(iOS)`; `MacSources/LifePlanEditorsMacStubs.swift` provides shim sheets so LifePlanView still compiles. VoiceEngine wrapped in `#if os(iOS)`. project.yml: NCLDesktop gains `Sources/{Models,Network,Services}` + 5 curated view files. MenuBarApp.swift: 2 new `@StateObject` (brainClient, appSettings), 2 new Window scenes — `Cmd+1 Morning Quiz`, `Cmd+2 Life Plan` — both `NavigationStack { ... }.environmentObject(brainClient).environmentObject(appSettings)`. **Phase 5** (FirstStrike `f702cc6`) — Cmd+3 Night Watch (`NightWatchContainer` fetches `/intelligence/night-watch/latest` + handles loading/error/empty before handing brief to `NightWatchBriefView`), Cmd+4 Memory, Cmd+5 Calendar. Walled CalendarView/IntelView/KnowledgeGraphView/MemoryDetailView `navigationBarLeading/Trailing` → `cancellationAction/confirmationAction`. Extracted `FlowLayout` from IntelView to `Sources/App/FlowLayout.swift` (MemoryDetailView depends on it; OpsView's duplicate renamed `ChipFlowLayout`). **Phase 6** (FirstStrike `37c731f`) — Cmd+6 Intel (full subview cascade walled: YouTubeCouncilView, RedditView, XView, PredictionDetailView, FocusContextView, FormattedTextView). **Phase 7** (NCL `a9fbe22`, FirstStrike `35410a2`) — distribution polish: app icon set (1024×1024 master → all macOS sizes via PIL), Sparkle 2 SPM dep (`packages.Sparkle from 2.6.0` + INFOPLIST_KEY_SUFeedURL pointing at brain `http://100.72.223.123:8800/desktop/appcast.xml`), `MacSources/SparkleUpdater.swift` wraps `SPUStandardUpdaterController` + Check-for-Updates menu item, OpsView empty/error state (wifi.exclamationmark + ProgressView). Brain side: new `runtime/api/routers/desktop_releases.py` serves `GET /desktop/appcast.xml` + `GET /desktop/dl/{filename}` (unauthenticated, .dmg whitelist); `scripts/setup_sparkle_keys.sh` + `scripts/make_release.sh` (archive → developer-id sign → optional notarytool → create-dmg → sparkle sign_update → appcast.xml append). **Phase 8** (NCL `ab67df8`) — auto-launch at macOS login. `launchd/com.resonanceenergy.ncldesktop.plist` installed at `~/Library/LaunchAgents/`. Initially direct-binary, switched to `open -W -a` because direct-launched LSUIElement apps don't get WindowServer attachment for the MenuBarExtra status item (verified via System Events `mb count: 0` post-launch); `open -W` blocks until app exits so launchd tracks the real app PID for KeepAlive crash detection. KeepAlive `{SuccessfulExit:false, Crashed:true}` + 10s throttle. Live-verified: SIGKILL respawn in 12s with LastExitStatus=9. **Phase 9** (FirstStrike `53b1df9`) — NATRIX: "8 windows is a mess". Collapsed 8 separate Window scenes into ONE `Window('NCL Desktop', id: 'main')` with `NavigationSplitView` + sidebar + @AppStorage-persisted selection + hidden zero-sized Button cluster wiring Cmd+1..8 to section change. Quick Add HUD stays separate (intentionally global Cmd+Shift+J). Also: OpsView lastError clears on next successful snapshot so the "ws: Could not connect" chip stops sticking; banner copy `Disconnected — retrying` → `Polling · stream reconnecting` when REST data flows. **Phase 10** (FirstStrike `5e4d07c`, 27 files +2961/-118) — NATRIX: "build it identical to app, change settings to OPS and combine". Sidebar mirrors iOS bottom tab bar exactly via shared `FSTab` enum (extracted from `Sources/App/ContentView.swift` to `Sources/Models/FSTab.swift`, made `Identifiable + Hashable` for NavigationSplitView selection); `.settings` case repurposed as "Ops" on Mac with waveform icon. New `MacSources/OpsSettingsView.swift` capsule picker (Live · Settings · Logs) hosts the live OpsView system monitor + a Mac-native SettingsForm (Tailscale IP, brain port, auth token, useBrainDirect/useTailscale toggles, relay port, computed Active Brain URL preview) + the existing LogStreamView. `MacAuthSeeder` reads `STRIKE_AUTH_TOKEN` from `~/dev/NCL/.env` on Mac launch and pushes into AppSettings so embedded iOS views authenticate. JournalView walled + added to Mac target. **Phase 11** (FirstStrike `112874a`) — NATRIX: "hammer". Pulled REAL iOS DashboardView + PortfolioView into Mac target via wholesale `Sources/Views` group include + 5-attempt iterate_wall_v2.py script (ChatView/ChatSettingsSheet/OptionsHeldView/OptionsStrategiesView walled, DashboardView's `.chat case ChatView()` site walled with Mac else-branch). Added PromptHistory + RelayClient + ConversationArchiver @StateObjects to match iOS FirstStrikeApp injections — required by DashboardView at runtime (was crashing `Fatal error: No ObservableObject of type PromptHistory found`). Detail switch now `NavigationStack { DashboardView(selectedTab: $section, intelSection: $intelSection) }` and `NavigationStack { PortfolioView() }`. **Phase 12** (FirstStrike `47f1ed4`) — NATRIX: "now needs to work lol". Two boot-time gaps fixed: (1) `brainClient.configure(ip:port:token:)` was never called on Mac → embedded iOS views had empty baseURL+token and every fetch silently failed. Added the iOS `.task` boot block to MainWindow (configure + initial health ping + 15s heartbeat loop). (2) AppSettings.init's `KeychainHelper.load(key:)` triggered "First Strike wants to access keychain" dialog on every launch (ad-hoc-signed dev rebuilds rotate code signature → invalidates Keychain ACL). Walled the Keychain read `#if !os(macOS)`; Mac always reads brainAuthToken from `.env` via MacAuthSeeder (now overwrites every launch). No more prompts. Live-verified: Cmd+1 Dashboard shows green "Connected", Scheduler/Brain API/Governance all HEALTHY; Cmd+2 Portfolio renders **US$34,218.47** with live broker chart + positions + allocation. **Phase 13** (this wave) — surgical re-wall of Chat/Options + Mac-stub for VoiceEngine (~30 LOC no-op class satisfying ChatView's @StateObject contract; voice features inactive on Mac, keyboard authoring works). ChatView/ChatSettingsSheet/ChatInputBar unwrapped, DashboardView `.chat case` un-walled — Mac now renders the FULL conversational surface. Brief fired live (62s, plan_mode=short, 4/4 trade ideas, critic_score=100, zero stubs in main brief; minor regression noted: `executive_summary` field leaks `**HEADLINE DEVELOPMENT**` markdown — Wave 14C strip pass didn't reach that field, queued). start-all.sh pruned: Paperclip stub removed (cost_tracker.py owns this), service count 4→3.

- Wave 14F — LLM goal synth + vision board + review wizards + editor screens. Commits NCL `f1d4abe`, FirstStrike `4f8da3b`. Backend (`runtime/life_plan/goal_synthesis.py`, `runtime/life_plan/vision_board.py`, `runtime/journal/review_wizards.py`, +890 LOC): (1) `POST /life/goal/{id}/synthesize-weekly` — takes a quarterly Goal (OKR), Sonnet 4 generates 4-6 SMART weekly tasks anchored to its KRs, each becomes its own scope=week Goal with parent_goal_id pointer + single-KR for 0/1 tracking; replaces prior weekly children of the same parent. Budget-gated. (2) `POST /life/vision/board/generate` — OpenAI gpt-image-1 1024×1024 high-quality (~$0.04 + 10-30s) renders a vision board from active Vision's title + narrative + pillars + horizon, stored at `data/life_plan/vision-boards/`; `GET /latest` serves base64 PNG. (3) `POST /journal/{weekly,yearly}-review` — Sunday + Dec 28 wizards mirroring the morning-quiz pattern, 7 questions each, persisted to `data/journal/{weekly,yearly}-review/` + creates `reflection` journal entry (importance 80/95) via fire-and-forget so ReflectionEngine consumes tonight. iOS (`Sources/Views/Journal/LifePlanEditors.swift` new 570 LOC + LifePlanView/JournalView patched): 6 sheets — VisionEditor/GoalEditor (objective + 1-many KRs + dates + confidence)/PlanEditor (kind picker + checklist)/WeeklyReview/YearlyReview/VisionBoard (Generate button + base64 PNG display). LifePlanView has new horizontal actionBar (+ VISION · + GOAL · + PLAN · VISION BOARD); JournalView INSIGHTS sub-tab has WEEKLY REVIEW · YEARLY REVIEW buttons. Built green for sim + device, deployed to all 4 devices.

- Wave 14E followup — quiz timeout + ItemType bug + scheduler. Commits NCL `d4c3e64`, FirstStrike `243f85f`. NATRIX reported the morning quiz felt broken — submit hung indefinitely, he hit Submit 3 times thinking it failed, propagation flags stayed false, plus the quiz never ran on a schedule. Trace via `[MQ-TRACE]` stderr instrumentation isolated three concrete bugs + one missing piece: (1) `journal_store.create_entry` hung the HTTP request because its inner `_bridge_to_memory` + `_inject_to_context` chain parks on an async lock when brain is busy — the journal entry IS persisted but the await never resumes. Fix: switched both `create_entry` calls in `propagate_quiz` to `asyncio.create_task()` — fire-and-forget. Response went from hanging forever to **0.28s**. (2) Pydantic-style `ItemType` enum import from `runtime.memory.working_context` — doesn't exist; `ContextItem` is a plain dataclass with `category: str` field. Every quiz silently failed working_context push. Fix: use ContextItem's real signature (`category="pinned"`, `salience_score`, `recency_score`, `relevance_score`, etc.). Verified live: `pushed_to_working_context: true`. (3) NEW `runtime/autonomous/loops/morning_quiz_scheduler.py` — wired into scheduler.py, runs 00:05 ET (write tomorrow's template carrying forward yesterday's posture + research_question), 06:00 ET (ntfy nudge if quiz not yet submitted), 12:00 ET (second-chance nudge). Idempotent state in `scheduler-state.json`. Weekend-quiet default (`NCL_QUIZ_NUDGE_WEEKENDS=1` to enable). Live: `[QUIZ-SCHED] morning quiz scheduler started`. (4) iOS de-clutter: NATRIX flagged "what is Councils doing here" + 9-tab clutter. Override `JournalSection.allCases` → curated 6 tabs (QUIZ · LIFE · WRITE · SEARCH · TIPS · INSIGHTS). Councils dropped from picker (still compiles for back-compat). New `.insights` case merges Today + Reflect + Analytics into one scrollable section.

- Wave 14E — Journal subsystem redesign: morning quiz + life plan + iOS surfaces. Commits NCL `d8d7991`, FirstStrike `cc5a6cc`. Full audit doc `docs/JOURNAL_REDESIGN_2026-05-25.md`. CRITICAL FINDING: Journal was structurally sound but functionally dormant — only 12 entries over 7 days, 5 of 6 daily reflections had ZERO entries to reflect on ("Recorded 0 journal entries today"). The reflection engine fires nightly into an empty pool. Root cause: no daily anchor that prompts intentional input. Five research threads synthesized: morning intention setting boosts task prioritization 40%, OKR/SMART/North-Star/12-week-year goal frameworks compose as Russian-doll, vision-first retirement (ask "what should it look like" before quantifying), habit stacking with 2-5min micro-habits, stoic Epictetus pattern. Three layers shipped: (1) Morning Quiz (`runtime/journal/morning_quiz.py` 340 LOC) — 7-question daily anchor + 5 endpoints `POST /journal/morning-quiz` + `GET /today|latest|by-date/{d}|history`; propagation creates `morning_quiz` JournalEntry + optional `lesson` JournalEntry + pins Q2 to working_context as `morning_quiz:priority` importance 100 + adds Q5 as research theme. (2) Life Plan (`runtime/life_plan/` new package — models/store/wisdom rotator, ~600 LOC) — Vision/NorthStar/Goal+KRs/Journey+Milestones/Plan+Checklist/DailyWisdom dataclasses, JSONL storage under `data/life_plan/`, 18 CRUD endpoints + `/life/dashboard` rollup, 50-entry seed wisdom corpus across 5 categories (stoic 15, operational 10, financial 10, personal 10, creative 5) with date-keyed deterministic rotation. (3) iOS (`Sources/Models/MorningQuiz.swift` + `Sources/Network/NCLBrainClient+Journal14E.swift` + `Sources/Views/Journal/MorningQuizView.swift` 340 LOC + `LifePlanView.swift` 250 LOC + JournalView patched) — QUIZ + LIFE sub-tabs as first two pickers. Wisdom card on top of quiz screen; 7-question form when not yet submitted, read-only summary when complete with EDIT/RE-SUBMIT.

- Wave 14D iter — planner trade_idea_count_target + critic enforcement. Commit `4949de2`. First live pipeline run produced an excellent brief structurally (planner+executor+critic all succeeded, score 100, zero markdown, zero stubs, 12 inline id= citations) but emitted ZERO trade ideas because the planner picked mode=short and the executor declined to fabricate setups. For NATRIX's primary use case (pre-market trading decisions), missing trade ideas is the most actionable failure mode. Three changes: planner mode bias toward "full" (any normal market day with ≥2 sources + ≥30 signals is "full" by default), new required `trade_idea_count_target` planner field (0/2/4/6 mapped from mode + data quality, must be ≥4 when PRE_MARKET_TRADE_IDEAS in include_sections), critic enforces the quota (`len(trade_ideas) >= max(2, target-1)` slack, flags as fixable→regen). Plus `pipeline_meta` now surfaces `trade_idea_target` + `trade_ideas_emitted` + `critic_reasons`. Live validation: plan_mode=full, target=6, emitted=6, 6 trade ideas (3 options + 1 stock + 1 spread + 1 futures) all with SOURCES lines, 15 inline id= citations, score 100.

- Wave 14D — Morning Brief multi-stage pipeline (Planner → Executor → Critic). Commit `9c84f9b`. Implements Phase B of `docs/MORNING_BRIEF_QUALITY_2026-05-25.md` via the Anthropic April 2026 Advisor Pattern. New `runtime/api/routers/intel/brief_pipeline.py` (1,075 LOC) with five stages: PLANNER (Sonnet 4, ~300 tokens, JSON-out — decides mode/themes/active_lanes/focus_tickers/include_sections from condensed per-source signal summary; `mode=no-edge` short-circuits to a 200-char quiet-day brief), EXECUTOR (Sonnet 4 ext. thinking, ~3500 tokens, JSON-out — each section carries `text` + `citations: [signal_id]`, trade ideas have explicit `sources: [signal_id]`; macro lanes only present for active_lanes so no "Signals quiet" stubs possible by construction), CRITIC (local Python first — checks fabricated ids, markdown, stubs, missing sources; optional Haiku 4.5 second pass gated behind `NCL_BRIEF_LLM_CRITIC=1`), REGENERATE (conditional, capped at 1 cycle), RENDERER (JSON → plain text matching iOS BriefRenderer's existing format, no iOS changes). Stage-by-stage budget gating via `NCL_BRIEF_BUDGET_*` env: degrades gracefully if executor/critic exhaust mid-chain. Cost-neutral ~$0.045/brief vs Phase A's $0.05. Handler wraps with fall-back to Phase A on any pipeline exception. `pipeline_meta` persisted to brief_data + response so each brief's generation path is observable.

- Wave 14C — Morning Brief Quality (Phase A surgical). Commit `00df9af`. Eight changes in `runtime/api/routers/intel/__init__.py` morning-brief handler from `docs/MORNING_BRIEF_QUALITY_2026-05-25.md` audit (13 concrete failure modes from real 5/25 brief — markdown leaks, empty PORTFOLIO HEALTH, silent GOAT/BRAVO, mostly-empty macro lanes, sector-ETF-dominated trade ideas, no signal_id traceability): (A1) Removed Pink Elephant anti-patterns from prompt — Anthropic 2026 research says "NEVER use X" primes attention onto X; replaced with positive direction + good-vs-weak example contrast. (A2) `_strip_markdown()` post-pass — regex sweep defangs leading/trailing `**`, `#` headers, backticks, code fences. (A3) Auto-omit empty sections — pre-fix forced "Signals quiet" stubs; new prompt omits the entire labeled paragraph if a lane has zero matching signals. (A4) Portfolio data via in-process `portfolio_mgr.get_positions()` instead of the file-read of `~/dev/NCL/data/portfolio/snapshots.jsonl` (which had a path drift bug; actual snapshots live under `~/NCL/data/`). (A5) Source-aware macro lane filters via `_lane()` helper that checks `signal.source.value` namespace first, then keyword fallback. (A6) GOAT/BRAVO scanner source detection — match on `scanner:goat`/`scanner:bravo` per `authority.py` SOURCE_TIER_MAP. (A7) Trade-idea `SOURCES: [signal_id]` citation requirement + `_format_signals` prepends `id=` to every signal line. (A8) `held_tickers` block injected into trade-idea rules so model has portfolio context for ADD TO EXISTING decisions. Live diff: 6,777 → 6,041 chars (denser), markdown leaks 1+ → 0, stubs 3-4 → 0, citations 0 → 7+4 SOURCES.

- Wave 14B — Memory Timeline city-events monoculture fix. Commit `9b7e7b7`. NATRIX flagged Memory→Timeline sub-tab on physical iPhone showing 50 events all from `AWAREBOT:CITY EVENTS:ASUNCION`. Root cause: `runtime/memory/dashboard_bridge.py::get_timeline` sorted by `created_at` desc and sliced `[:50]`. The `ncl-city-events` autonomous loop runs per-city across 7 cities and emits 50+ units in a tight window post-bounce (25 Calgary, 11 San Salvador, 5 Montevideo, 5 Asuncion, 4 Panama City within 22 seconds). Fix: single-pass diversity selector — after time-sort, walk events and skip any whose source has already hit `max_per_source` (default 5, `NCL_TIMELINE_MAX_PER_SOURCE` env knob). Access/decay events bypass the cap. If the cap is too aggressive (only 2-3 active sources), backfills from overflow so the response still hits `limit`. Bonus: fixed pre-existing contract bug — `get_timeline` returned a bare list while docstring promised `{events, degraded}` dict envelope. Live verification: 5 city-events sources monoculture → 11 distinct sources, each capped at 5.

- Wave 14A — Intel + Memory IA reorg, ship-now backend slice. Full audit + roadmap in `docs/INTEL_MEMORY_REORG_2026-05-25.md`. The Intel tab is "one Awarebot signal pool projected through seven redundant lenses" — root cause: Risk Alerts ⊂ Key Signals is guaranteed, the executive summary is the top signal's text echoed verbatim, and Working Context / Focus-the-tier / Focus-the-config are three concepts wearing the same word. The 14A ship-now slice fixes the worst of the backend bleed without the multi-day iOS restructure (deferred to 14B). Five backend changes shipped: (1) `runtime/api/routers/intel/night_watch.py` — new router with `GET /intelligence/night-watch/{latest,by-date/{d},history}` parsing `data/night-watch/daily-*.md` into structured payload for iOS (today/yesterday/newest fallback chain, raw_appendix dict, markdown_full passthrough); (2) `runtime/autonomous/night_watch/analyst.py` model IDs `claude-opus-4-6` → `claude-opus-4-20250514` + `claude-sonnet-4` → `claude-sonnet-4-20250514` — stops the nightly 4× HTTP 404 (Wave 13 EOD swept Sonnet but missed Night Watch's analyst); today's 2026-05-25 brief parsed to RED status with "Diagnose the Anthropic 404" as first recommendation, confirming the bug; (3) A2 risk-alert dedup at brief boundary via token-Jaccard ≥0.6 against `top_signals[:5]` titles — catches both substring matches and LLM rephrases; (4) A3 authority filter at brief boundary via new `_signal_authority_tier()` helper resolving source via `tier_for_source()` with CRITICAL/HIGH route-level bump SCANNER→LLM_SINGLE; default `NCL_BRIEF_MIN_AUTHORITY=20` (drops RAW only) with safeguard that passes originals through if filter would zero-out the brief — plan-doc spec said 40 but that would kill all Awarebot signals (every one is SCANNER=20), so default is permissive with the env knob documented for tightening; (5) A5 `GET /intelligence/digest` unified endpoint returning `{headline, summary, key_signals (auth-filtered), risk_alerts (deduped), working_context_top, night_watch_status, source_breakdown}` — single read for "what's happening right now", iOS adopts in 14B. Intel router net: 51 → 55 routes. Validation: ast parse OK, pyflakes clean, helpers unit-tested in isolation (auth-tier resolution + filter sanity + dedup with substring/rephrase/near-dup catches), full intel package loads + all 55 routes register. iOS-side work (NightWatchView, Brief dedup consumption, FROM CONTEXT in FOCUS) is queued for the next session; the new backend endpoints are shape-stable for that consumption.

**Prior wave summary (2026-05-24)**:
- Wave 8 — 15-agent foundation swarm: Tailscale-only bind, A/B harness, burn-in verifier, Prometheus /metrics, tracing IDs, LLM facade complete, pillar dispatch excised, SQLite double-write live on 3 tables.
- Wave 9 — 10-agent post-W8 audit + Director's synthesis.
- Wave 10 — 45-agent 3-phase implementation: stop silent bleeds + CI sanity (10A) → foundation refactors (10B) → cleanup + carves + DI completion (10C). Net: scheduler.py 7,464 → 5,032 LOC (3 night-watch monsters carved; LOC verified 2026-05-24 / Wave 13 via `wc -l runtime/autonomous/scheduler.py`), intel.py carved into package, DoubleWriteHook abstraction, central flags module, SQLite connection pool (1 writer + 4 readers), double-writes off hot path (12× speedup), correlation IDs in 5 high-volume loops, CouncilQuorum wired (autonomous-only Sonnet+Haiku pre-pass), 9 routers DI-converted, ChromaDB batched upsert (memory store only — W10B-15), predictions live SQLite write hook, /metrics separate read-only token, SQLite OperationalError retry handler, stall watchdog deadband for long-running tags, alert-dispatcher sentinel. **SQLite double-write status (verified 2026-05-25 / Wave 14G P14)**: gates `NCL_MANDATES_SQLITE`, `NCL_COST_LEDGER_SQLITE`, `NCL_UNITS_INDEX_SQLITE` are all `true` in `.env`. DB lives at `data/persistence/ncl.db` (28MB; default path from `DEFAULT_DB_PATH` in `runtime/persistence/sqlite_store.py`, NOT `data/mandates.sqlite` as earlier doc claimed). `sqlite3 ncl.db` reports: mandates 70 rows (matches `mandates.json`), cost_ledger 2,911 rows, units_index 33,005 rows + council_sessions/council_rounds/predictions/schema_migrations. JSONL stays source of truth; SQLite is the live read-fallback mirror.
- Wave 11 — YTC restructure: hourly per-video reports + 3am-local nightshift rollup; 354 reports reorganized into per-date subfolders; iOS YTC tab → 3 sections (NIGHTSHIFT / TODAY'S VIDEOS / PAST BRIEFS); 5 nightshift briefs (5/20-5/24) retro-seeded.
- Wave 12 — CouncilVectorStore singleton + batched + async-safe ChromaDB. Fixes 2026-05-24 19:20 incident (pid 27623 deadlocked 99% CPU entirely inside `chromadb_rust_bindings.abi3.so`, frozen mid-YTC-loop at video 24/33). Root cause: `_auto_ingest_report` constructed a fresh `CouncilVectorStore(data_dir)` per video → fresh `chromadb.PersistentClient` per call. 33 videos/hour × concurrent clients on the same persistent store → Rust HNSW write-lock deadlock. Compounding: every `upsert`/`query` was a sync call inside an async function blocking the event loop. Fix: `runtime/councils/shared/vector_store_singleton.py` (process-wide instance + double-checked lock); `index_documents_batch()` for one upsert per report instead of N; sync ChromaDB ops wrapped in `asyncio.to_thread`. 4 call sites migrated (runner + 3 council router handlers + LDE sandbox).
- Wave 13 — 10-agent read-only audit + 4-agent P0 fix wave + 4-agent P1/P2/P3 reconcile wave. Root-cause of "NCC residue keeps appearing": `runtime/ncl_brain/council.py:1126` CHAIR prompt was literally instructing every LLM to emit `"pillar": "NCC"` in its JSON mandate block — fixed to use `NCL` and gated by a strict pillar_map (no fallback to NCC). 10 more relative-import bugs in `runtime/api/routers/intel/__init__.py` (same morning-brief HTTP 500 class hit in Wave 12) — fixed. iOS↔Brain contract drift: 6 endpoint mismatches (working-context pin body, memory timeline key, `/intelligence/x/posts` handler, `/council/queue` handler, unpin path, portfolio `quotes_failed` field) — fixed on both sides. Sync `json.dumps(5–10MB)` on the event loop in `brain._persist_council_sessions_unlocked` (likely root of the 20:30 JSON-encoder lockup) — moved to `asyncio.to_thread`. Whisper model singleton (same anti-pattern as Wave 12 ChromaDB), stall-watchdog factory entry, 7 paid-call cost gates added at previously-unmetered sites, MemoryStore reader cache fast-path, data store integrity sweep (orphan tmp files, oversize jsonl, stale 113MB ghost embeddings, archive caps, alert pruner). This doc reconciled against live grep in the same wave.
- Wave 13 P0 followup #1 (commit `98616ad`) — `runtime/memory/working_context.py::_persist` was still doing sync `json.dumps` on the event loop. 12 call sites (every pin/unpin/note_access/assemble) each serialized 50 items × nested metadata. After the mid-day refresh at 21:28 the loop pegged the JSON encoder at 99% CPU and Brain pid 37681 hung at 17 min uptime — iOS reported offline. Fix: snapshot the dict synchronously (cheap), then `loop.create_task(asyncio.to_thread(self._do_persist_io, ...))`. Fire-and-forget safe because next `_persist()` rewrites latest. `_archive_to_history` got the same treatment. Audit miss: original P0-4 grep only covered `brain.py` persistence paths, not `memory/`.
- Wave 13 P0 followup #2 (commit `388d710`) — single careful Read pass over all 56 `json.dumps(indent=...)` callers in `runtime/`. Identified and fixed 5 more sites with the `await f.write(json.dumps(big_dict, indent=2))` pattern where `aiofiles` made the write async but `json.dumps` still ran on the loop: `autonomous/scheduler.py:4485` per-video YTC (30-50×/hr × 100KB), `:4657` nightshift rollup (500KB-1MB at 3am), `awarebot/agent.py:3747` + `:3764` duplicate awarebot YTC paths, `:3418` predictions, `councils/runner.py:1200` `_snapshot_intel_state` pre-council brief. All now `await asyncio.to_thread(json.dumps, ...)` then write. Confirmed via Read pass that the remaining 50 callers are sync-only, small-payload, or bounded-by-truncation — none on the lockup risk surface.

**Codename**: NCL (NUREALCORTEXLINK)
**Role**: Standalone personal AI brain serving NATRIX via the FirstStrike iOS app.
**Host**: Mac Studio M1 Ultra 64GB, Tailscale IP 100.72.223.123

---

## Identity

NCL is a standalone personal-AI brain. It is **not** a router or dispatcher in a multi-pillar ecosystem.

The original "Resonance Energy" architecture (NCL → NCC/BRS/AAC) has been fully retired:

- **BRS** (would-have-been tactical revenue) — never existed as a real service. Retired 2026-05-23.
- **AAC** (sibling trading-system repo at `/Users/natrix/dev/AAC`) — integration shelved. Elements (planktonxd + weatherbetter strategy scorers, IBKR connection patterns) were cherry-picked into NCL and now live entirely inside this repo with no live dependency on AAC. Pillar retired 2026-05-23.
- **NCC** — repo no longer present on this machine. Mandate dispatch path is archived. The Brain's `_dispatch_to_ncc()` helper is a vestigial sink that writes to a non-existent intake directory.

What NCL **is** today:
- FastAPI service on port 8800 (`runtime/api/routes.py:versioned_app`)
- 35 in-process autonomous loops (memory consolidation, calendar correlation, awarebot intel, council auto-spawn, journal reflection, working-context assembly, portfolio sync, etc.) <!-- verified 2026-05-24 / Wave 13 — 35 unique `ncl-*` task names in runtime/autonomous/scheduler.py incl. supervisor; +1 since Wave 10 = `ncl-ytc-nightshift` -->

- Memory subsystem: 25K MemUnits, ChromaDB vectors, BM25 keyword index, NetworkX knowledge graph, 7-tier authority weighting, Beta-Bernoulli source-authority learner, ACE reflection, conflict resolver, narrative threads, PII redactor, async write queue
- Multi-LLM council system (Claude chairs; Grok, Gemini, Perplexity, GPT, Copilot as members). Universal context pack at `runtime/council_pack/` consolidates assembly + MMR + temporal split + contradictions surfacing + position trick + 40% utilization cap + MapReduce compression + Anthropic Citations API document blocks + calibrated verbalized confidence + anonymized peer review + 3-tier hierarchical write-back
- Awarebot intelligence pipeline with 6-factor scoring + exclusive tier routing (focused/micro/macro)
- Local portfolio integration (IBKR, Moomoo, SnapTrade, NDAX, MetaMask, Polymarket) feeding FirstStrike's Portfolio tab
- Calendar system (lunar, market events, 7-city local events)
- Journal store with daily LLM reflection
- Cost tracker with per-source budget enforcement and a $20/day platform-wide hard cap

**Authority**: NATRIX (absolute) → NCL (standalone). No downstream pillars.

---

## Archived Subsystems (2026-05-23)

The pump → council → mandate → pillar pipeline was MERGED into the Brain. The legacy file-queue scaffolding around it was moved to `archive/`:

| Was | Where it lives now |
|-----|--------------------|
| `runtime/pump_watcher.py` | `archive/strike-point-pre-merge/pump_watcher.py` — replaced by Brain `POST /pump` endpoint (`routes.py:795`) |
| `runtime/strike_point_orchestrator.py` | `archive/strike-point-pre-merge/strike_point_orchestrator.py` — replaced by Brain `receive_pump_prompt(auto_flow=True)` at `runtime/ncl_brain/brain.py:312-399`, which runs the full strike-point flow in-process |
| `runtime/execution_loop.py` | `archive/strike-point-pre-merge/execution_loop.py` — Copilot/Claude-Code subprocess bridge, separately dead (manual-mode fallback since May 22) |
| `tests/test_pump_watcher.py` | `archive/strike-point-pre-merge/` |
| `mandate-generation/` directory tree (input/, processed/, failed/, output/) | `archive/strike-point-pre-merge/mandate-generation/` — preserved with 21 historical processed pumps + 5 stuck AAC War Room sweeps |
| `workspaces/execution-pipeline/` | `archive/strike-point-pre-merge/execution-pipeline/` — MWP stage directories |
| `com.resonanceenergy.ncl-watcher.plist` | `archive/launchd-disabled/` — `launchctl bootout`'d |
| `com.resonanceenergy.ncl-orchestrator.plist` | `archive/launchd-disabled/` — `launchctl bootout`'d |
| `feedback-synthesis/{brs,aac,ncc}-reports/` + senders | Neutralized in place by A03b (2026-05-23). BRS/AAC sender stubs exit 1; READMEs marked RETIRED. |
| Stale Apr-May docs (`RESONANCE_ENERGY_SOT.md`, `RUNTIME_GUIDE.md`, `BUILD_SUMMARY.md`, `INDEX.md`, `MANIFEST.txt`, `STRUCTURE.md`, `README.md`, `CONTEXT.md`, `AUDIT_brain.md`, `WORKSPACES_INDEX.md`, `shared/doctrine/AGENTS.md`, `shared/doctrine/paperclip.config.json`, `shared/doctrine/NARTIX-Ecosystem-Build-Plan.md`) | `archive/docs-pre-retirement/` — all described an architecture that no longer exists |

The Brain has been verified healthy post-archive: pid still serving 8800, FirstStrike iOS connections ESTABLISHED.

**Stale mandate cleanup (2026-05-24)**: After A03b retired the BRS/AAC enum values, `data/mandates.json` still held 21 mandates with `target_pillar: 'brs'` or `'aac'` that the Pydantic model now rejects on `load_state()` — 105 ERROR lines per boot. Pruned via `scripts/prune_retired_pillar_mandates.py` (idempotent, takes a timestamped `.pre-prune-*.bak` backup, drops only retired-pillar entries). 70 NCC mandates retained because the NCC enum value is kept for back-compat. Re-run the script if the mandate file ever regrows retired-pillar entries.

**Strike Point pipeline — current architecture**:
iOS `POST /pump` → Brain `routes.py:receive_pump_prompt` → `runtime/ncl_brain/brain.py:receive_pump_prompt(auto_flow=True)` → `spawn_council_session()` → `_extract_mandates_from_council()` → council write-back via async writer → memory persistence. All in-process, no file queue, no external dispatch.

**iOS pump transport**: defaults to Brain Direct (port 8800). Relay mode (port 8787 via `/Users/natrix/Projects/FirstStrike/relay-pump-endpoint.py`) is a fallback that requires explicit toggle in iOS settings; relay still drops files to `archive/strike-point-pre-merge/mandate-generation/input/` if exercised, but nothing reads them anymore.

---

## Runtime System

NCL Brain API runs as a **FastAPI service on port 8800** with 289+ route decorators across 20+ categories. The runtime layer is autonomous and persistent. <!-- verified 2026-05-24 / Wave 10 — `grep -rE "@\w+\.(get|post|put|delete|patch)\(" runtime/` = 323 raw matches; ~289 unique routes after stripping duplicate decorators on the same handler -->

### Autonomous Scheduler — 35 Active Named Tasks (verified 2026-05-24 / Wave 13)

| # | Task name | Method | Cadence | Status |
|---|-----------|--------|---------|--------|
| 1 | `ncl-awarebot-agent` — 8-source scanning, 6-factor scoring, tier routing, intel briefs, predictions (internal YTC sub-task DISABLED) | `Awarebot.run()` | per-source rate limits | ACTIVE (X 402; Crypto disabled) |
| 2 | `ncl-council-auto` — Delphi-MAD debate on 3+ converging signals or 4hr review | `_council_auto_loop` | 5m poll | ACTIVE |
| 3 | `ncl-memory` — decay + prune + cluster + merge + ChromaDB reindex | `_memory_consolidation_loop` | 1hr | ACTIVE |
| 4 | `ncl-workspace` — MWP pipeline stage health | `_workspace_health_loop` | 30m | ACTIVE |
| 5 | `ncl-mandate-purge` — hygiene against state-leak | `_mandate_purge_loop` | 6hr | ACTIVE |
| 6 | `ncl-feedback-synth` — pillar reports → synthesis notes | `_feedback_synthesis_loop` | 5m | ACTIVE |
| 7 | `ncl-heartbeat` — JSONL liveness + watchdog (alerts via central dispatcher) | `_heartbeat_loop` | 60s | ACTIVE |
| 8 | `ncl-working-ctx` — 6am assembly, noon refresh, 11pm EOD | `_working_context_loop` | 3x daily | ACTIVE |
| 9 | `ncl-journal-reflection` — Sonnet 4 daily synthesis (`claude-sonnet-4-20250514`) | `_journal_reflection_loop` | 10pm ET daily | ACTIVE |
| 10 | `ncl-night-watch` — 5-phase maintenance (M1 is now a no-op that reads `last_dedup_scan_merged_24h`) | `_night_watch_loop` | 2am ET nightly | ACTIVE |
| 11 | `ncl-calendar-agent` — lunar/market/local event correlation | `CalendarAgent.run()` | per-agent | ACTIVE |
| 12 | `ncl-calendar-alerts` — push critical/high alerts (via central dispatcher) | `_calendar_alert_check_loop` | 10m | ACTIVE |
| 13 | `ncl-health-rollup` — aggregated component status → `data/health/current.json` + `/system/health/rollup` | `_health_rollup_loop` | 60s | ACTIVE |
| 14 | `ncl-cost-rollover` — UTC-midnight cost ledger close + JSONL `cost_day_closed` audit | `_cost_rollover_loop` | 60s poll | ACTIVE |
| 15 | `ncl-cache-warmer` — pre-touches calendar (7d/30d) + todos + sun + working context | `_cache_warmer_loop` | 5m | ACTIVE |
| 16 | `ncl-alert-dispatch` — centralized rate-limited (1/10s) + deduped (1h per-key) ntfy queue | `_alert_dispatch_loop` | 10s tick | ACTIVE |
| 17 | `ncl-ytc-dedicated` — YouTube Council with own $3/day cap; dedup window 1d | `_ytc_dedicated_loop` | 1hr | ACTIVE |
| 17b | `ncl-ytc-nightshift` — 3am-local YTC rollup that consolidates the day's per-video reports into a single nightshift brief (Wave 11) | `_ytc_nightshift_loop` | 3am local daily | ACTIVE <!-- added Wave 13 verification 2026-05-24 — present in scheduler.py but missing from prior doc table --> |
| 18 | `ncl-bm25-rebuild` — BM25 keyword index rebuild for FusedRetriever | `_bm25_rebuild_loop` | 30m | ACTIVE |
| 19 | `ncl-memory-eval` — weekly 50 Q/A regression eval; hit@5 / MRR / recall@10; ntfy on regression | `_memory_eval_loop` | Sun 3am ET | ACTIVE |
| 20 | `ncl-chroma-gc` — purges orphaned ChromaDB embeddings (zero-ghost collections now preserved in output) | `_chroma_gc_loop` | 1hr | ACTIVE |
| 21 | `ncl-conflict-arb` — `contradicts` edge detection + council arbitration; cap 50/cycle, adaptive cadence | `_conflict_arb_loop` | 5/10/15m (backlog-adaptive) | ACTIVE |
| 22 | `ncl-staleness` — re-verifies high-importance facts (≥70) using `created_at` (not `last_accessed`) | `_staleness_loop` | 6hr | ACTIVE |
| 23 | `ncl-narrative-threads` — cross-session entity threading; ties related units into named narratives | `_narrative_threads_loop` | 6hr | ACTIVE |
| 24 | `ncl-async-writer` — fire-and-forget memory write queue (4 drainers, Sonnet 4 enrichment, budget-gated) | `AsyncWriter.run()` | continuous | ACTIVE |
| 25 | `ncl-memory-budget` — per-tier token-spend rollup + cap-exceed ntfy | `_memory_budget_loop` | 15m | ACTIVE |
| 26 | `ncl-dedup-scan` — sliding-window 500-unit M1 dedup (lifted out of Night Watch after 30m timeout) | `_dedup_scan_loop` | 6hr | ACTIVE |
| 27 | `ncl-claude-md-refresh` — re-ingests `CLAUDE.md` as procedural memory (importance 90, BRAIN tier) | `_claude_md_refresh_loop` | 24hr | ACTIVE |
| 28 | `ncl-stall-watchdog` — detects + alerts on stalled scheduler tasks | `_stall_watchdog_loop` | continuous | ACTIVE <!-- added Wave 10 verification 2026-05-24 --> |
| 29 | `ncl-city-events` — per-city local-events refresh loop | `_city_events_loop` | per-loop | ACTIVE <!-- added Wave 10 verification 2026-05-24 --> |
| 30 | `ncl-stocks-scan` — internal stocks/market scan loop | `_stocks_scan_loop` | per-loop | ACTIVE <!-- added Wave 10 verification 2026-05-24 --> |
| 31 | `ncl-haiku-ab-monitor` — Haiku A/B model rollout monitor | `_haiku_ab_monitor_loop` | per-loop | ACTIVE (gated) <!-- added Wave 10 verification 2026-05-24 --> |
| 32 | `ncl-sqlite-burnin-verify` — SQLite burn-in verification probe | `_sqlite_burnin_verify_loop` | per-loop | ACTIVE (gated) <!-- added Wave 10 verification 2026-05-24 --> |
| 33 | `ncl-startup-migrations` — one-shot startup data migrations | `_startup_migrations` | one-shot at boot | ACTIVE <!-- added Wave 10 verification 2026-05-24 --> |
| + | `ncl-supervisor` — monitors and restarts crashed tasks (max 3 restarts) | `_supervisor_loop` | 30s | ACTIVE (supervises itself) |

> Active set: 34 named work tasks + supervisor = **35 unique `ncl-*` names** in `runtime/autonomous/scheduler.py` (verified 2026-05-24 / Wave 13 via `grep -oE 'name="ncl-[a-z0-9-]+"' runtime/autonomous/scheduler.py | sort -u | wc -l`). Plus 4 async-writer drainer subtasks reported individually in `/autonomous/loops`. The +1 since Wave 10 is `ncl-ytc-nightshift` (row 17b above).

**Removed since prior doc:** `_aac_sync_loop` (folded into Night Watch Phase 1) and the previously-listed `ncl-awarebot-brief` — that task name has no `create_task(..., name="ncl-awarebot-brief")` in `runtime/autonomous/scheduler.py` and was a doc artifact (verified 2026-05-24 / Wave 10).

**Dormant / not yet wired:** `X Liked Videos` (READY — needs OAuth token).

**Dead code formerly listed** (`_scanner_loop`, `_prediction_loop`, `_intel_collection_loop`, `_intel_brief_loop`, `_morning_brief_loop`, `_weekly_strategy_loop`): physically removed from scheduler.py — do not re-introduce.

### API Endpoints (current 2026-05-22 EOD)

| Endpoint | Purpose |
|----------|---------|
| `GET /memory/search/fused?q=...&top_k=N` | Vector + BM25 + entity-graph via RRF. Surfaces `tier`+`signal_id`. `NCL_FUSION_MIN_SCORE` env knob |
| `GET /memory/by-authority?min_tier=council` | Filter recall by authority tier |
| `POST /memory/backfill-authority` / `POST /memory/retag-authority` | One-shot migrations (both already run; **14,144 units** now in `data/memory/units.jsonl`, verified 2026-05-24 / Wave 13 via `wc -l`) |
| `POST /memory/bootstrap-claude-md` | Ingest CLAUDE.md files as procedural memory |
| `POST /memory/kg-cleanup` | Purge URL/domain noise nodes (one-shot) |
| `GET /memory/budget` / `/memory/budget/history` / `/memory/budget/check` | Per-tier token-spend telemetry |
| `GET /memory/async-writer/{stats,dlq,retry-dlq}` | Async writer queue stats + DLQ inspection/retry |
| `GET /memory/pii/recent` | Recent PII redactions (audit) |
| `POST/DELETE /memory/working-context/pin` | Pin/unpin items; JSON body or query param |
| `GET /system/memory-profile` | RSS / objects / buffer sizes |
| `GET /system/health/rollup` | Brain, scheduler, Awarebot, costs, councils, memory (units fixed via async-aware `get_stats()`), calendar, portfolio. Persisted to `data/health/current.json` |
| `GET /council/quality` | Auto-fixes stuck DEBATING sessions + counters |
| `GET /pump/health` | Pump pipeline health (`mandate-generation/{input,processed,failed}`) |
| `GET /intelligence/stats` | Awarebot Intel header: `signal_count`, `source_count`, `last_scan_at`, `signals_routed`, `high_critical_count` |
| `GET /focus/queries` / `GET /focus/subreddits` | iOS shape: `queries.{x,youtube,reddit}` + `subreddits.{tier_1,tier_2,tier_3}` + `_meta` |
| `POST/DELETE /focus/queries` + `/focus/subreddits` | Accept tier as bare digit `1`/`2`/`3` |
| `GET /youtube/reports/recent?limit=N` | Recent YTC + YouTube reports, dedup by `video_id` |
| `GET /predictions` | Each item: cleaned `description`, `direction` (regex classifier), `models` (parsed from `[Consensus: lead=X][Y concurs]`), `linked_signals` |
| `GET /autonomous/loops` | 35 loops with correct `last_run` (verified 2026-05-24 / Wave 13) |
| `GET /portfolio/accounts` | `positions_count` propagation fixed |
| `GET /portfolio/options-flow` | **NEW EOD** — top-20 grouped by ticker with premium splits + call/put ratio + `is_held_in_portfolio` flag |
| `GET /calendar/events/compiled?window=30` | Auto-excludes first 7 days; scanner contribution capped at 30% (was 93%) |

### Fixes Shipped Today (EOD swarm, commit `25c3710`)

**P0 — model + lock + crash**
- Model 17-site sweep: `claude-sonnet-4-6-20250514` → `claude-sonnet-4-20250514` (was returning HTTP 404)
- MemoryStore reader-counter lock leak: replaced ad-hoc Lock+counter+Event with `asyncio.Condition` (writer-preference, no lost-wakeups). 500 writes 16s → 0.87s
- `awarebot-x-liked` crash: `self._shutdown_event` → `self._running`
- Health rollup `memory.units=0`: `get_stats()` is an async coroutine — now properly awaited + `units.jsonl` line-count fallback
- YTC `_auto_ingest_report` migrated from sync `httpx` to `async_writer.enqueue` (was blocking 2N+1 roundtrips per session)
- Staleness selector now reads `created_at` (was `last_accessed`, bumped by working-context refresh)
- ChromaDB GC now preserves zero-ghost collections in output (was dropping them)
- M1 dedup lifted into own 6h loop (was timing out at 30min inside Night Watch on false-positive comparator)
- `MAX_TOTAL_UNITS` 10K → 25K (was thrashing eviction every ~4s)
- Anthropic daily cap $5 → $12 (was hitting cap by 18:00 ET) <!-- value verified 2026-05-24 / Wave 10 against runtime/cost_tracker.py:53 `"anthropic": 12.00`; prior doc said $15 — drift -->

- `first-strike-chat` re-tagged NATRIX(100) → CALENDAR(50) (was polluting TSLA searches)

**P0 — council + pump + KG + budget (final swarm)**
- Council runner persistence: every session since 2026-05-17 was persisting at `status=DEBATING` but never updating final state. Now force-persists. 9 stuck sessions auto-marked failed
- Pump pipeline: real path is `mandate-generation/{input,processed,failed}` (not `data/pumps/*`). Strike Point orchestrator unblocked: `httpx` install + MANDATE-2026-008 empty-pillar handling
- Bounded `contradicts_index.jsonl` at 5MB (was 30MB append-only; OOM risk)
- Calendar 3-city notable_dates backfilled (panama_city, montevideo, asuncion). Compiled events 521→19; scanner-sourced 487→45
- KG entity extractor blacklists `*.com` domains + yfinance sector buckets. Top-10 entities 100% noise (reddit.com 9774) → 100% real (Claude Code, Council Insight)
- Authority retag: NATRIX(100) units 305→3. Polluted units (`portfolio:significant_move`, chat fragments) demoted to BRAIN(60)
- CLAUDE.md ingested as procedural memory (importance 90, BRAIN tier) via new 24h refresh loop
- Async writer budget gates: every Sonnet enrichment checks `can_spend("anthropic", 0.01)` BEFORE the API. 429/529/503 → 3 retries exp backoff. 401/403/404 → DLQ + ntfy
- `create_unit` lifts Awarebot `route_level` onto `unit.tier` (focused/micro/macro), stamps `authority_tier` from source
- Portfolio quotes feed: field-name mismatch fixed (`current_price` vs `last_price`). New `quote_ok` flag. Absurd `daily_pl_pct` clamped

### KNOWN ISSUES

| Issue | Impact | Fix needed |
|-------|--------|-----------|
| **X/Twitter DISABLED** | Scanner ON HOLD per NATRIX (May 19). API 402 + cost overrun. Set `X_SCANNER_ENABLED=true` in .env to re-enable. | Renew subscription |
| **Paperclip not deployed** | Adapter wired but backend never existed. **MITIGATED** by `runtime/cost_tracker.py`. | Paperclip is dead code; cost_tracker.py owns this |
| **BRS Dashboard (legacy stub)** | Pillar retired 2026-05-23 — the start-all.sh stub at port 8000 is unused dead weight. | Remove from start-all.sh |
| **CoinGecko rate limiting** | Crypto source disabled (60s+ delays). | Alternative source or paid tier |

### Tailscale Mesh (verified GREEN EOD 2026-05-22)
All 3 peers on direct LAN — no DERP relay:
- Mac Studio: `100.72.223.123` (host)
- iPad (GRIP AND RIPP HDD): `100.76.184.123` (9ms)
- iPhone (Nathan's iPhone): `100.82.59.60` (19ms)

### Background — Earlier Hardening (May 19-22, 2026)
Brief summary of pre-EOD work, kept for context. Detailed list lives in git.
- **Night Watch agent**: 5-phase overnight cycle ($0.88/night typical). M1 dedup now offloaded to dedicated `ncl-dedup-scan` loop.
- **Cost tracking**: `record_cost()` wired to 20+ LLM call sites. ntfy on 80% / 100% / supervisor restart-exhaustion.
- **Supervisor self-healing**: `_supervisor_loop()` monitors all tasks, auto-restarts up to 3×.
- **SnapTrade options**: `options.list_option_holdings` per account.
- **Awarebot single-scorer**: 6-factor composite. Tier routing in-Awarebot. Warm-start reloads last 48h.
- **Sources re-enabled** (May 20): Google Trends, Polymarket, News, Unusual Whales.
- **Memory plumbing**: Auth fixed, ChromaDB ghosts fixed, `$AAPL` regex, `get_stats()` uses actual `memory_type`/`by_type`/`by_tier`.
- **Memory subsystem (morning 2026-05-22)**: BM25, FusedRetriever, async writer, PII redactor, narrative threads, conflict resolver, staleness detector, authority tiers, weekly eval harness, ChromaDB GC, memory budget telemetry. Centralized AlertDispatcher (1/10s rate-limit, 1h dedup). All shipped earlier today — EOD work patched their P0 bugs.

### Scoring System — Single Scorer (Awarebot)

Awarebot scores every signal on ingest using a 6-factor composite (0.0-1.0 scale):

| Factor | Weight | Source |
|--------|--------|--------|
| Context Relevance | 30% | BM25 against watch queries + mandate/working-context keyword matching |
| Freshness | 20% | HN-gravity decay |
| Cross-Source | 15% | Token overlap confirmation from other sources (0/1/2/3+ confirming) |
| Source Confidence | 15% | Baseline authority + engagement + scanner-provided confidence |
| Actionability | 10% | Direction, % change, confidence, tags, URL |
| Novelty | 10% | SimHash near-dupe detection + exponential decay |

### Tier Routing (Awarebot internal, single-pass exclusive)

| Tier | Threshold | Age | Max | Description |
|------|-----------|-----|-----|-------------|
| **Focused** (green) | ≥ 0.75 | < 4h | 10 | Act now — sorted by cross-source then score |
| **Micro** (orange) | ≥ 0.50 | < 24h | 10 | Trending today |
| **Macro** (blue) | ≥ 0.30 | > 24h or narrative source | 10 | Persistent narratives |

Signals claimed exclusively (highest tier wins). API endpoints call `awarebot.route_to_tiers()` directly — no re-scoring on request.

### Active Intelligence Sources
| Source | Method | Status |
|--------|--------|--------|
| **Reddit** | RSS pre-scan + API (55 subreddits in 3 tiers) | WORKING — ~147+ signals per cycle |
| **YouTube** | yt-dlp channel scanning + per-video council reports | WORKING |
| **X/Twitter** | API v2 search | BROKEN — 402 Payment Required (circuit breaker active) |
| **X Liked Videos** | OAuth 2.0 + yt-dlp + Whisper transcription | READY — needs OAuth setup + X credits |
| **Google Trends** | pytrends | ACTIVE (re-enabled May 20) |
| **Polymarket** | Public REST API | ACTIVE (re-enabled May 20) |
| **News** | NewsAPI/GNews/RSS | ACTIVE (re-enabled May 20) |
| **Crypto** | CoinGecko free tier | DISABLED — rate limiting causes 60s+ delays |
| **Options Flow** | Unusual Whales API | ACTIVE (re-enabled May 20) — runs if API key set |

### YouTube Council — Per-Video Reports (added May 19, 2026)
YTC now produces one deep-dive report per video (full 150K char transcript budget each) plus a cross-video rollup. Reports stored in `intelligence-scan/council-reports/` and `intelligence-scan/youtube-reports/`, each ingested into ChromaDB and memory separately.

### X Liked-Video Pipeline (added May 19, 2026)
Tracks NATRIX's liked videos on X via OAuth 2.0 user auth, downloads via yt-dlp, transcribes with Whisper, analyzes per-video, stores reports + transcripts in long-term memory. Autonomous scan every 6h when OAuth token is available. Setup: set `X_OAUTH_CLIENT_ID`/`X_OAUTH_CLIENT_SECRET` in `.env`, call `POST /x/oauth/authorize`.

### Memory System (Hardened May 22, 2026 EOD)
**MemoryStore**: **25K unit capacity** (bumped from 10K — was thrashing eviction every ~4s), **14,144 units** now in `data/memory/units.jsonl` (verified 2026-05-24 / Wave 13 via `wc -l`; up from the ~12,792 Wave-10 figure and the ~9,711 May-22 EOD retag figure). Seven-layer architecture inspired by MemGPT/Letta + Mem0, plus Zep/Graphiti bi-temporal KG edges.

**Core Features:**
- Two-speed decay (FadeMem): LML 0.999/day (facts, decisions, preferences, procedures), SML 0.95/day (signals, episodes)
- 6 typed ChromaDB collections + legacy default; auto-reindex after consolidation
- LLM importance scoring + entity extraction on **Sonnet 4** (model id `claude-sonnet-4-20250514`)
- Knowledge graph: NetworkX DiGraph + JSONL persistence. URL/domain noise blacklisted at extractor
- Reflection loop (ACE): quality, fingerprint dedup, conflict detection
- Working Context: hybrid relevance (60% vector + 40% keyword), salience baked with **authority tier**, capacity capped at 50
- Reader/writer concurrency now `asyncio.Condition` (writer-preference); 500 writes 16s → 0.87s
- `contradicts_index.jsonl` bounded at 5MB (was 30MB append-only)

**Authority Tiers** — every unit stamped with provenance weight; baked into salience in `working_context.py` and FusedRetriever rank weighting in `fusion.py`. Post-retag, NATRIX(100) shrunk 305→3 (polluted `portfolio:significant_move` + chat fragments demoted to BRAIN(60)).

| Tier | Weight | Source |
|------|--------|--------|
| NATRIX | 100 | Direct user directives |
| COUNCIL | 80 | Council deliberation output |
| BRAIN | 60 | Brain-synthesized reflections / briefs |
| CALENDAR | 50 | Calendar/event-derived facts |
| LLM_SINGLE | 40 | Single-model LLM output |
| SCANNER | 20 | Awarebot scanner signals |
| RAW | 10 | Unscored ingest |

**New Memory Subsystem Modules (`runtime/memory/`)** — added 2026-05-22:
- `async_writer.py` — fire-and-forget memory write queue (4 drainers, Sonnet 4 enrichment in background; model id `claude-sonnet-4-20250514` — the "4.6" `claude-sonnet-4-6-20250514` string was returning HTTP 404 and was swept out in the EOD model fix)
- `chat_context.py` — chat amnesia fix; builds context block injected into `/chat`
- `chroma_gc.py` — orphaned-embedding purger
- `conflict_resolver.py` — `contradicts` edge detection → council arbitration queue
- `staleness_detector.py` — re-verifies high-importance facts against current signals
- `narrative_threads.py` — cross-session entity threading
- `pii_redactor.py` — on-write PII scrubber, 10 patterns, Tailscale-IP allowlist
- `procedural.py` — Night Watch Phase 2.6 skill distillation
- `temporal.py` — bi-temporal KG edges (Zep/Graphiti pattern)
- `authority.py` — 7-tier provenance system
- `budget_tracker.py` — memory context budget telemetry
- `eval/` (4 files) — weekly 50 Q/A regression harness (hit@5 / MRR / recall@10)
- `retrieval/` (3 files) — BM25 + FusedRetriever with Reciprocal Rank Fusion

**Data:** `data/memory/` (units.jsonl, chromadb/, knowledge_graph/, working_context/, bm25_index/, eval/, pii_log/)

### Journal System
Full daily journal with 9 entry types. JSONL persistence, full-text search, tag filtering. ReflectionEngine runs LLM synthesis at 10pm ET daily. Working — 2 reflections generated May 18-19. Data at `data/journal/`.

### Council System
Multi-LLM debate engine (Claude chairs; Grok, Gemini, Perplexity, GPT as members). Mandate extraction, governance pipeline, v2 runner with RAG + replay. Council outputs go to MemoryStore (not to `data/councils/` — those dirs are empty). Auto-spawn triggers on 3+ converging signals.

### Cost Tracker (added May 19, 2026) — REPLACES PAPERCLIP
Real, file-backed cost tracking with per-source daily budget enforcement. Every paid API call records to a JSONL append-only ledger (`data/costs/cost_ledger.jsonl`). Daily summaries survive restarts via replay.

**Budget Caps (daily, USD):**
| Source | Daily Cap | Override Env Var |
|--------|----------|-----------------|
| x_twitter | $2.00 | NCL_BUDGET_X_TWITTER |
| anthropic | $12.00 | NCL_BUDGET_ANTHROPIC |
| xai | $2.00 | NCL_BUDGET_XAI |
| openai | $2.00 | NCL_BUDGET_OPENAI |
| google | $2.00 | NCL_BUDGET_GOOGLE |

> Anthropic raised $5 → $12 EOD 2026-05-22 (was hitting cap by 18:00 ET after Sonnet-everywhere migration). <!-- value verified 2026-05-24 / Wave 10 — earlier doc said $15 but `runtime/cost_tracker.py` shipped with $12 -->


**Enforcement**: Budget check runs before every paid API call. 80% warning logged, 100% hard stop blocks the call + push notification sent (via ntfy/Pushover). Platform-wide $20/day hard cap. Date rollover at midnight UTC resets totals.

**Instrumented callers**: Scanner (X tweets), YouTube analyzer (Anthropic/xAI), Brain council (Claude/Grok/Gemini), Council orchestrator (Claude/Grok), Council runner agents (Claude/Grok).

**API endpoints**: `GET /system/costs` (today's summary), `GET /system/costs/today` (detailed), `GET /system/costs/history` (30-day), `GET /system/costs/ledger` (raw entries), `POST /system/costs/record` (manual entry).

**X scan interval**: Reduced from 5min to 30min (was burning $25-36/day via 2,304 calls/day).

### Paperclip — DESIGNED BUT NOT DEPLOYED (SUPERSEDED)
Paperclip was designed as the agent orchestration backbone but no real backend was ever deployed. Cost tracking is now handled by `runtime/cost_tracker.py` instead. The original `runtime/paperclip_adapter/client.py` has been removed from disk — only the in-repo `paperclip_mock.py` and `config/paperclip` config stub remain (verified 2026-05-24 / Wave 10 via `find . -name "paperclip*"`). CostGate in `runtime/swarm/cost_gate.py` still references Paperclip but falls back to in-memory bookkeeping since the adapter and the backend never existed.

---

## Infrastructure

### Services (Mac LaunchAgents — current 2026-05-23)
| Plist | Process | Port | Lifecycle | Status |
|-------|---------|------|-----------|--------|
| `com.resonanceenergy.ncl-brain.plist` | Brain API (`uvicorn runtime.api.routes:versioned_app`) | 8800 | KeepAlive, RunAtLoad | **LIVE** |
| `com.resonanceenergy.relay.plist` | Relay pump endpoint (FirstStrike repo) | 8787 | RunAtLoad | Live but idle (iOS defaults to Brain Direct) |
| `com.resonanceenergy.ncl-councils.plist` | Council sweep | — | Every 6h, no RunAtLoad | Live (autonomous council loop in Brain also runs this on 5m poll) |
| ~~`com.resonanceenergy.ncl-orchestrator.plist`~~ | ~~Strike Point orchestrator~~ | — | — | **ARCHIVED 2026-05-23** — strike point merged into Brain `auto_flow`. Plist in `archive/launchd-disabled/`. |
| ~~`com.resonanceenergy.ncl-watcher.plist`~~ | ~~Pump watcher~~ | — | — | **ARCHIVED 2026-05-23** — Brain `/pump` endpoint absorbed this function. Plist in `archive/launchd-disabled/`. |

### Adjacent Services (independent processes)
| Service | Port | Status |
|---------|------|--------|
| Ollama | 11434 | Local LLM, live |
| ~~NCC Relay / Master~~ | ~~8787 / 8765~~ | Repo absent from disk. Any code path that references NCC is vestigial. |
| ~~One-Drop~~ | ~~8123~~ | Not currently running. Pre-retirement service, not in scope. |
| ~~AAC Monitor~~ | ~~8080~~ | Retired 2026-05-23. |
| ~~BRS Dashboard~~ | ~~8000~~ | Retired 2026-05-23. |
| ~~Paperclip~~ | ~~3100~~ | Never deployed. Cost tracking handled by `runtime/cost_tracker.py`. |

### Key Config
- **Tailscale IP**: 100.72.223.123
- **Brain port**: 8800
- **Relay port**: 8787
- **API keys**: `~/dev/NCL/.env` (sourced by `scripts/launch-brain.sh`)
- **Python**: `/opt/homebrew/bin/python3` (NOT Xcode's python3.9)
- **FirstStrike iOS**: 72+ commands, Brain Direct + Relay dual-mode, **6 bottom tabs** (Dashboard/Portfolio/Intel/Memory/Calendar/Journal) — Settings now lives behind gear icon in Dashboard header. Portfolio has 5 sub-tabs (Portfolio/GOAT/Bravo/Paper/OPTIONS), Intel has 9, Calendar has 6, Memory has 4
- **Physical iPhone**: `00008130-000675C822A2001C` (Nathan's iPhone)
- **Physical iPad**: `00008027-001664301E07002E` (GRIP AND RIPP HDD)
- **iPhone 16e Sim**: `9F77D8B9-90B7-49F5-A654-BF6CE34F1D60`
- **iPad Pro M5 Sim**: `CE298CEE-1125-4090-8847-116691BE501B`

### Authority Chain (current 2026-05-23)
```
NATRIX (absolute)
  |
NCL Brain (standalone — owns memory, councils, intel, calendar, journal, portfolio)
  |
FirstStrike iOS (the interface)
```

No downstream pillars. The Brain is the terminus.

> Historical context: the "Resonance Energy" architecture aimed for NCL → NCC/BRS/AAC pillar handoff. That doctrine was retired in stages — BRS never shipped, AAC integration was shelved (elements cherry-picked into NCL), and the NCC repo was removed from this machine. Mandate dispatch is now an in-process Brain concept, not an external service call.

**Key Rule**: NCL is the whole product. Treat mandates, council outputs, and feedback as Brain-internal artifacts persisted to memory — not as RPC payloads to external pillars.

---

## DO NOT TOUCH — Critical Rules

These rules exist because previous Claude sessions broke production by ignoring them.

### 0. NEVER send NATRIX terminal commands to run (added 2026-05-22)
Claude has direct shell access via `mcp__Control_your_Mac__osascript` (runs commands on Mac), `mcp__workspace__bash` (sandbox Linux), and `mcp__Claude_in_Chrome__*` (browser automation). Use these to execute EVERYTHING — git commits/pushes, curl probes, launchctl kickstarts, file edits, API key updates, build commands, etc.

**Do NOT paste shell commands into chat for NATRIX to copy and run.** If a fix needs `curl -X POST /memory/kg-cleanup`, run it via osascript yourself. If a key needs to land in `.env`, write it via the file tools or via osascript awk. If a build needs to run, launch xcodebuild via osascript and poll the result.

The only time it's acceptable to surface a command to NATRIX is when it requires credentials only NATRIX has (e.g., a password prompt that bypasses the OS keychain, or an interactive 2FA flow). Even then, prefer the in-browser path via Claude in Chrome first.

Past mistake: pasting verification curls + setup-script invocations as instructions instead of just running them. NATRIX explicitly said "stop sending me terminal inputs find another way".

### 1. Mac LaunchAgents own the service lifecycle — NOT Cowork
All NCL services run via macOS LaunchAgents. The Brain's internal autonomous scheduler handles ALL intelligence sweeps, council triggers, memory consolidation, working context, journal reflections, etc.

**NEVER create Cowork scheduled tasks that duplicate Brain scheduler functionality.**
**NEVER modify, rewrite, or "improve" LaunchAgent plist files.**
**NEVER strip API keys from plists or refactor them into wrapper scripts.**
**NEVER create new startup scripts or wrapper scripts for existing services.**

If a LaunchAgent needs fixing, diagnose the issue and make the minimal targeted fix. Do not rewrite the file.

### 2. Python environment
Use `/opt/homebrew/bin/python3` — NOT Xcode's python3.9 (missing dependencies). When installing packages: `pip3 install --break-system-packages <pkg>`.

### 3. API keys live in `~/dev/NCL/.env`
The `.env` file is sourced by `scripts/launch-brain.sh` at startup. Do not hardcode keys in plists, do not move keys between files, do not create new env sourcing mechanisms.

### 4. Do not claim things are "disabled" without verifying
If disabling a source/feature, it must be done via a config flag or by removing the call from code. Verify the change is reflected at runtime. Do not just mark a task as "completed" without testing.

### 5. Do not create stubs or mocks for missing services
If a service doesn't exist (Paperclip never deployed; BRS/AAC/NCC retired 2026-05-23), acknowledge it in documentation. Do not create fake inline stubs that pretend the service is healthy.

### 6. Do not resurrect the archived strike-point pipeline (added 2026-05-23)
The pump → mandate → pillar pipeline was MERGED into the Brain. `pump_watcher`, `strike_point_orchestrator`, `execution_loop`, `mandate-generation/`, and `workspaces/execution-pipeline/` are in `archive/strike-point-pre-merge/`. The Brain's `POST /pump` endpoint (`routes.py:795`) with `auto_flow=True` (default) IS the strike-point flow. Do not:
- Re-create `mandate-generation/{input,processed,failed,output}/` in the repo root
- Re-load the unloaded LaunchAgents (`ncl-watcher`, `ncl-orchestrator`)
- Import from `runtime.pump_watcher` or `runtime.strike_point_orchestrator` (they're not on the import path anymore)
- Wire any new code to write or poll those archived directories

If a future change really does need to revive any of this, do it as a separate explicit project — not as a side effect of another fix.

### 7. Do not re-introduce pillar dispatch to NCC/BRS/AAC (added 2026-05-23, tightened 2026-05-24 Wave 13)
NCL is standalone. `PillarType` enum has `NCL` and `NCC` values for historical compatibility; the only dispatch surface that still exists is the `pillar_map` block at `runtime/ncl_brain/brain.py:1020` plus the vestigial `_dispatch_to_ncc()` helper at `brain.py:1091` (its only call site at `brain.py:760` is commented out). Wave 13 P0 made `pillar_map` STRICT — unknown pillar strings (including any future LLM emitting `"pillar": "NCC"`) now log a warning and fall through to `PillarType.NCL` rather than silently routing to a retired pillar. The separate `runtime/dispatch/pillar_router.py` referenced by older drafts of this doc has not existed for a long time (verified 2026-05-24 / Wave 13 via `ls runtime/dispatch/` → "No such file or directory"). Do not rebuild any of this. If multi-target dispatch is ever needed again, that's a fresh feature decision, not a "restoration".

### 8. Do not hardcode the STRIKE_AUTH_TOKEN in dashboard HTML (added 2026-05-24, W6-E)
`dashboard/command-center.html` and `dashboard/review-queue.html` contain the placeholder `__AUTH_TOKEN__` which the `/app` and `/review-queue/dashboard` handlers in `runtime/api/routes.py` substitute with the requester's already-verified Bearer token before serving. The token is NEVER on disk + NEVER in VCS. If you add a new authed dashboard page, follow the same pattern: ship `__AUTH_TOKEN__` in the HTML, run `_verify_strike_token(authorization)` in the handler, then `html.replace("__AUTH_TOKEN__", safe_token)` before returning `HTMLResponse`. Do NOT paste the real token back into the HTML "just for testing" — that puts it back into git history.

---

## Calendar System (added May 21, 2026)

**Backend** (`runtime/calendar/`):
- `lunar.py` — Moon phase engine (Skyfield + Meeus fallback), 8-phase energy mapping, cycle context
- `events.py` — Market events: FOMC 2026, options expiry, quad witching, VIX expiry, futures roll, Finnhub economic calendar
- `local_events.py` — Local events for 7 cities (Edmonton, Calgary, Panama City, San Salvador, Montevideo, Asuncion, Oaxaca). Holidays, Open-Meteo weather alerts, Ticketmaster events, curated JSONL
- `watchlist.py` — Correlated to-do engine pulling from moon energy, predictions, scanners, council, journal, paper trades, portfolio, calendar events
- `calendar_routes.py` — FastAPI router: 12 endpoints under `/calendar/`

**API Endpoints**:
- GET `/calendar/today` — today's moon + events + context
- GET `/calendar/week` — 7-day view with phases + events
- GET `/calendar/month` — 30-day view
- GET `/calendar/moon` — current phase + cycle context
- GET `/calendar/moon/phases` — upcoming major phases
- GET `/calendar/energy` — energy state + phase-based todos
- GET `/calendar/events` — market events with date range + category filter
- POST `/calendar/events` — add custom event
- GET `/calendar/categories` — event category metadata
- GET `/calendar/cities` — available cities list
- GET `/calendar/local/{city_id}` — local events for a city
- POST `/calendar/local/events` — add curated local event
- GET `/calendar/watchlist` — full correlated to-do list

## Watch Queries (updated May 17, 2026)
- **X**: AI automation, algo trading, prediction markets, indie game dev, DUBFORGE, Claude, crypto regime, AI startup (8 queries — all failing due to 402)
- **YouTube**: AI business, crypto trading, indie game dev, AI dev tools, prediction markets, AI music (6 queries)
- **Reddit**: 6 search queries + 55 subreddits across 3 tiers (T1: 10, T2: 16, T3: 29)

---

## Routing Table

| Task Type | Trigger | Output |
|-----------|---------|--------|
| New pump prompt | `NATRIX` message | mandate package |
| Council run | `council` keyword | deliberation log + decision → MemoryStore |
| Research request | `research` keyword | research plan → UNI execution |
| Intelligence scan | auto (Awarebot) | signal report → SignalProcessor |
| Signal processing | auto (SignalProcessor) | routed to memory/context/push/JSONL |
| Memory recall | `recall` keyword | context brief |
| Journal entry | `journal` keyword | JSONL record + optional memory bridge |
| Journal reflection | 10pm ET cron | LLM synthesis → WorkingContext |
| Feedback processing | `feedback` keyword | mandate adjustments |
| Mandate status | `status` keyword | current state table |
