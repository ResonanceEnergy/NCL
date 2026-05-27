#!/bin/bash
TOKEN=$(grep STRIKE_AUTH_TOKEN /Users/natrix/dev/NCL/.env | awk -F= '{print $2}' | tr -d '"')
echo "token len: ${#TOKEN}"
curl -s -m 10 -H "Authorization: Bearer $TOKEN" http://100.72.223.123:8800/system/ops/snapshot > /tmp/ops3.json
wc -c /tmp/ops3.json
head -c 200 /tmp/ops3.json
echo ""
/opt/homebrew/bin/python3 << 'PY'
import json
d = json.load(open('/tmp/ops3.json'))
s = d['snapshot']
t = s['tailscale']
print(f"PEERS: {t['online_count']}/{t['peer_count']}  self={t.get('self_name')} {t.get('self_addr')}")
for p in t.get('peers', [])[:5]:
    mark = '●' if p['online'] else '○'
    relay = 'DERP' if p['relayed_via_derp'] else 'direct'
    hs = p['last_handshake_secs']
    hs_str = 'never' if hs == -1 else f"{hs}s"
    print(f"  {mark} {p['name']:25s} {p['addr']:15s} hs={hs_str} {relay}")
PY
