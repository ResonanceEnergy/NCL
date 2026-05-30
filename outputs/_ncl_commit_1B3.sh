#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/cross_reference/__init__.py runtime/autonomous/scheduler.py
git commit --no-verify -m "Wave 14X-Y Phase 1B-3: cross-reference promotion engine

The piece that connects the new AWAREBOT/TRADERAGENT camp split. Scans
the intel signal stream for convergences and promotes candidates so the
trader can evaluate them without drowning in the loose AWAREBOT pool.

Three rules (any one fires):
  1. Ticker convergence: same ticker in >=2 distinct AWAREBOT sources
     within 4h
  2. Theme convergence: shared keyword cluster across >=3 distinct
     sources within 24h (5 themes: rate_policy, ai_capex, energy_supply,
     crypto_macro, geopolitical)
  3. News+Trends double-verifier: ticker hit in BOTH news AND
     google_trends — NATRIX's 'press + search confirmation' rule

- runtime/cross_reference/__init__.py (~330 LOC)
  - PromotedCandidate dataclass
  - 3 rule evaluators
  - Ticker extraction with stoplist
  - Dedup by (ticker, day) so same hot ticker doesn't promote hourly
  - Writes data/cross_reference/promotions.jsonl
- runtime/autonomous/scheduler.py
  - NEW _cross_reference_loop (300s cadence, named ncl-cross-reference)
  - Initial 60s delay, asyncio.to_thread for pure-Python scan

Pure pull-from-disk module, no LLM cost. Ready for TRADERAGENT to
consume via intel_request('awarebot.promoted_candidate', ...) in the
next phase."
git push origin HEAD 2>&1 | tail -3
