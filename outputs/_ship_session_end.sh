#!/bin/bash
set +e
cd /Users/natrix/Projects/FirstStrike

echo "=== xcodegen"
/opt/homebrew/bin/xcodegen generate > /tmp/sess_xcg.log 2>&1 || (tail -10 /tmp/sess_xcg.log; exit 1)
echo "  ok"

echo "=== xcodebuild sim (iPhone 16e)"
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath build build > /tmp/sess_sim.log 2>&1
SIM=$?
echo "  exit $SIM"

echo "=== xcodebuild device (generic)"
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build build > /tmp/sess_dev.log 2>&1
DEV=$?
echo "  exit $DEV"

if [ $SIM -ne 0 ] || [ $DEV -ne 0 ]; then
  echo "=== build errors:"
  grep -E "error:" /tmp/sess_sim.log /tmp/sess_dev.log | head -10
  exit 1
fi
echo "=== both builds OK"
