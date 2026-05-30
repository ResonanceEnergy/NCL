#!/bin/bash
TOK='QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU'
BASE='http://100.72.223.123:8800'

echo '=== pre-bounce ==='
launchctl list | grep ncl-brain | head -2
echo ''
echo '=== bouncing ncl-brain ==='
launchctl kickstart -k "gui/$(id -u)/com.resonanceenergy.ncl-brain" 2>&1
sleep 10
echo ''
echo '=== post-bounce ==='
launchctl list | grep ncl-brain | head -2
echo ''
for i in 1 2 3 4 5 6 7 8 9 10; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 -H "Authorization: Bearer $TOK" "$BASE/health" 2>/dev/null)
  echo "  attempt $i: /health = $code"
  if [ "$code" = '200' ]; then break; fi
  sleep 3
done
echo ''
echo '=== YTC entries in /autonomous/loops (legacy should be gone) ==='
curl -s -H "Authorization: Bearer $TOK" --max-time 8 "$BASE/autonomous/loops" | /usr/bin/python3 -c '
import json, sys
d = json.load(sys.stdin)
ytc = [l for l in d.get("loops", []) if "ytc" in l.get("name","").lower() or "youtube" in l.get("name","").lower()]
print(f"  YTC-related entries: {len(ytc)}")
for l in ytc:
    print(f"    name={l.get(\"name\")!r} last_run={l.get(\"last_run\",\"none\")[:19]}")
'
echo ''
echo '=== NEW /council/youtube/channels/health (live test) ==='
curl -s -H "Authorization: Bearer $TOK" --max-time 15 "$BASE/council/youtube/channels/health?lookback_days=14" | /usr/bin/python3 -c '
import json, sys
d = json.load(sys.stdin)
print(f"  configured={d.get(\"configured_channel_count\")} fresh={d.get(\"fresh_count\")} stale={d.get(\"stale_count\")} silent={d.get(\"silent_count\")}")
print(f"  silent_handles: {d.get(\"silent_handles\")}")
print(f"  stale_handles: {d.get(\"stale_handles\")}")
print("")
print("  per-channel detail:")
for c in d.get("channels", []):
    h = c.get("handle") or c.get("name","?")
    print(f"    {c[\"status\"]:6} {h[:20]:20} reports={c[\"report_count\"]:3} last={c.get(\"days_since_last_report\")}d ago")
'
