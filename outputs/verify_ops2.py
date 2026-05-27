#!/usr/bin/env python3
import json


d = json.load(open("/tmp/ops2.json"))
s = d["snapshot"]
h = s["host"]
b = s["brain"]
t = s["tailscale"]
l = s["llm_calls"]
print("=== PHASE 2 POLISH VERIFIED ===")
print(
    f"host mem: {h['mem_used_gb']} / {h['mem_total_gb']} GB (wired {h['mem_wired_gb']}, free {h['mem_free_gb']})"
)
print(
    f"tailscale: {t['online_count']}/{t['peer_count']} peers · self={t['self_name']} {t['self_addr']}"
)
for p in t.get("peers", [])[:5]:
    mark = "●" if p["online"] else "○"
    relay = "DERP" if p["relayed_via_derp"] else "direct"
    print(f"  {mark} {p['name']:20s} {p['addr']:15s} hs={p['last_handshake_secs']}s {relay}")
print(f"llm calls (60m): {l['call_count']} calls · ${l['total_cost_usd']}")
for m, v in (l.get("by_model") or {}).items():
    print(f"  {m:35s} {v['count']} calls ${v['cost_usd']}")
print()
print(f"scheduler_activity field: {'PRESENT' if 'scheduler_activity' in s else 'MISSING'}")
print(f"  {len(s.get('scheduler_activity', []))} tasks tracked")
for a in s.get("scheduler_activity", [])[:8]:
    print(f"  {a['state']:8s} {a['name']}")
