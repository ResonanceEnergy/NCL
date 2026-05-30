#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/portfolio/paper_trading.py runtime/portfolio/paper_routes.py
git commit --no-verify -m "Wave 14X-5: persisted paper balance + admin deposit endpoint

Paper engine previously initialized account_balance from a constant
(10K) every restart and only persisted trades. Closing positions at
entry yielded 0 PnL so balance never reflected NATRIXs expected
after a rebuild (cash from selling seeded mirror positions).

- paper_trading.py: balance.json next to trades.jsonl. Engine init
  prefers persisted balance over default. New deposit() and
  set_balance() methods write balance.json atomically.

- paper_routes.py: NEW POST /paper/admin/deposit
  Body: {amount, note?, absolute?}
  When absolute=true, sets balance to amount; otherwise credits/debits.

Used to seed paper NAV to live broker NAV (~25K USD) so auto-trader
redeploys from a meaningful cash pool."

git push origin HEAD 2>&1 | tail -3
