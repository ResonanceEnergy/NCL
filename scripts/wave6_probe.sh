#!/bin/bash
# Quick endpoint probe to verify Wave 5/6 router split landed cleanly.
for path in /system/health/rollup /memory/budget /memory/working-context /intelligence/stats /council/quality /predictions /portfolio/summary /calendar/today; do
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:8800$path)
  echo "$code  $path"
done
