#!/usr/bin/env python3
import json


d = json.load(open("/Users/natrix/dev/NCL/data/health/drawdown.json"))
print(
    f"band={d['band']}  nav=${d['current_nav_cad']:.2f}  dd={d['drawdown_pct']:.2f}%  mult={d['sizing_multiplier']}  computed_at={d['computed_at'][-9:-1]}"
)
