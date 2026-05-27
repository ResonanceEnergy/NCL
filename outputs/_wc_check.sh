#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"
echo "=== /memory/working-context (current state) ==="
curl -sS --max-time 10 -H "Authorization: Bearer $TOKEN" \
  "http://100.72.223.123:8800/memory/working-context" | \
  /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d.get('items', [])
print('items:', len(items))
print('last_assembled_at:', d.get('last_assembled_at'))
print('first 3 items:')
for it in items[:3]:
    print(' -', (it.get('source') or '?'), '|', (it.get('content') or '')[:80])
"
