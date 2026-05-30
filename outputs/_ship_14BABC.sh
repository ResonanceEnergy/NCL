#!/bin/bash
set +e
cd /Users/natrix/Projects/FirstStrike

echo "=== xcodegen"
/opt/homebrew/bin/xcodegen generate > /tmp/14babc_xcg.log 2>&1 || (tail -20 /tmp/14babc_xcg.log; exit 1)
echo "  ok"

echo "=== sim build (iPhone 16e)"
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath build build > /tmp/14babc_sim.log 2>&1
SIM=$?
echo "  exit $SIM"

if [ $SIM -eq 0 ]; then
  echo "=== device build (generic iOS)"
  /usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
    -destination 'generic/platform=iOS' \
    -derivedDataPath build build > /tmp/14babc_dev.log 2>&1
  DEV=$?
  echo "  exit $DEV"
else
  DEV=1
fi

if [ $SIM -ne 0 ] || [ $DEV -ne 0 ]; then
  echo "=== errors:"
  grep -E "error:" /tmp/14babc_sim.log /tmp/14babc_dev.log 2>&1 | head -15
  exit 1
fi
echo "=== both builds OK"
