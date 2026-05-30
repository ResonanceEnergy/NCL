#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add docs/AWAREBOT_MANDATE.md docs/CROSS_REFERENCE_MANDATE.md
git commit --no-verify -m "Wave 14X-Y Phase 5: AWAREBOT + Cross-Reference mandate docs

NATRIX's AWAREBOT/TRADERAGENT camp-split now has its mandates:

- docs/AWAREBOT_MANDATE.md (NEW): codifies the intel-camp identity.
  7-factor scoring with new SITUATIONAL_RELEVANCE factor (5%),
  source priority order (YTC #1, Reddit #2, X #3 paused, MARKETS+
  POLYMARKET merged at #5, Trends/News verifier-only), authority
  ceiling at LLM_SINGLE except council-grade YTC.

- docs/CROSS_REFERENCE_MANDATE.md (NEW): codifies the engine that
  bridges AWAREBOT → TRADERAGENT. Three rules (ticker / theme /
  news+trends double-verifier), AWAREBOT-source whitelist, output
  shape, consumers (iOS NOW, TRADERAGENT scout, morning Brief,
  afternoon Debrief).

Original INTEL_MANDATE.md remains as the UI-lane mandate (what the
iOS Intel tab is). AWAREBOT_MANDATE is the agent-camp mandate (what
the AWAREBOT scoring/routing agent does)."
git push origin HEAD 2>&1 | tail -3
