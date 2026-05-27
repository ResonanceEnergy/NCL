#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike

echo "[1/4] iPhone 16e sim build…"
xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
    -destination 'platform=iOS Simulator,id=9F77D8B9-90B7-49F5-A654-BF6CE34F1D60' \
    build > /tmp/sim_iphone.log 2>&1 &
SIM_IPHONE_PID=$!

echo "[2/4] iPad Pro M5 sim build…"
xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
    -destination 'platform=iOS Simulator,id=CE298CEE-1125-4090-8847-116691BE501B' \
    build > /tmp/sim_ipad.log 2>&1 &
SIM_IPAD_PID=$!

echo "[3+4/4] Device build (iPhone + iPad)…"
xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
    -destination 'generic/platform=iOS' \
    build > /tmp/device_build.log 2>&1 &
DEVICE_PID=$!

echo "Waiting for builds…"
wait $SIM_IPHONE_PID && echo "  ✓ iPhone sim build done"
wait $SIM_IPAD_PID && echo "  ✓ iPad sim build done"
wait $DEVICE_PID && echo "  ✓ Device build done"

echo "Installing on sims…"
xcrun simctl install 9F77D8B9-90B7-49F5-A654-BF6CE34F1D60 \
    ~/Library/Developer/Xcode/DerivedData/FirstStrike-gpnzdvxemonchhgekvmszaorgdeg/Build/Products/Debug-iphonesimulator/FirstStrike.app
echo "  ✓ iPhone sim installed"
xcrun simctl install CE298CEE-1125-4090-8847-116691BE501B \
    ~/Library/Developer/Xcode/DerivedData/FirstStrike-gpnzdvxemonchhgekvmszaorgdeg/Build/Products/Debug-iphonesimulator/FirstStrike.app
echo "  ✓ iPad sim installed"

echo "Installing on physical devices via devicectl…"
DEVICE_APP=~/Library/Developer/Xcode/DerivedData/FirstStrike-gpnzdvxemonchhgekvmszaorgdeg/Build/Products/Debug-iphoneos/FirstStrike.app
xcrun devicectl device install app --device 00008130-000675C822A2001C "$DEVICE_APP" 2>&1 | tail -3
echo "  ✓ Physical iPhone install attempted"
xcrun devicectl device install app --device 00008027-001664301E07002E "$DEVICE_APP" 2>&1 | tail -3
echo "  ✓ Physical iPad install attempted"
echo "DONE"
