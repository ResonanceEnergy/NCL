#!/bin/bash
# Wave 14BO — fire Morning Brief Pro with A/B flag on and capture cost delta.
set -e
TOKEN=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
H="Authorization: Bearer $TOKEN"

echo "=== before fire ==="
curl -s -H "$H" 'http://100.72.223.123:8800/system/costs/dashboard.json?days=1' \
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
print("today total:", d.get("totals", {}).get("today"))
for k,v in d.get("by_source_model", {}).items():
    print(f"  {k}: ${v:.4f}")'

echo
echo "=== firing brief (~90s) ==="
curl -s --max-time 240 -X POST -H "$H" -H 'Content-Type: application/json' \
    http://100.72.223.123:8800/intelligence/morning-brief/pro/fire \
    -o /tmp/brief_14BO.json
echo "wrote /tmp/brief_14BO.json size=$(stat -f%z /tmp/brief_14BO.json)"

echo
echo "=== council models used ==="
python3 -c 'import json
d=json.load(open("/tmp/brief_14BO.json"))
print("status:", d.get("status"))
syn = d.get("synthesis", {})
meta = syn.get("_meta", {})
print("council_models:", meta.get("council_models"))
print("local_ab_enabled:", meta.get("local_ab_enabled"))
print("members_succeeded:", meta.get("members_succeeded"))'

echo
echo "=== after fire ==="
curl -s -H "$H" 'http://100.72.223.123:8800/system/costs/dashboard.json?days=1' \
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
print("today total:", d.get("totals", {}).get("today"))
for k,v in d.get("by_source_model", {}).items():
    print(f"  {k}: ${v:.4f}")'
