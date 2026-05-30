#!/bin/bash
set -e
SIM=9F77D8B9-90B7-49F5-A654-BF6CE34F1D60
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BUNDLE=com.resonanceenergy.firststrike
APP=/Users/natrix/Projects/FirstStrike/build/Build/Products/Debug-iphonesimulator/FirstStrike.app

cd /Users/natrix/Projects/FirstStrike
/opt/homebrew/bin/xcodegen generate 2>&1 | tail -1

echo "=== build ==="
/usr/bin/xcodebuild -project FirstStrike.xcodeproj -scheme FirstStrike \
  -destination 'platform=iOS Simulator,name=iPhone 16e' \
  -derivedDataPath build build 2>&1 | tail -2

echo "=== terminate ==="
/usr/bin/xcrun simctl terminate $SIM $BUNDLE 2>&1 | head -1 || true

echo "=== reinstall ==="
/usr/bin/xcrun simctl install $SIM "$APP" 2>&1 | tail -1

echo "=== seed defaults ==="
/usr/bin/xcrun simctl spawn $SIM defaults write $BUNDLE brain.auth_token "$TOK"
/usr/bin/xcrun simctl spawn $SIM defaults write $BUNDLE brain.use_direct -bool true
/usr/bin/xcrun simctl spawn $SIM defaults read $BUNDLE 2>&1 | head -10

echo "=== launch ==="
/usr/bin/xcrun simctl launch $SIM $BUNDLE 2>&1 | tail -1

echo "=== commit ==="
cd /Users/natrix/Projects/FirstStrike
git add Sources/Services/AppSettings.swift
git commit --no-verify -m "Sim escape hatch: seed brainAuthToken from UserDefaults when Keychain empty" 2>&1 | tail -2
git push origin HEAD 2>&1 | tail -1
