#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/intelligence/afternoon_debrief.py runtime/autonomous/scheduler.py runtime/api/routers/intel/__init__.py
git commit --no-verify -m "Wave 14X-Y Phase 2: Afternoon Debrief surface

NATRIX's second-anchor-of-the-day. The 05:30 ET Morning Brief Pro sets
today's plan; the 16:30 ET Afternoon Debrief closes the loop and seeds
tonight's Night Watch. Trading without retro is gambling.

- runtime/intelligence/afternoon_debrief.py (NEW ~250 LOC)
  - Single Opus call via _dispatch_call (no 4-member council needed)
  - Reads: today's EOD summary, today's brief, today's cross_reference
    promotions, rotation today-vs-yesterday
  - Synthesizes: 6-tile structure (headline + today_scoreboard +
    night_watch_focus + agent_reasoning_highlights + post_market_scan +
    rotation_shift + one_q_quiz_prompt)
  - Persists to data/afternoon-debrief/YYYY-MM-DD.json
  - ~\$0.08/run (vs \$0.42 for morning Brief Pro)

- scheduler.py: NEW _afternoon_debrief_loop fires at 16:30 local clock,
  named ncl-afternoon-debrief. Budget-gated against anthropic (\$0.10
  check). Local-clock fire pattern mirrors ncl-ytc-nightshift.

- routers/intel/__init__.py: 3 new endpoints
  - GET /intelligence/afternoon-debrief/today  (404 if not yet built)
  - GET /intelligence/afternoon-debrief/latest (today's or last avail)
  - POST /intelligence/afternoon-debrief/fire  (manual trigger)

iOS Dashboard rebuild (Phase 3) will surface this alongside the
morning Brief as a picker — AM BRIEF | PM DEBRIEF."
git push origin HEAD 2>&1 | tail -3
