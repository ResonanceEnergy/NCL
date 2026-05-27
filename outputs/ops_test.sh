#!/bin/bash
TOK=$(grep '^STRIKE_AUTH_TOKEN=' /Users/natrix/dev/NCL/.env | head -1 | cut -d= -f2- | tr -d '"')
echo "=== /system/ops/snapshot ==="
curl -s -H "Authorization: Bearer $TOK" http://100.72.223.123:8800/system/ops/snapshot > /tmp/ops.json
/opt/homebrew/bin/python3 <<'PY'
import json
d = json.load(open('/tmp/ops.json'))
s = d.get('snapshot', {})
h = s.get('host', {})
b = s.get('brain', {})
t = s.get('tailscale', {})
l = s.get('llm_calls', {})
sched = s.get('scheduler_activity', [])
print(f"status: {d.get('status')}")
print(f"sample_ms: {s.get('sample_duration_ms')}")
print()
print("HOST")
print(f"  cpu={h.get('cpu_pct')}% load_1m={h.get('load_avg_1m')}")
print(f"  mem={h.get('mem_used_gb')}/{h.get('mem_total_gb')}GB (wired {h.get('mem_wired_gb')})")
print(f"  disk={h.get('disk_free_gb')}/{h.get('disk_total_gb')}GB free")
print(f"  net=↓{h.get('net_rx_mbps')} ↑{h.get('net_tx_mbps')} Mbps")
print(f"  hostname={h.get('hostname')} uptime={h.get('uptime_seconds')}s")
print()
print("BRAIN")
print(f"  pid={b.get('pid')} rss={b.get('rss_mb')}MB cpu={b.get('cpu_pct')}% threads={b.get('threads')}")
print(f"  tasks={b.get('healthy_tasks')}/{b.get('active_tasks')} dead={len(b.get('dead_tasks', []))}")
print(f"  cost=${b.get('today_cost_usd')} ({b.get('today_budget_pct')}% of cap)")
print()
print("TAILSCALE")
print(f"  self={t.get('self_name')} ({t.get('self_addr')})")
print(f"  peers={t.get('online_count')}/{t.get('peer_count')} online")
for p in t.get('peers', [])[:5]:
    print(f"    {'●' if p.get('online') else '○'} {p.get('name'):20s} {p.get('addr')} hs={p.get('last_handshake_secs')}s relay={p.get('relayed_via_derp')}")
print()
print(f"LLM CALLS (60min) — {l.get('call_count')} calls, ${l.get('total_cost_usd')}")
for m, v in (l.get('by_model') or {}).items():
    print(f"  {m:35s} {v['count']} calls ${v['cost_usd']}")
print()
print(f"SCHEDULER ACTIVITY — {len(sched)} ncl-* tasks")
for a in sched[:12]:
    print(f"  {a.get('state'):8s} {a.get('name')}")
PY

echo
echo "=== /system/ops/history?minutes=1 ==="
curl -s -H "Authorization: Bearer $TOK" "http://100.72.223.123:8800/system/ops/history?minutes=1" > /tmp/hist.json
/opt/homebrew/bin/python3 -c "import json; d=json.load(open('/tmp/hist.json')); print(f'count: {d.get(\"count\")} (5s ticks in last minute)')"
