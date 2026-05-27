#!/usr/bin/env python3
import json


with open("/Users/natrix/dev/NCL/data/portfolio/auto_trader/reasoning_chains.jsonl") as f:
    lines = f.readlines()
for ln in lines[-8:]:
    try:
        e = json.loads(ln)
        gov = e.get("governor_decision") or {}
        reasons = gov.get("reasons", ["?"])
        ts = (e.get("ts") or "")[11:19]
        print(f"{ts}  {e.get('ticker'):6s}  approved={gov.get('approved'):5}  {reasons[0][:90]}")
    except Exception as ex:
        print(f"err: {ex}")
