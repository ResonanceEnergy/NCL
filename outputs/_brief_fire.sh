#!/bin/bash
curl -s --max-time 300 -X POST -H 'Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU' \
  'http://100.72.223.123:8800/intelligence/morning-brief/pro/fire?skip_prep=true' \
  > /tmp/_brief_fire_out.json 2>/tmp/_brief_fire_err.log
echo "exit=$? size=$(wc -c < /tmp/_brief_fire_out.json)" > /tmp/_brief_fire_status.log
