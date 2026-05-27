#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"
echo "=== bootstrap-claude-md (max-time 90s) ==="
curl -sS --max-time 90 -w "\nHTTP %{http_code} %{time_total}s\n" \
  -X POST "http://100.72.223.123:8800/memory/bootstrap-claude-md" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | head -c 800
echo DONE
