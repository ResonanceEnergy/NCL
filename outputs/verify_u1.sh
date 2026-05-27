#!/bin/bash
TOK=$(grep STRIKE_AUTH_TOKEN ~/dev/NCL/.env | cut -d= -f2 | tr -d '"')
BASE=http://100.72.223.123:8800

echo "--- last 5 chains (post-Wave 14U bounce) ---"
tail -5 ~/dev/NCL/data/portfolio/auto_trader/reasoning_chains.jsonl > /tmp/c.jsonl
/opt/homebrew/bin/python3 <<'PYEOF'
import json
for ln in open('/tmp/c.jsonl'):
    try: d = json.loads(ln)
    except: continue
    dec = d.get('governor_decision') or {}
    bucket = dec.get('strategy_bucket', '?') if isinstance(dec, dict) else '?'
    reasons = dec.get('reasons', []) if isinstance(dec, dict) else []
    r0 = (reasons[0] if reasons else '')[:130]
    pc = d.get('policy_check') or {}
    pc_reason = (pc.get('reason') if isinstance(pc, dict) else '') or ''
    print(f"  strat={d.get('strategy','?'):16s} bucket={bucket:14s}")
    if r0: print(f"    gov: {r0}")
    if pc_reason: print(f"    pc:  {pc_reason[:100]}")
PYEOF

echo
echo "--- emergency-stop smoke test (skip_flatten=true so no real positions touched) ---"
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"skip_flatten": true, "reason": "Wave 14U smoke test"}' \
  $BASE/portfolio/auto-trader/emergency-stop | /opt/homebrew/bin/python3 -m json.tool

echo
echo "--- resume after emergency-stop ---"
curl -s -X POST -H "Authorization: Bearer $TOK" $BASE/portfolio/auto-trader/resume | /opt/homebrew/bin/python3 -m json.tool

echo
echo "--- drawdown state (bands should be 5/10/15 now) ---"
cat ~/dev/NCL/data/health/drawdown.json | /opt/homebrew/bin/python3 -m json.tool | head -10

echo
echo "--- friction profiles (intraday multiplier in scanner_data on next open) ---"
TOK=$TOK curl -s -H "Authorization: Bearer $TOK" $BASE/portfolio/auto-trader/friction | /opt/homebrew/bin/python3 -m json.tool | head -15
