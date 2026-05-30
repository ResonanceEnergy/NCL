#!/bin/bash
echo "=== sleeping 20s for sweep to land more signals..."
sleep 20

echo "=== Reddit signals in last 5 min:"
/opt/homebrew/bin/python3 << 'PY'
import json, time
from datetime import datetime
cutoff = time.time() - 300
n_total = 0
n_rss = 0
n_oauth = 0
subs = set()
recent_sample = None
with open("/Users/natrix/dev/NCL/data/intelligence/agent_signals.jsonl") as f:
    for line in f:
        try: d = json.loads(line)
        except: continue
        if "reddit" not in str(d.get("source", "")).lower(): continue
        ts = d.get("timestamp") or d.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.timestamp() < cutoff: continue
        except: continue
        n_total += 1
        meta = d.get("metadata") or {}
        fp = meta.get("fetch_path", "")
        if fp == "rss": n_rss += 1
        elif fp == "oauth": n_oauth += 1
        for t in d.get("tags", []):
            if t.startswith("r/") or t.startswith("search:"): subs.add(t)
        recent_sample = d
print(f"  total reddit signals last 300s: {n_total}")
print(f"  by path: rss={n_rss}  oauth={n_oauth}  unknown={n_total - n_rss - n_oauth}")
print(f"  distinct subs/searches: {len(subs)}")
print(f"  sample: {sorted(subs)[:10]}")
if recent_sample:
    print(f"  newest url: {recent_sample.get('url', 'NONE')}")
    print(f"  newest title: {(recent_sample.get('content') or '')[:100]}")
PY

echo
echo "=== recent log lines mentioning Reddit RSS:"
tail -200 /Users/natrix/dev/NCL/logs/ncl-brain-stderr.log | grep -E 'Reddit (RSS|OAuth)' | tail -15
