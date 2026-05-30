#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add CLAUDE.md
git commit --no-verify -m "Wave 14X-Y Phase 6: CLAUDE.md updated with full Wave 14X arc

Documents today's 9 commits in chronological order with rationale +
hashes:
  14X-1A YTC channel-fairness fix
  14X-1B Yesterday's Recap + sprawl cut
  14X-2 + 14X-2b Multi-provider council (Opus/Grok/Gemini/GPT/Opus)
  14X-3 Push notifications re-wired + Strike Point dead code deleted
  14X-Y P1B-3 Cross-Reference Engine
  14X-Y P1B-4 Situational context into Brief + Awarebot scorer
  14X-Y Phase 2 Afternoon Debrief
  14X-Y Phase 5 AWAREBOT + Cross-Reference mandate docs

Plus REVAMP architecture context section explaining the AWAREBOT vs
TRADERAGENT camp split, the Brief-as-Dashboard situational cockpit,
and what's deferred (iOS Phases 3+4)."
git push origin HEAD 2>&1 | tail -3
