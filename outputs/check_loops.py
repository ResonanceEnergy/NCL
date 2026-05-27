#!/usr/bin/env python3
import json
import subprocess


H = ["-H", "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"]
r = subprocess.run(
    ["curl", "-sS"] + H + ["http://100.72.223.123:8800/autonomous/loops"],
    capture_output=True,
    text=True,
)
d = json.loads(r.stdout)
loops = d.get("loops", [])
print(f"total loops: {len(loops)}")
poly = [l for l in loops if "poly" in (l.get("name") or "").lower()]
print(f"poly tasks: {len(poly)}")
for p in poly:
    print(f"  {p}")
print("\nAll task names:")
for l in loops:
    name = l.get("name", "?")
    state = l.get("state", l.get("active", "?"))
    last_run = (l.get("last_run") or "")[11:19]
    print(f"  {name:40s}  state={state}  last={last_run}")
