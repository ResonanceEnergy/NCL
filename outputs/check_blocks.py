#!/usr/bin/env python3
import json


d = json.load(open("/tmp/pro_brief_s.json"))
text = d.get("full_brief", "")
print(f"== brief size: {len(text)} chars ==")
blocks = [
    "DAILY CONTEXT",
    "PORTFOLIO",
    "AGENT",
    "ROTATION",
    "GOAT",
    "BRAVO",
    "OPTIONS",
    "CRYPTO",
    "POLYMARKET",
    "PREDICTIONS",
    "YTC",
    "CONTEXT",
    "TODO_7DAY",
]
for b in blocks:
    mark = "X" if b in text else "_"
    print(f"  [{mark}] {b}")

# Show the daily context section
if "DAILY CONTEXT" in text:
    idx = text.find("DAILY CONTEXT")
    snippet = text[idx : idx + 2000]
    print("\n--- SAMPLE ---")
    print(snippet)
