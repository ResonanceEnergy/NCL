#!/bin/bash
TOKEN=$(grep STRIKE_AUTH_TOKEN /Users/natrix/dev/NCL/.env | awk -F= '{print $2}' | tr -d '"')
echo "Firing morning brief PRO..."
START=$(date +%s)
curl -s -m 300 -X POST -H "Authorization: Bearer $TOKEN" \
    http://100.72.223.123:8800/intelligence/morning-brief/pro/fire > /tmp/brief_pro.json 2>&1
END=$(date +%s)
echo "elapsed: $((END - START))s"
wc -c /tmp/brief_pro.json
echo "--- top-level keys ---"
/opt/homebrew/bin/python3 -c "
import json
try:
    d = json.load(open('/tmp/brief_pro.json'))
    print(list(d.keys()))
    if 'detail' in d:
        print('ERROR:', d['detail'][:200])
    else:
        print('exec_summary len:', len(d.get('executive_summary','')))
        print('full_brief len:', len(d.get('full_brief','')))
        print('trade_ideas count:', len(d.get('trade_ideas') or []))
        mop = d.get('market_open_plan') or {}
        print('market_open_plan keys:', list(mop.keys()))
        cm = d.get('council_meta') or {}
        print('council_meta:', cm)
except Exception as e:
    print('parse failed:', e)
    print(open('/tmp/brief_pro.json').read()[:500])
"
