#!/bin/bash
set +e
APP_SIM=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphonesimulator/FirstStrike.app
APP_DEV=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphoneos/FirstStrike.app

# Booted sims first
echo "=== boot iPhone 16e sim if cold ==="
/usr/bin/xcrun simctl boot 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 2>/dev/null || true
echo "=== boot iPad Pro M5 sim if cold ==="
/usr/bin/xcrun simctl boot CE298CEE-1125-4090-8847-116691BE501B 2>/dev/null || true

echo "=== install iPhone 16e sim ==="
/usr/bin/xcrun simctl install 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 "$APP_SIM" && echo "  ok"
echo "=== install iPad Pro M5 sim ==="
/usr/bin/xcrun simctl install CE298CEE-1125-4090-8847-116691BE501B "$APP_SIM" && echo "  ok"

echo "=== install physical iPhone (Nathan's iPhone) ==="
/usr/bin/xcrun devicectl device install app --device 00008130-000675C822A2001C "$APP_DEV" 2>&1 | tail -3
echo "=== install physical iPad (GRIP AND RIPP HDD) ==="
/usr/bin/xcrun devicectl device install app --device 00008027-001664301E07002E "$APP_DEV" 2>&1 | tail -3
