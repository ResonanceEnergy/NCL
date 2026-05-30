#!/bin/bash
# Final session sanity check — probe every chip endpoint we shipped today.
TOKEN=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
H="Authorization: Bearer $TOKEN"
BASE=http://100.72.223.123:8800

probe() {
    local desc=$1
    local path=$2
    local code=$(curl -s -o /dev/null -w '%{http_code}' -H "$H" "$BASE$path")
    printf "  %-40s %s  %s\n" "$desc" "$code" "$path"
}

echo "=== brain health ==="
probe "health" "/health"
probe "system env"          "/system/env"
probe "system bertopic status" "/system/bertopic/status"
probe "system costs dashboard" "/system/costs/dashboard.json?days=1"

echo "=== Wave 14B chips ==="
probe "spend chip backing"   "/system/costs/dashboard.json?days=1"
probe "Form 4 insider"       "/portfolio/insider/form4?days_back=14"
probe "Earnings calendar"    "/portfolio/earnings/calendar"
probe "Cross-Reference"      "/cross-reference/today"
probe "Macro snapshot"       "/intelligence/macro/today"
probe "Air quality"          "/calendar/air-quality?city_id=edmonton"

echo "=== autonomous loops ==="
LOOPS=$(curl -s -H "$H" "$BASE/autonomous/loops" \
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
loops=d.get("loops",[])
print(f"  {len(loops)} loops total")
btopic=[l["name"] for l in loops if "BERTopic" in l["name"] or "bertopic" in l["name"].lower()]
print(f"  BERTopic loops: {btopic}")')
echo "$LOOPS"
