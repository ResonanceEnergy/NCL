#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"
nohup curl -sS --max-time 600 \
  -X POST "http://100.72.223.123:8800/memory/bootstrap-claude-md" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' \
  > /Users/natrix/dev/NCL/outputs/_bootstrap_bg.json 2>&1 &
echo "bg pid: $!"
disown
