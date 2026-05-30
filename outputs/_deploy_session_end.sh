#!/bin/bash
set +e
APP_SIM=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphonesimulator/FirstStrike.app
APP_DEV=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphoneos/FirstStrike.app

echo "=== boot sims if cold"
/usr/bin/xcrun simctl boot 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 2>/dev/null
/usr/bin/xcrun simctl boot CE298CEE-1125-4090-8847-116691BE501B 2>/dev/null

echo "=== install iPhone 16e Sim"
/usr/bin/xcrun simctl install 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 "$APP_SIM" && echo "  ok"

echo "=== install iPad Pro M5 Sim"
/usr/bin/xcrun simctl install CE298CEE-1125-4090-8847-116691BE501B "$APP_SIM" && echo "  ok"

echo "=== install physical iPhone"
/usr/bin/xcrun devicectl device install app --device 00008130-000675C822A2001C "$APP_DEV" 2>&1 | tail -2

echo "=== install physical iPad"
/usr/bin/xcrun devicectl device install app --device 00008027-001664301E07002E "$APP_DEV" 2>&1 | tail -2

echo "=== bounce brain"
/bin/launchctl kickstart -k gui/$(id -u)/com.resonanceenergy.ncl-brain && echo "  bounced"
sleep 20

echo "=== health check"
curl -sS -o /dev/null -w 'health HTTP %{http_code}  time=%{time_total}s\n' \
  http://100.72.223.123:8800/health --max-time 30

echo "=== final commit log (last 12):"
cd ~/dev/NCL && /usr/bin/git log --oneline -12
