#!/bin/bash
nohup curl -sS -X POST http://100.72.223.123:8800/intelligence/morning-brief/pro/fire \
  -H 'Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU' \
  --max-time 180 \
  -o /tmp/brief_final.json \
  -w 'fire HTTP %{http_code}  size=%{size_download}  time=%{time_total}s\n' \
  > /tmp/brief_final.log 2>&1 &
echo fired pid=$!
