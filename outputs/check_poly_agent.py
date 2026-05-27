#!/usr/bin/env python3
import json
import subprocess


H = ["-H", "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"]

# Check cache file
import os


cache_dir = "/Users/natrix/dev/NCL/data/intelligence/polymarket"
if os.path.isdir(cache_dir):
    for f in sorted(os.listdir(cache_dir)):
        print(f"  cache file: {f} ({os.path.getsize(os.path.join(cache_dir, f))} bytes)")
else:
    print("NO CACHE DIR")

r = subprocess.run(
    ["curl", "-sS"] + H + ["http://100.72.223.123:8800/portfolio/polymarket-agent/edges?limit=5"],
    capture_output=True,
    text=True,
    timeout=10,
)
d = json.loads(r.stdout)
print(f"\nmarket_cache_count: {d.get('market_cache_count')}")
print(f"edge_count: {d.get('edge_count')}")
for e in d.get("edges", [])[:5]:
    pid = e.get("prediction_title") or "none"
    print(f"  {e.get('edge_pp')}pp {e.get('side')}  {(e.get('market_question') or '')[:60]}")
    print(f"     prediction: {pid[:60]}")
    print(
        f"     market_yes=${e.get('market_yes_price'):.2f}  stated_prob={e.get('prediction_stated_probability')}  days_to_res={e.get('days_to_resolution')}"
    )
