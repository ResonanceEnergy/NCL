#!/bin/bash
TOK=$(grep '^STRIKE_AUTH_TOKEN=' /Users/natrix/dev/NCL/.env | head -1 | cut -d= -f2- | tr -d '"')
echo "=== refresh working context (90s budget) ==="
curl -sS --max-time 90 -X POST \
  -H "Authorization: Bearer $TOK" \
  http://100.72.223.123:8800/memory/working-context/refresh \
  -o /tmp/wc2.json -w 'http=%{http_code} time=%{time_total}s\n'
echo "--- payload ---"
head -c 400 /tmp/wc2.json
echo
echo
echo "=== bootstrap CLAUDE.md (background, 240s budget) ==="
(nohup curl -sS --max-time 240 -X POST \
  -H "Authorization: Bearer $TOK" \
  http://100.72.223.123:8800/memory/bootstrap-claude-md \
  -o /tmp/cmd2.json -w 'http=%{http_code} time=%{time_total}s\n' \
  > /tmp/cmd2-meta.txt 2>&1 &)
echo "claude-md bootstrap pid=$!"
