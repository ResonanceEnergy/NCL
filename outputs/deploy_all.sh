#!/bin/bash
set -euo pipefail
cd /Users/natrix/Projects/FirstStrike
SIM_APP=$(find build/SimDerived/Build/Products -type d -name 'FirstStrike.app' | head -1)
DEV_APP=$(find build/DevDerived/Build/Products -type d -name 'FirstStrike.app' | head -1)
BUNDLE=com.resonanceenergy.firststrike

echo "=== iPhone 16e sim ==="
xcrun simctl install 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 "$SIM_APP"
xcrun simctl launch 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 $BUNDLE

echo "=== iPad Pro M5 sim ==="
xcrun simctl install CE298CEE-1125-4090-8847-116691BE501B "$SIM_APP"
xcrun simctl launch CE298CEE-1125-4090-8847-116691BE501B $BUNDLE

echo "=== Nathan iPhone ==="
xcrun devicectl device install app --device 00008130-000675C822A2001C "$DEV_APP" 2>&1 | grep -E 'App installed|installationURL' | head -2

echo "=== GRIP AND RIPP HDD iPad ==="
xcrun devicectl device install app --device 00008027-001664301E07002E "$DEV_APP" 2>&1 | grep -E 'App installed|installationURL' | head -2

echo
echo "=== refresh working context ==="
TOK=$(grep '^STRIKE_AUTH_TOKEN=' /Users/natrix/dev/NCL/.env | head -1 | cut -d= -f2- | tr -d '"')
curl -s --max-time 30 -X POST \
  -H "Authorization: Bearer $TOK" \
  http://100.72.223.123:8800/memory/working-context/refresh \
  -o /tmp/wc.json -w 'http=%{http_code} time=%{time_total}s\n'

echo
echo "=== bootstrap CLAUDE.md (background, takes 2-3 min) ==="
(nohup curl -s --max-time 240 -X POST \
  -H "Authorization: Bearer $TOK" \
  http://100.72.223.123:8800/memory/bootstrap-claude-md \
  -o /tmp/cmd.json -w 'http=%{http_code} time=%{time_total}s\n' \
  > /tmp/cmd-meta.txt 2>&1 &)
echo "claude-md bootstrap backgrounded"
