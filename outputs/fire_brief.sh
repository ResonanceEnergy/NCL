#!/bin/bash
TOKEN=$(grep STRIKE_AUTH_TOKEN /Users/natrix/dev/NCL/.env | awk -F= '{print $2}' | tr -d '"')
echo "Firing morning brief..."
START=$(date +%s)
curl -s -m 180 -X POST -H "Authorization: Bearer $TOKEN" \
    http://100.72.223.123:8800/intelligence/morning-brief > /tmp/brief.json 2>&1
END=$(date +%s)
echo "completed in $((END - START))s"
wc -c /tmp/brief.json
/opt/homebrew/bin/python3 << 'PY'
import json
try:
    d = json.load(open('/tmp/brief.json'))
except Exception as e:
    print(f"JSON parse fail: {e}")
    print(open('/tmp/brief.json').read()[:500])
    exit(1)
text = d.get('text') or d.get('brief') or ''
meta = d.get('pipeline_meta') or {}
print(f"--- PIPELINE META ---")
print(f"plan_mode: {meta.get('plan_mode')}")
print(f"trade_idea_target: {meta.get('trade_idea_target')}")
print(f"trade_ideas_emitted: {meta.get('trade_ideas_emitted')}")
print(f"critic_score: {meta.get('critic_score')}")
print(f"critic_reasons: {meta.get('critic_reasons')}")
print(f"--- BRIEF SUMMARY ---")
print(f"length: {len(text)} chars")
# count markdown leaks + stubs
import re
md_leaks = len(re.findall(r'^\*\*|^#', text, re.MULTILINE))
stubs = text.lower().count('signals quiet') + text.lower().count('no signals')
print(f"markdown leaks: {md_leaks}")
print(f"stub phrases: {stubs}")
print(f"--- FIRST 400 CHARS ---")
print(text[:400])
PY
