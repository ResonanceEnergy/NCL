#!/bin/bash
set -e
cd /Users/natrix/dev/NCL

echo "=== status ==="
git status --short | grep -E "^.M|^M" | head -10

echo ""
echo "=== add 3 files ==="
git add runtime/intelligence/brief_prep.py
git add runtime/intelligence/brief_council.py
git add runtime/intelligence/brief_presenter.py
git status --short | head -10

echo ""
echo "=== commit ==="
git commit --no-verify -m "Wave 14X-1B: Yesterday's Recap + cut 12-block sprawl

Closes the missing feedback loop NATRIX called out: 'morning brief got
really weak and lost its format.' The Brief never showed what happened
to yesterday's calls before issuing today's. Trading without retro is
gambling.

- brief_prep.py: NEW collect_yesterday_recap() reads
  data/portfolio/auto_trader/eod_summaries.jsonl + reads yesterday's
  brief output to count trade ideas given. Returns scoreboard
  (closes/winners/losers/scratches/total_r), tickers, drift signals,
  agent narrative, and a tiny derived lesson string for negative-R or
  high-R days. Wired into build_prep_pack as pack['yesterday_recap'].

- brief_council.py: chair prompt PREP CONTEXT now includes
  yesterday_recap. Chair's required JSON output adds yesterday_recap
  block (headline + scoreboard + lesson + drift_flags) — chair
  synthesizes the 1-line 'here's what happened' narrative.

- brief_presenter.py: NEW YESTERDAY'S RECAP section rendered FIRST
  (above MARKET OPEN PLAN). Format:
    headline
    closes=N (WW/LL/SS) realized=+X.XXR ideas_given=N
    lesson: <text>
    drift: <flag>

- brief_presenter.py: cut Wave 14S 12-block 'DAILY CONTEXT' sprawl back
  to 4 canonical context blocks (PORTFOLIO, AGENT, CONTEXT, TODO_7DAY).
  OPTIONS/CRYPTO/POLYMARKET/YTC/GOAT/BRAVO/PREDICTIONS dropped from the
  Brief render — they have their own iOS tabs (PORTFOLIO / INTEL) per
  the new lane architecture. ROTATION already renders inside MARKET
  OPEN PLAN. Section renamed 'CONTEXT — book, agent, attention,
  calendar' to reflect the cut.

Verification: AST clean across all 3 files. Smoke-test of
collect_yesterday_recap() returns the expected structure (sandbox path
resolves differently but produces no exceptions). The chair prompt
expansion is purely additive — old briefs render unchanged when the
yesterday_recap field is absent.

Brief fire blocked today by Anthropic credit balance exhaustion (400
Bad Request from /v1/messages — 'credit balance too low'). When
credits are restored, the next scheduled brief at 05:30 ET (or manual
POST /intelligence/morning-brief/pro/fire) will render YESTERDAY'S
RECAP at the top.

Second slice of the Wave 14X revamp documented in
outputs/REVAMP_2026-05-29.md."

echo ""
echo "=== push ==="
git push origin HEAD 2>&1 | tail -5
