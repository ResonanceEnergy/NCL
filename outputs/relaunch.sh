#!/bin/bash
launchctl bootout gui/$(id -u)/com.resonanceenergy.ncldesktop 2>/dev/null
pkill -f 'NCL Desktop' 2>/dev/null
sleep 1
rm -rf '/Applications/NCL Desktop.app'
cp -R '/Users/natrix/Library/Developer/Xcode/DerivedData/FirstStrike-gpnzdvxemonchhgekvmszaorgdeg/Build/Products/Debug/NCL Desktop.app' /Applications/
codesign --force --deep --sign - '/Applications/NCL Desktop.app' 2>&1 | tail -1
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.resonanceenergy.ncldesktop.plist
sleep 4
osascript -e 'tell application id "com.resonanceenergy.ncldesktop" to activate'
sleep 2
osascript -e 'tell application "System Events" to tell process "NCL Desktop" to (set frontmost to true)'
sleep 1
osascript -e 'tell application "System Events" to tell process "NCL Desktop" to keystroke "0" using command down'
sleep 1
ps aux | grep 'NCL Desktop' | grep -v grep | head -1 | awk '{print "pid:", $2}'
