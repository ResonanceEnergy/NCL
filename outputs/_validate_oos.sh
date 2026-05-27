#!/bin/bash
cd /Users/natrix/dev/NCL
echo "=== AST checks ==="
for f in \
  runtime/portfolio/order_preview.py \
  runtime/portfolio/backtest_harness.py \
  runtime/portfolio/manual_adapter.py \
  runtime/portfolio/quote_source.py \
  runtime/portfolio/streaming_scaffold.py \
  runtime/api/routers/portfolio.py \
  tests/test_portfolio_manager.py
do
  /opt/homebrew/bin/python3 -c "import ast; ast.parse(open('$f').read())" && echo "AST OK: $f" || echo "AST FAIL: $f"
done

echo
echo "=== pytest tests/test_portfolio_manager.py ==="
/opt/homebrew/bin/python3 -m pytest tests/test_portfolio_manager.py -v --tb=short 2>&1 | tail -60
