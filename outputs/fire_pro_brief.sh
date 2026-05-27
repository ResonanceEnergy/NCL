#!/bin/bash
TOKEN=$(grep STRIKE_AUTH_TOKEN /Users/natrix/dev/NCL/.env | awk -F= '{print $2}' | tr -d '"')
echo "Firing Morning Brief Pro (NightWatch -> Council -> Render)..."
START=$(date +%s)
curl -s -m 220 -X POST -H "Authorization: Bearer $TOKEN" \
    http://100.72.223.123:8800/intelligence/morning-brief/pro/fire > /tmp/pro_brief.json 2>&1
END=$(date +%s)
echo "completed in $((END - START))s"
wc -c /tmp/pro_brief.json
touch /tmp/pro_brief.done
