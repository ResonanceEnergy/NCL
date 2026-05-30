#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike

echo "=== xcodegen ==="
/opt/homebrew/bin/xcodegen generate > /tmp/14ae_xcg.log 2>&1 || (tail -20 /tmp/14ae_xcg.log; exit 1)

echo "=== xcodebuild sim (iPhone 16e) ==="
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath build build > /tmp/14ae_sim.log 2>&1 &
SIM_PID=$!

echo "=== xcodebuild device (generic iOS) ==="
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build build > /tmp/14ae_dev.log 2>&1 &
DEV_PID=$!

wait $SIM_PID
SIM_STATUS=$?
wait $DEV_PID
DEV_STATUS=$?

echo "--- sim status: $SIM_STATUS"
tail -3 /tmp/14ae_sim.log
echo "--- dev status: $DEV_STATUS"
tail -3 /tmp/14ae_dev.log

if [ $SIM_STATUS -ne 0 ] || [ $DEV_STATUS -ne 0 ]; then
  echo "=== build FAILED — errors:"
  grep -E "error:" /tmp/14ae_sim.log /tmp/14ae_dev.log | head -15
  exit 1
fi
echo "=== both builds OK"
