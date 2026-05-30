#!/usr/bin/env python3
"""Honest Reddit audit. Did Reddit ever produce real signals? What URLs?"""

import collections
import glob
import json
import os


paths = [
    os.path.expanduser("~/dev/NCL/data/intelligence/agent_signals.jsonl"),
    *glob.glob(os.path.expanduser("~/dev/NCL/data/intelligence/archive/agent_signals*.jsonl")),
    *glob.glob(os.path.expanduser("~/dev/NCL/data/awarebot/signals*.jsonl")),
]
paths = [p for p in paths if os.path.exists(p)]
print(f"Scanning {len(paths)} signal files:")
for p in paths:
    sz = os.path.getsize(p) / 1024
    print(f"  {p}  ({sz:.0f}KB)")
print()

by_day = collections.Counter()
sample_per_day = {}
total_reddit = 0
total_all = 0
url_samples = []

for path in paths:
    with open(path) as f:
        for line in f:
            total_all += 1
            try:
                d = json.loads(line)
            except Exception:
                continue
            src = str(d.get("source", "")).lower()
            url = str(d.get("url", ""))
            is_reddit = "reddit" in src or "reddit.com" in url
            if not is_reddit:
                continue
            total_reddit += 1
            ts = d.get("timestamp") or d.get("created_at") or d.get("discovered_at") or ""
            day = ts[:10] if ts else "unknown"
            by_day[day] += 1
            if day not in sample_per_day:
                sample_per_day[day] = d
            if url and len(url_samples) < 8 and "reddit.com" in url:
                url_samples.append((day, url[:140]))

print("=== TOTALS")
print(f"  total signals across all files: {total_all:,}")
print(f"  reddit signals: {total_reddit:,}")
print()
print("=== REDDIT signals by day (last 21):")
for day, cnt in sorted(by_day.items())[-21:]:
    print(f"  {day}: {cnt}")
print()
print("=== REAL Reddit URLs found (proves not fabricated):")
for day, url in url_samples:
    print(f"  [{day}] {url}")
print()
last_day = max((d for d in by_day if d != "unknown"), default=None)
if last_day:
    s = sample_per_day[last_day]
    print(f"=== LAST DAY WITH REDDIT DATA: {last_day}")
    print(f"  source: {s.get('source')}")
    print(f"  url:    {s.get('url', 'NONE')}")
    print(f"  title:  {(s.get('title') or s.get('text') or s.get('content') or 'NONE')[:200]}")
    print(f"  meta:   {s.get('metadata', {})}")
