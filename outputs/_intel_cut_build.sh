#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath build build > /tmp/intel_cut_sim.log 2>&1 &
echo "sim build pid: $!"
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build build > /tmp/intel_cut_dev.log 2>&1 &
echo "device build pid: $!"
wait
echo "--- sim:"
tail -2 /tmp/intel_cut_sim.log
echo "--- device:"
tail -2 /tmp/intel_cut_dev.log
echo "--- errors:"
grep -E "error:" /tmp/intel_cut_sim.log /tmp/intel_cut_dev.log | head -10 || echo "none"
