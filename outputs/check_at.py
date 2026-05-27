#!/usr/bin/env python3
import json
import subprocess


out = subprocess.run(
    [
        "curl",
        "-sS",
        "-H",
        "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU",
        "http://100.72.223.123:8800/portfolio/auto-trader/dashboard",
    ],
    capture_output=True,
    text=True,
    timeout=10,
)
d = json.loads(out.stdout)
s = d.get("state", {})
print(f"last_loop_tick: {s.get('last_loop_tick_iso')}")
print(
    f"today: eval={s.get('ideas_evaluated_today')} open={s.get('ideas_opened_today')} reject={s.get('ideas_rejected_today')}"
)
