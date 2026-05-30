#!/bin/bash
set +e
APP_SIM=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphonesimulator/FirstStrike.app
APP_DEV=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphoneos/FirstStrike.app

/usr/bin/xcrun simctl boot 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 2>/dev/null
/usr/bin/xcrun simctl boot CE298CEE-1125-4090-8847-116691BE501B 2>/dev/null

echo "=== iPhone 16e Sim"
/usr/bin/xcrun simctl install 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 "$APP_SIM" && echo "  ok"
echo "=== iPad Pro M5 Sim"
/usr/bin/xcrun simctl install CE298CEE-1125-4090-8847-116691BE501B "$APP_SIM" && echo "  ok"
echo "=== physical iPhone"
/usr/bin/xcrun devicectl device install app --device 00008130-000675C822A2001C "$APP_DEV" 2>&1 | tail -2
echo "=== physical iPad"
/usr/bin/xcrun devicectl device install app --device 00008027-001664301E07002E "$APP_DEV" 2>&1 | tail -2
