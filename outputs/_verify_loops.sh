#!/bin/bash
curl -s -H 'Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU' --max-time 8 http://100.72.223.123:8800/autonomous/loops > /tmp/loops.json
/usr/bin/python3 << 'PY'
import json
d = json.load(open('/tmp/loops.json'))
ls = d.get('loops', [])
xref = [l for l in ls if 'cross' in l.get('name','').lower()]
adb = [l for l in ls if 'afternoon' in l.get('name','').lower()]
print(f"total loops={len(ls)}")
print(f"  cross-ref entries: {len(xref)}")
for l in xref:
    print(f"    name={l.get('name')!r} last_run={l.get('last_run')}")
print(f"  afternoon-debrief entries: {len(adb)}")
for l in adb:
    print(f"    name={l.get('name')!r} last_run={l.get('last_run')}")
PY
