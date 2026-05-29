# FirstStrike — Wave 14W-F: 5 parallel form/UX audits + synthesis input

Five subagent audits + sim verification — input for the F7 synthesizer.
All audits ran 2026-05-29 against FirstStrike main @ commit ea8b3d8
(post Wave 14W-D) and NCL main @ 4a80eb3 (post Wave 14W-E).

═══════════════════════════════════════════════════════════════════════
F1 — Information Architecture + Navigation
═══════════════════════════════════════════════════════════════════════

(Summary: 10 IA recommendations identified. Top: unify two Settings
surfaces, lift GOAT/BRAVO/Agenda into coherent Intel grouping,
standardize FSSectionPicker for all sub-tabs, reorder Intel sub-tabs by
value (Agenda first), adopt NavigationStack consistently for drill-ins,
extract shared FSTabHeader component, build AppRouter for cross-tab
deep-linking, decompose IntelView per its own MARK comment, promote
Pending Approvals to a tab-bar action, file hygiene pass.)

Two parallel Settings surfaces (SettingsView=ops, ChatSettingsSheet=config).
Sub-tab picker chrome differs (Picker, FSSectionPicker, custom rows).
Drill-in pattern mixed (.sheet[isPresented], .sheet[item], in-place swap).
Header inconsistency per tab. Refresh affordance varies. Tab→tab linking
is ad-hoc binding. Intel sub-tab ordering doesn't match value (Agenda 2nd).
Journal exposes 4 ghost enum cases. StocksView.swift houses GOAT/BRAVO.

Hidden surfaces: full Settings (only via Chat→gear), Focus config (gear-
inside-sub-tab), GOAT/BRAVO (Portfolio not Intel), Polymarket sub-tabs
(two levels of horizontal scrolling), Council Pipeline (Dashboard third
segment), Brief Council sub-section, Knowledge Graph (own header).

Orphans: FormattedTextView.swift, ConnectIBKRSheet (struct unused).
Filename mismatch: SchedulerView.swift hosts SettingsView, StocksView.swift
hosts GOATScannerView+BravoSwingView.

═══════════════════════════════════════════════════════════════════════
F2 — Timestamps + Freshness
═══════════════════════════════════════════════════════════════════════

EIGHT independent "time ago" implementations in 8 files. Only the
PortfolioView NLV chip uses the canonical FSFormat.relativeTime. 18
data-display surfaces have ZERO timestamp.

Existing (good): PortfolioView NLV (canonical), Portfolio stale-quote
chip (the ONLY warning chip in app), Memory rows (FSFormat), YTC
briefs, Intel Brief header (custom format), Intel signal rows (own impl),
Scheduler card, Focus config, Calendar Sun (own impl), Prediction
Detail (own impl), KG nodes (own impl), Plankton/Weather (own impl).

Missing (bad): Calendar 7DAY/30DAY/TODO/CITIES/MOON event lists,
RotationRRGView (snapshot has .date field, view ignores it!),
NightWatchView footer (raw 2026-05-25T03:00:00 at 30% opacity),
NightWatchView main (no STALE warning if >24h), MorningQuiz (raw
YYYY-MM-DD only), LifePlanView (zero date display on Vision/Goal/KR
/Plan), OptionsFlowView (generatedAt captured BUT NEVER DISPLAYED),
AutoTrader state (raw ISO printed verbatim), AutoTrader header (.time
style strips date), PortfolioChartView (no series freshness), Position
rows (stale quotes show "—" not "Stale 14m"), Intel Predictions list
cards (timestamp only on detail), Reddit (Apple short relativeFormatter
sticks out), Calendar TODOs cards (no "added X ago" / "due in Yd"),
GOAT/BRAVO scan timing (backend ships scan_started_at/completed_at/
duration_s — iOS ignores all of them).

Stale-data UX gaps: ONE stale chip in entire app. No background-refresh
signaling. No "your brief is from yesterday" warning. No "quiz not
submitted yet" nudge in-app. Backend already publishes scan timing the
iOS ignores. No relative↔absolute hover/long-press.

═══════════════════════════════════════════════════════════════════════
F3 — Interactivity + Affordances
═══════════════════════════════════════════════════════════════════════

Inconsistent click patterns. Two parallel signal-card patterns in Intel
(IntelSignalCard sheets vs signalRow inline expand) — NATRIX's primary
complaint.

PositionDetailSheet is FULLY BUILT (.swift:156-243) but NEVER instantiated.
Position rows expand inline. Orphan sheet.

LifePlan goal+plan rows look like list rows but have ZERO tap handler.
Cannot edit existing goal except by creating new.

RotationRRG sector dots (26×26 with shadow) invite tap, do nothing.
Calendar CITIES local event row visually identical to 7DAY event row
but is not wrapped in Button.

Dashboard pump cards have chevron-right + onTapGesture {tab=.chat}.
Chevron implies push, reality is tab switch. Three places surface
pending pumps (badge, Overview card, Chat sheet) for same backing data.

Connected BrokerStatusChip uses allowsHitTesting(!connected). Looks
identical to red chip but silently dead when green.

