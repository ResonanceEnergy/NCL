#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"
echo "=== /system/health/rollup (full keys) ==="
curl -sS --max-time 15 -H "Authorization: Bearer $TOKEN" \
  http://100.72.223.123:8800/system/health/rollup | \
  /opt/homebrew/bin/python3 -m json.tool 2>&1 | head -50
