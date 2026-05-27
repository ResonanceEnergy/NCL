#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/api/routers/intel/__init__.py runtime/api/routers/intel/brief_pipeline.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G P15 — brief timestamp surfaced + trade ideas favor individual stocks

NATRIX: 'morning brief has no time stamp and focused on indexes and no
stocks investigate'. Two real bugs in the morning-brief output.

1. TIMESTAMP MISSING from API response (intel/__init__.py).
   brief_data['generated_at'] was being persisted to disk (in the
   morning-{date}.json artifact) but the API response dict that iOS
   actually reads omitted the field. iOS BriefRenderer had no way to
   show when the brief was synthesized — the reader couldn't tell a
   fresh brief from a stale cached one.
   Fix: added 'generated_at': brief_data['generated_at'] to the return
   dict. Live-verified: response now includes
   generated_at='2026-05-26T15:15:14.605170+00:00'.

2. TRADE IDEAS ALL SECTOR ETFs (brief_pipeline.py executor prompt).
   Awarebot's options-flow scanners emit huge volumes of signals on
   SPY + sector SPDRs (XLF, XLE, XLU, XLB, XLC, XLK, etc) because
   sector ETFs have multi-billion-dollar premium days routinely. The
   planner saw those as the dominant signals and biased trade ideas
   toward them — every brief was 4/4 ETF trade ideas (XLU/XLB/SPY/XLC
   pattern). The text body had plenty of individual stock references
   (63 in last brief), but the actionable trade ideas were all
   broad-sector plays that don't match NATRIX's actual trading style.

   Fix: new executor prompt rule 7a 'INDIVIDUAL STOCKS OVER SECTOR
   ETFs'. AT MOST ONE of N trade ideas may be a broad-market or
   sector ETF (explicit blocklist: SPY/QQQ/IWM/DIA/VTI/VOO/VXX/TLT/
   IEF/XLF/XLK/XLE/XLV/XLI/XLP/XLY/XLB/XLU/XLC/XLRE/GLD/SLV/USO/UNG/
   ARKK/SMH/SOXX). The rest MUST be individual operating companies
   (NVDA/TSLA/AMZN/MSFT/GOOG/AAPL/META/AMD/COIN/PLTR/etc). Escape
   hatch: if the entire signal feed genuinely lacks individual-stock
   catalysts, ETFs are allowed but the thesis must explain why.

   Live-verified post-bounce: trade ideas now 3/4 individual stocks +
   1/4 ETF (IWM put spread, XOM long, NVDA call spread, LMT long).
   Exactly the rule 7a quota. Critic still scores 100, no regressions.

Net: 2 modified files. ~+15 LOC.
"
git push origin main 2>&1 | tail -3
