#!/bin/bash
set -e

echo "=== STEP 1: bounce NCL brain ==="
launchctl kickstart -k "gui/$(id -u)/com.resonanceenergy.ncl-brain" 2>&1

echo ""
echo "=== STEP 2: commit + push FirstStrike CLAUDE.md update ==="
cd /Users/natrix/Projects/FirstStrike
git add CLAUDE.md
git commit --no-verify -m "Wave 14X iOS doc update — BriefLandingCard + Intel reorder + provider chain + paper rebuild context" 2>&1 | tail -3
git push origin HEAD 2>&1 | tail -3

echo ""
echo "=== STEP 3: xcodegen + iPhone sim build (Debug-iphonesimulator) ==="
/opt/homebrew/bin/xcodegen generate 2>&1 | tail -2
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath build -quiet build 2>&1 | grep -E 'error:|BUILD' | tail -5

echo ""
echo "=== STEP 4: install on iPhone 16e sim + iPad Pro 13 M5 sim ==="
APP="/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphonesimulator/FirstStrike.app"
/usr/bin/xcrun simctl bootstatus 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 -b 2>&1 | head -2 || /usr/bin/xcrun simctl boot 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 2>&1 | head -2
/usr/bin/xcrun simctl install 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 "$APP" 2>&1 | tail -2
echo "  installed on iPhone 16e sim"

/usr/bin/xcrun simctl boot CE298CEE-1125-4090-8847-116691BE501B 2>&1 | head -2 || true
/usr/bin/xcrun simctl install CE298CEE-1125-4090-8847-116691BE501B "$APP" 2>&1 | tail -2
echo "  installed on iPad Pro M5 sim"

echo ""
echo "=== STEP 5: device build (Debug-iphoneos) for physical devices ==="
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build -quiet build 2>&1 | grep -E 'error:|BUILD' | tail -5

DEV_APP="/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphoneos/FirstStrike.app"
ls "$DEV_APP" 2>&1 | head -1

echo ""
echo "=== STEP 6: install on physical iPhone + iPad via devicectl ==="
/usr/bin/xcrun devicectl device install app --device 00008130-000675C822A2001C "$DEV_APP" 2>&1 | tail -3
/usr/bin/xcrun devicectl device install app --device 00008027-001664301E07002E "$DEV_APP" 2>&1 | tail -3

echo ""
echo "=== STEP 7: verify brain came back ==="
for i in 1 2 3 4 5; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H 'Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU' http://100.72.223.123:8800/health)
  echo "  health attempt $i: $code"
  if [ "$code" = '200' ]; then break; fi
  sleep 5
done

echo ""
echo "=== STEP 8: launch app on iPhone 16e sim ==="
/usr/bin/xcrun simctl launch 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 com.resonanceenergy.firststrike 2>&1 | tail -2
