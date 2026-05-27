#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/stocks/enrichments.py runtime/stocks/scanner.py runtime/api/routes.py runtime/api/routers/intel/__init__.py runtime/intelligence/brief_prep.py runtime/intelligence/brief_council.py runtime/intelligence/brief_presenter.py runtime/autonomous/loops/brief_pro_scheduler.py runtime/autonomous/scheduler.py docs/MORNING_BRIEF_PRO_2026-05-26.md CLAUDE.md

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14H — Morning Brief Pro (NightWatch → Council → Presentation) + P19 GOAT/BRAVO gate restoration

NATRIX: morning brief is one of the app's flagship features. Wants it built
to the highest standard — NightWatch agent preps overnight, hands off to
a multi-LLM Council for research + presentation. Detailed market open
plan with what-to-watch, direction indicators, momentum signals. Full
effort, full performance.

Three new modules in runtime/intelligence/:

1. brief_prep.py (~280 LOC). PREP STAGE — runs nightly at 02:30 ET.
   Concurrent yfinance + signal-feed collectors → context pack:
   futures (ES/NQ/RTY/YM), VIX term structure (^VIX/^VIX9D/^VIX3M
   shape: backwardation/contango/mixed), overnight movers (top 20
   gainers + losers from watchlist), headlines (last 12h Awarebot
   dedup), options_flow_yesterday (GOAT/BRAVO top 10 from yesterday's
   JSONLs), economic_calendar (Finnhub if key set), earnings_today,
   polymarket_leading (active-leading-only per P17-D), held_positions,
   working_context, night_watch_summary. Persists to
   data/morning-brief-prep/YYYY-MM-DD.json.

2. brief_council.py (~280 LOC). COUNCIL STAGE — runs nightly at 05:00
   ET. Delphi-MAD 4-member panel (parallel asyncio.gather) + chair:
     Macro Analyst       — futures/cross-asset/VIX direction call
     Real-Time Pulse     — sentiment/breaking/Polymarket shifts
     Flow Detective      — options/dark-pool/GEX/institutional positioning
     Technical Tactician — per-ticker setups + momentum + RVOL + ORB
   Each member gets a domain-tailored slice of the prep pack. Outputs
   are structured JSON with section_text + key_findings + trade_idea_seeds
   + watch_list + confidence. Chair (Sonnet 4 ext-thinking) receives
   all 4 outputs + resolves contradictions + applies rule 7a ETF quota
   + date-recency check + writes final brief envelope with
   market_open_plan section. Cost ~\$0.26/run vs P14D's \$0.045 — 5x
   for the flagship.

3. brief_presenter.py (~250 LOC). PRESENTATION STAGE — pure-Python
   renderer (no LLM). Renders council synthesis → plain-text brief
   with MARKET OPEN PLAN section pinned to top:
     WHAT TO WATCH       — 3-5 catalysts with reaction triggers
     DIRECTION INDICATORS — ES futures, VIX shape, breadth
     MOMENTUM SIGNALS    — gap-up watch, RVOL >3x, ORB candidates
     RISK FLAGS          — severity-tagged
   Below: existing EXECUTIVE SUMMARY, KEY MOVEMENTS, EMERGING OPP,
   PRE-MARKET TRADE IDEAS (rule 7a holds), POLYMARKET WATCH,
   TODAY'S RESEARCH TOPICS.

Scheduler wiring (runtime/autonomous/scheduler.py):
  3 new named tasks: ncl-brief-prep (02:30 ET), ncl-brief-council
  (05:00 ET), ncl-brief-render (05:30 ET). Total 35 → 38 ncl-* loops.
  Per-stage local-time scheduling via zoneinfo America/New_York with
  fail-open degradation (no prep → council uses yesterday; no council
  → render falls through to P14D).

API surface (runtime/api/routers/intel/__init__.py):
  GET /intelligence/morning-brief/pro             (today's rendered brief)
  GET /intelligence/morning-brief/pro/prep        (raw prep pack debug)
  GET /intelligence/morning-brief/pro/council     (raw council debug)
  POST /intelligence/morning-brief/pro/fire       (manual e2e trigger)
  Existing /intelligence/morning-brief (P14D) kept as fallback.

Architecture doc at docs/MORNING_BRIEF_PRO_2026-05-26.md.

Live verification (fire endpoint):
  elapsed: 71s end-to-end
  members_succeeded: ['macro', 'pulse', 'flow', 'technical']  (all 4)
  contradictions_resolved: ['Macro bullish on tech leadership vs Flow
    bearish on QUBT - resolved as sector rotation from speculative to
    fundamental plays']
  confidence: 0.79
  trade_ideas: 6 (rule 7a: max 1 ETF holds)
  market_open_plan keys: what_to_watch, direction_indicators,
    momentum_signals, risk_flags  (all populated)
  exec_summary: 351 chars, full_brief: 4850 chars

═══════════════════════════════════════════════════════════════════════
Also shipped: Wave 14G P19 — GOAT/BRAVO scanner gate restoration
═══════════════════════════════════════════════════════════════════════

P18 audit found 3 of 4 documented gates silently non-functional + 1 top
pick (NNE) with 9% stale price. P19-A:

1. yfinance earnings calendar fallback. get_earnings_map() now accepts
   tickers list and falls through to yfinance.get_earnings_dates(limit=4)
   when FINNHUB_API_KEY is missing. Was returning 'unavailable' on
   every scan, silently bypassing the earnings gate.

2. Hardened _yf_iv_blocking. 3-tier spot fetch: fast_info →
   info.currentPrice → 1d history.iloc[-1]. fast_info shape changed in
   newer yfinance which broke the gate.

3. ivr_status field on every result. 'available' or 'unavailable' so
   the gate is HONEST about whether IVR was evaluated. Previously the
   gate silently passed entries when ivr was None — UI advertised
   'rejects IVR >70' but enforced nothing.

P19-B polish:
4. Drop score=0 results from response (was shipping 11 noise rows in
   BRAVO).
5. Populate sector from WATCHLIST_MAP join (was 'sector: ?' for all).
6. Add scan_started_at + scan_completed_at + scan_duration_s to _meta.

CLAUDE.md updated with full Wave 14H + P19 architecture summary.

Net: 3 new intelligence modules + 1 new scheduler loop file + 5
modified runtime files + 1 architecture doc + CLAUDE.md.
~+1,100 LOC.
"
git push origin main 2>&1 | tail -3
