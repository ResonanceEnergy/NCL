#!/usr/bin/env python3
import json


raw = open("/tmp/brief.json").read()
# Parse first JSON object using raw_decode
decoder = json.JSONDecoder()
d, end_idx = decoder.raw_decode(raw)
print(f"=== First JSON ({end_idx} chars) ===")
print(f"keys: {list(d.keys())}")
pm = d.get("pipeline_meta", {})
print("\npipeline_meta:")
for k, v in pm.items():
    print(f"  {k}: {v}")

ti = d.get("trade_ideas", [])
print(f"\ntrade_ideas: {len(ti)}")
for i, t in enumerate(ti[:3]):
    print(f"  [{i}] {t.get('ticker','?')} {t.get('direction','?')} {t.get('strategy','?')}")
    print(f"      thesis: {(t.get('thesis') or '')[:120]}")

# parse second JSON if there's more
if end_idx < len(raw):
    remaining = raw[end_idx:].strip()
    if remaining:
        try:
            d2, end2 = decoder.raw_decode(remaining)
            print(f"\n=== Second JSON ({end2} chars) ===")
            print(f"keys: {list(d2.keys())}")
        except Exception as e:
            print(f"\nSecond JSON parse failed: {e}")
            print(remaining[:300])
