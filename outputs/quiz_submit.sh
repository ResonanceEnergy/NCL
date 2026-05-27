#!/bin/bash
TOK=$(grep '^STRIKE_AUTH_TOKEN=' /Users/natrix/dev/NCL/.env | head -1 | cut -d= -f2- | tr -d '"')
curl -s -X POST \
  -H "Authorization: Bearer $TOK" \
  -H 'Content-Type: application/json' \
  --data-binary @/Users/natrix/dev/NCL/outputs/quiz_test.json \
  -o /tmp/quiz-resp.json \
  -w 'http=%{http_code} time=%{time_total}s size=%{size_download}\n' \
  http://100.72.223.123:8800/journal/morning-quiz
echo ===
head -c 1500 /tmp/quiz-resp.json
echo
