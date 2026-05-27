#!/bin/bash
cd /Users/natrix/dev/NCL
echo "=== AST checks ==="
for f in \
  runtime/portfolio/rotation_execution.py \
  runtime/portfolio/tax_compliance.py \
  runtime/portfolio/polymarket_discipline.py \
  runtime/portfolio/telemetry.py \
  runtime/portfolio/hygiene.py \
  runtime/api/routers/portfolio.py \
  runtime/api/routers/intel/brief_pipeline.py \
  tests/test_portfolio_manager.py
do
  /opt/homebrew/bin/python3 -c "import ast; ast.parse(open('$f').read())" && echo "AST OK: $f" || echo "AST FAIL: $f"
done

echo
echo "=== pytest tests/test_portfolio_manager.py ==="
/opt/homebrew/bin/python3 -m pytest tests/test_portfolio_manager.py -v --tb=short 2>&1 | tail -60
