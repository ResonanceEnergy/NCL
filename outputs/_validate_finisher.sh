#!/bin/bash
cd /Users/natrix/dev/NCL
echo "=== AST checks ==="
for f in \
  runtime/portfolio/tax_lot_ledger.py \
  runtime/portfolio/on_chain_journal.py \
  runtime/portfolio/slippage_tracker.py \
  runtime/portfolio/settle_calendar.py \
  runtime/portfolio/mock_adapter.py \
  runtime/api/routers/portfolio.py \
  tests/test_portfolio_manager.py
do
  /opt/homebrew/bin/python3 -c "import ast; ast.parse(open('$f').read())" && echo "AST OK: $f" || echo "AST FAIL: $f"
done

echo
echo "=== pytest tests/test_portfolio_manager.py ==="
/opt/homebrew/bin/python3 -m pytest tests/test_portfolio_manager.py -v --tb=short 2>&1 | tail -60