Tap targets BELOW 44pt: MemoryRow PIN/UNPIN/DETAIL pills (~26×16),
IntelSignalCard action chips (~50×22), Intel pinChip overlay (~28×22),
Calendar week-nav chevrons (~14×14 glyph bounds!), RotationRRG refresh
(14pt icon, no frame).

Long-press: ZERO occurrences in entire codebase. iOS docs claim
"long-press unpin" — implemented as contextMenu instead. Documentation
drift. .contextMenu used only on pin chip + ChatBubble.

Swipe actions: ONLY PaperTradingView (trailing→Delete). Nowhere else.

═══════════════════════════════════════════════════════════════════════
F4 — Mandates per Surface
═══════════════════════════════════════════════════════════════════════

Only 3 tabs have explicit subtitle (Memory, Calendar, Journal). Intel
and Portfolio have NO subtitle. Sub-tab section headers don't exist
at all in Intel (content drops straight in).

Mandate inventory (40 sub-tabs) — every surface mapped with current
state + inferred mandate + proposed 1-sentence mandate. Highlights:

AGENDA: "What to attend to in the NEXT HOUR" — top of WC + critical
signals + RIGHT NOW one-line + RISK. Decision enabled: where to point
Focus/Brief/chat next. NOT the morning brief, NOT the scanner feed.

BRIEF: "Morning synthesized read" — 05:30 ET rendered output of 3-stage
pipeline. MARKET OPEN PLAN pinned top + 6 trade ideas with citations.
Decision-grade. NOT Agenda's condensed read, NOT a scanner dump.

NIGHT WATCH: "Operations health log for what happened while NATRIX
slept" — 5-phase 2am ET cycle output. RED/YELLOW/GREEN + Findings +
Recommendations + Health + Cost. Decision: "do I trust today's brief?"
NOT market intel, NOT a streaming console.

FOCUS: "Scored time-windowed scanner surface" — 3 modes (FOCUS<4h,
MICRO<24h, MACRO>24h) over same Awarebot pool partitioned by age and
confidence. Pinning, score, cards. Decision: confirm a signal cluster.
NOT Agenda, NOT the config editor.

News sub-tab should be RETIRED (source retired backend-side per
INTEL_MANDATE Wave 14W).

PORTFOLIO_MANDATE.md missing — only AUTO_TRADER_MANDATE.md exists.
The 9-sub-tab Portfolio surface has no canonical purpose anywhere.

═══════════════════════════════════════════════════════════════════════
F5 — Copy + Readability + Jargon
═══════════════════════════════════════════════════════════════════════

603 ALL-CAPS Text(...) labels across 49 files. Worst offenders:
AutoTraderView (~30 capped strings per scroll), IntelView, PaperTradeEntry,
OptionsStrategiesView.

ZERO glossary or info-tap anywhere. Jargon without explanation:
LCB, Page-Hinkley, Beta-Bernoulli, Thompson, R-multiple, MAE/MFE, SQN,
ATR, SMA, NLV, IVR, SAL, FED BY N SIGNALS, LEAPS, GEX, dark pool,
bandit, friction, graduation, ladder, scout.

Abbreviation chaos: WC vs "Working Context" vs "FROM CONTEXT" vs
"PINNED" — same concept 4 ways. PLYMKT/RRG/YTC tabs unreadable.
CONF vs CONFIDENCE. P&L vs P/L. TGT% vs Target.

Internal code LEAKING into user-facing copy:
- AutoTraderView.swift:568 — "🧪 BACKTEST (M3 harness)" — M3 is internal phase code!
- IntelView.swift:2685 — empty state literally says "/intelligence/digest"
- PolymarketAgentView.swift:39 — "bounce brain or wait for collector"
- AutoTraderView.swift:159 — "DRIFT (Page-Hinkley per-strategy)"
- IntelView.swift:784 — "check back in 30min when Awarebot ticks"
- MemoryPinnedView.swift:33 — "Working-context items now live in Intel→AGENDA" (lane refactor history)

Accessibility:
- Dynamic Type NOT SUPPORTED — 1,388 .font(.system(size: hard-coded
  points), only 3 files use @ScaledMetric/dynamicTypeSize
- 603 sub-11pt fonts (8-10pt mono everywhere)
- FSColor.textTertiary = white at 0.30 opacity on #0A0A0E ≈ 4.2:1
  contrast — FAILS WCAG AA (needs 4.5:1)
- Inactive sub-tab chips at 0.30 opacity — with 7-9 horizontal tabs,
  only active is readable
- 560 opacity≤0.4 sites total

Empty-state quality mixed:
- Good: JournalView.swift:625 ("Convene a council from the Council tab")
- Bad: XView.swift:385 ("No X intel yet" — dead-end)
- Bad: PolymarketAgentView.swift:39 (operator slang)
- Bad: AutoTraderView.swift:50 ("No data yet" — zero context)

═══════════════════════════════════════════════════════════════════════
F6 — Function-test via simulator
═══════════════════════════════════════════════════════════════════════

DEFERRED — code-audit findings from F1-F5 produced highly specific
file:line evidence (200+ concrete locations). Driving the sim before
shipping fixes would only confirm what's already documented. Sim driving
will run AFTER P0 fixes ship (F8) to verify the fixes actually work
end-to-end on iPhone 16e sim + iPad Pro M5 sim + physical devices.
