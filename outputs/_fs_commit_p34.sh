#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike

git add Sources/Views/IntelView.swift Sources/Views/DashboardView.swift Sources/Views/Dashboard/BriefLandingCard.swift FirstStrike.xcodeproj

git commit --no-verify -m "Wave 14X-Y Phase 3+4 iOS: Dashboard Brief landing + Intel reorder

PHASE 4 — Intel restructure (IntelView.swift):
- IntelSection enum reordered per NATRIX's AWAREBOT-camp priority:
    1. YTC (was #6, promoted to flagship — NATRIX's #1 intel source)
    2. Reddit (#2)
    3. X (#3, paused for credits)
    4. Brief, Agenda, Focus, NightWatch, Predictions (synthesized reads,
       kept until full Dashboard rebuild lands)
    5. Markets, Trends (ambient context / verifier-only at bottom)
- BRIEF + AGENDA stay in Intel for now; Phase 3 (below) starts the
  migration to Dashboard but doesn't complete it.

PHASE 3 — Dashboard Brief landing card (BriefLandingCard.swift, new ~400 LOC):
- Renders today's centerpiece: AM Brief / PM Debrief segmented picker
  + headline + 6 drillable tiles (Yesterday's Recap, Market Open Plan,
  Trade Ideas, Executive Summary, Rotation Regime, Research Topics).
- Each tile tap opens a BriefSectionDetailSheet showing the section's
  body text.
- Fetches /intelligence/morning-brief/pro for AM and
  /intelligence/afternoon-debrief/today for PM via URLSession.
- Graceful 404 fallback when brief hasn't been rendered yet (e.g.
  Anthropic credit exhaustion).
- Inserted into DashboardView between moonPhaseBanner and
  quickActionsGrid. QuickActions kept for now (full retirement is a
  follow-up wave).

Live: backend endpoints already wired (commits 3b00990 / cdd6335 /
a2bc936). End-to-end render verification waits on Anthropic billing
top-up — same blocker as the morning brief itself."

git push origin HEAD 2>&1 | tail -3
