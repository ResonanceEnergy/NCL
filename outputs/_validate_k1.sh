#!/bin/bash
cd /Users/natrix/dev/NCL
echo "=== AST ==="
for f in \
  runtime/portfolio/auto_trader/__init__.py \
  runtime/portfolio/auto_trader/state.py \
  runtime/portfolio/auto_trader/policy.py \
  runtime/portfolio/auto_trader/observability.py \
  runtime/api/routers/portfolio.py \
  tests/test_portfolio_manager.py
do
  /opt/homebrew/bin/python3 -c "import ast; ast.parse(open('$f').read())" && echo "OK: $f" || echo "FAIL: $f"
done
echo
echo "=== pytest ==="
/opt/homebrew/bin/python3 -m pytest tests/test_portfolio_manager.py --tb=line -q 2>&1 | tail -5
