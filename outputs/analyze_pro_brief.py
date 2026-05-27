#!/usr/bin/env python3
import json


raw = open("/tmp/pro_brief.json").read()
decoder = json.JSONDecoder()
d, _ = decoder.raw_decode(raw)
print(f"top-level keys: {list(d.keys())}")
print(f"date: {d.get('date')}")
print(f"status: {d.get('status')}")
brief = d.get("brief") or {}
print(f"\nbrief keys: {list(brief.keys()) if isinstance(brief, dict) else type(brief)}")
ti = brief.get("trade_ideas", []) if isinstance(brief, dict) else []
print(f"trade_ideas: {len(ti)}")
for t in ti[:3]:
    print(f"  - {t.get('ticker','?')} {t.get('direction','?')} {t.get('strategy','?')[:40]}")
meta = brief.get("_meta") or d.get("_meta") or {}
print(f"\n_meta keys: {list(meta.keys()) if isinstance(meta, dict) else 'none'}")
print(f"context_packet_len: {meta.get('context_packet_len')}")
print(f"context_packet_has_ladder: {meta.get('context_packet_has_ladder')}")
print(f"context_packet_has_scout: {meta.get('context_packet_has_scout')}")
print(f"context_packet_has_quant: {meta.get('context_packet_has_quant')}")
print(f"context_packet_has_capability_gaps: {meta.get('context_packet_has_capability_gaps')}")
