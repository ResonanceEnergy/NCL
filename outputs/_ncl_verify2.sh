#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== YTC entries in /autonomous/loops (legacy should be gone) ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 8 "$BASE/autonomous/loops" > /tmp/loops.json
/usr/bin/python3 << 'PY'
import json
d = json.load(open('/tmp/loops.json'))
ytc = [l for l in d.get('loops', []) if 'ytc' in l.get('name','').lower() or 'youtube' in l.get('name','').lower()]
print(f"  YTC-related entries: {len(ytc)}")
for l in ytc:
    print(f"    name={l.get('name')!r}  last_run={(l.get('last_run') or 'none')[:19]}  enabled={l.get('enabled','?')}")
PY

echo ""
echo "=== NEW /council/youtube/channels/health (live test) ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 30 "$BASE/council/youtube/channels/health?lookback_days=14" > /tmp/health.json
/usr/bin/python3 << 'PY'
import json
d = json.load(open('/tmp/health.json'))
print(f"  configured={d.get('configured_channel_count')} fresh={d.get('fresh_count')} stale={d.get('stale_count')} silent={d.get('silent_count')}")
print(f"  silent_handles: {d.get('silent_handles')}")
print(f"  stale_handles: {d.get('stale_handles')}")
print()
print("  per-channel detail:")
for c in d.get('channels', []):
    h = c.get('handle') or c.get('name','?') or '?'
    print(f"    {c['status']:6}  {h[:22]:22}  reports={c['report_count']:3}  days_since={c.get('days_since_last_report')}")
PY
