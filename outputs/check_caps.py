#!/usr/bin/env python3
import json
import subprocess


out = subprocess.run(
    [
        "curl",
        "-sS",
        "-H",
        "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU",
        "http://100.72.223.123:8800/portfolio/auto-trader/capabilities",
    ],
    capture_output=True,
    text=True,
    timeout=15,
)
d = json.loads(out.stdout)
s = d["summary"]
print(f"available={s['available']} unavailable={s['unavailable']}")
for g in s.get("gaps", []):
    print(f"  GAP {g['name']} ({g['status']}): {g['gap_reason'][:90]}")
