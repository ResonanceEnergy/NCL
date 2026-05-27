#!/bin/bash
set -uo pipefail
TOK=$(grep '^STRIKE_AUTH_TOKEN=' /Users/natrix/dev/NCL/.env | head -1 | cut -d= -f2- | tr -d '"')
BASE=http://100.72.223.123:8800

echo "=== STATE BEFORE ==="
echo "-- quiz file pre --"
ls -la /Users/natrix/dev/NCL/data/journal/morning-quiz/2026-05-25.json 2>&1
cat /Users/natrix/dev/NCL/data/journal/morning-quiz/2026-05-25.json 2>&1 | head -30
echo "-- journal.jsonl tail 3 pre --"
tail -3 /Users/natrix/dev/NCL/data/journal/journal.jsonl

echo
echo "=== POST quiz ==="
cat > /tmp/quiz_trace.json <<'JSON'
{"mood_score":7,"mood_word":"focused","top_priority":"DEBUG: trace test 14E-fix","supporting_tasks":["a","b"],"market_posture":"neutral","research_question":"Why is propagation tracking not persisting?","gratitude":"-","yesterday_lesson":"-","notes":"trace","wisdom_id_shown":"stoic-006"}
JSON

curl -sS -X POST \
  -H "Authorization: Bearer $TOK" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/quiz_trace.json \
  -o /tmp/quiz_trace_resp.json \
  -w 'http=%{http_code} time=%{time_total}s\n' \
  $BASE/journal/morning-quiz
echo "-- response payload --"
cat /tmp/quiz_trace_resp.json
echo

echo "=== STATE AFTER ==="
echo "-- quiz file post --"
cat /Users/natrix/dev/NCL/data/journal/morning-quiz/2026-05-25.json 2>&1 | head -30
echo "-- journal.jsonl tail 2 post --"
tail -2 /Users/natrix/dev/NCL/data/journal/journal.jsonl

echo
echo "=== Brain log MORNING-QUIZ entries ==="
grep -E 'MORNING-QUIZ|morning_quiz' /Users/natrix/dev/NCL/logs/ncl-brain-stderr.log | tail -5
