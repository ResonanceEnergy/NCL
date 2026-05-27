#!/bin/bash
cd /Users/natrix/Projects/FirstStrike
xcodebuild -project FirstStrike.xcodeproj -scheme NCLDesktop -destination 'platform=macOS' build > /tmp/build_p7.log 2>&1
echo "---tail---"
tail -10 /tmp/build_p7.log
echo "---errors---"
grep -E 'error:|BUILD' /tmp/build_p7.log | head -15
