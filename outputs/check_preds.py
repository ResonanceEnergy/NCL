#!/usr/bin/env python3
import json
import subprocess


H = ["-H", "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"]

# List
r = subprocess.run(
    ["curl", "-sS"] + H + ["http://100.72.223.123:8800/predictions?limit=5&sort=confidence"],
    capture_output=True,
    text=True,
    timeout=10,
)
d = json.loads(r.stdout)
print("=== LIST sort=confidence ===")
for p in d.get("predictions", []):
    print(
        f"  [{p.get('confidence',0):.2f}] q={p.get('quality_score',0):.2f} "
        f"win={p.get('forecast_window_days')}d  '{p.get('title')}'"
    )
print(f"  meta: {d.get('_meta')}\n")

# Detail (use first id)
if d.get("predictions"):
    pid = d["predictions"][0]["prediction_id"]
    r2 = subprocess.run(
        ["curl", "-sS"] + H + [f"http://100.72.223.123:8800/prediction/{pid}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    d2 = json.loads(r2.stdout)
    print(f"=== DETAIL {pid[:8]} ===")
    print(f"  status: {d2.get('status')}")
    print(f"  top-level keys: {list(d2.keys())}")
    sigs = d2.get("signals", [])
    print(f"  signals (top-level): {len(sigs)} hydrated")
    for s in sigs[:3]:
        print(f"    - {s.get('source')[:30]:30s} {s.get('title','')[:50]}")
    pred = d2.get("prediction", {})
    print(f"  prediction.title: {pred.get('title')}")
    print(f"  prediction.expires_at_iso: {pred.get('expires_at_iso')}")
