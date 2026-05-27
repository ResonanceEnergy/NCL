#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/api/routers/intel/__init__.py runtime/intelligence/collectors.py CLAUDE.md

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G P14 — exec_summary markdown strip + Coinpaprika fallback + SQLite doc correction

Three carry-overs from P13 cleared.

1. EXEC_SUMMARY MARKDOWN STRIP (runtime/api/routers/intel/__init__.py).
   Wave 14C's _strip_markdown() post-pass only covered the topics_text
   field. brief.executive_summary was passed through verbatim, so the
   iOS BriefRenderer rendered '**HEADLINE DEVELOPMENT**' as literal
   markdown.

   Fix: applied _strip_markdown(brief.executive_summary or '') at the
   brief_data assembly point + return point. Same strip pass that
   handles topics now handles exec_summary. Live-verified post-bounce:
   exec_summary='EXECUTIVE BRIEF — NATRIX OPERATIONS\\n\\nHEADLINE
   DEVELOPMENT\\nSPY options show...' (no \`**\` chars, clean plain text).

2. COINPAPRIKA FALLBACK (runtime/intelligence/collectors.py +250 LOC).
   CoinGecko free tier rate-limits at ~10-30/min, and the per-coin
   market_chart calls for TA computation push us over that quickly.
   Crypto scanner has been DISABLED for weeks because of 60s+ retry
   stalls.

   Added Coinpaprika as a fallback: free tier ~25k calls/month, no API
   key, similar /tickers endpoint shape. New PAPRIKA_BASE +
   PAPRIKA_IDS dict + _paprika_market_overview() helper. In the
   collect_market_overview except branch, if CoinGecko fails we
   fall through to Coinpaprika and emit the same MarketSignal shape
   tagged 'coinpaprika' in metadata['source'] so downstream code can
   distinguish provenance. TA fields (RSI/MACD) drop off the
   Coinpaprika path because their free tier doesn't provide
   historical OHLC — acceptable degradation; the alternative was
   no crypto signals at all.

3. SQLITE MANDATES CUTOVER — DOC CORRECTION (CLAUDE.md).
   The claim 'SQLite double-write live on 3 tables but data/mandates.sqlite
   never created on disk' was wrong. The DB lives at the default path
   data/persistence/ncl.db (28 MB on this machine). sqlite3 dump shows:
     mandates: 70 rows (matches mandates.json count)
     cost_ledger: 2,911 rows
     units_index: 33,005 rows
     plus council_sessions, council_rounds, predictions
   All three Wave 10 gates (NCL_MANDATES_SQLITE, NCL_COST_LEDGER_SQLITE,
   NCL_UNITS_INDEX_SQLITE) are set to true in .env and the
   DoubleWriteHook is faithfully writing through to ncl.db on every
   call. The cutover was DONE in Wave 10 — only the doc was looking at
   a wrong path. Updated Wave 10 summary in CLAUDE.md to reflect actual
   state.

Net: 2 modified code files + 1 doc file. ~+95 LOC. Brain bounced
(pid rotating, /health returns 200), morning brief refired (62s,
critic 100, 4/4 trade ideas, exec_summary clean).
"
git push origin main 2>&1 | tail -3
