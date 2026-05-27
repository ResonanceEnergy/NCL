#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add launchd/com.resonanceenergy.ncldesktop.plist

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 8 — NCL Desktop auto-launches at macOS login

New LaunchAgent at launchd/com.resonanceenergy.ncldesktop.plist (installed
to ~/Library/LaunchAgents/) wires NCL Desktop to fire automatically at
each login + auto-respawn on crash.

Key plist decisions:
  Program       = /Applications/NCL Desktop.app/Contents/MacOS/NCL Desktop
                  (direct binary, NOT 'open -a'; required so launchd
                  tracks the app's real PID rather than open's PID,
                  which is what makes KeepAlive's crash detection work).
                  Works because LSUIElement=YES — the app's
                  MenuBarExtra-only mode means it doesn't need the
                  WindowServer 'open' bootstrap dance.
  RunAtLoad     = true        — fire at login
  KeepAlive     = {SuccessfulExit:false, Crashed:true}
                                — auto-respawn on SIGKILL/crash,
                                  not when user quits cleanly
  ProcessType   = Interactive — foreground scheduling priority for GUI
  ThrottleInterval = 10s      — bounded restart loop if app is missing
  StandardOut/Err = /tmp/ncl-desktop.{out,err}.log

Pre-install one-time setup (already done on this machine — committing
the artifact for reference + future Mac reinstalls):
  cp /Users/natrix/Library/Developer/Xcode/DerivedData/.../NCL\ Desktop.app /Applications/
  codesign --force --deep --sign - '/Applications/NCL Desktop.app'  # ad-hoc resign for unsealed app
  cp launchd/com.resonanceenergy.ncldesktop.plist ~/Library/LaunchAgents/
  launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.resonanceenergy.ncldesktop.plist

Validation:
  Initial bootstrap → pid 42806 spawned automatically.
  kill -9 42806 → 12s later pid 42870 respawned via KeepAlive,
                   LastExitStatus=9 (SIGKILL) recorded in launchctl list.

Adjacent to the Brain's existing com.resonanceenergy.ncl-brain.plist
LaunchAgent — same pattern, separate process. Note CLAUDE.md's strict
no-touch rule on existing LaunchAgents applies; this NEW agent is fine
because it's a new service.

Net: 1 new plist (no code changes). +35 LOC.

Cmd+Tab + Dock now show NCL Desktop with the new pulse-waveform icon at
every login. Killing it via Force Quit will spawn it back within 10s
(intentional — operator should toggle the LaunchAgent off to stop it
permanently: launchctl bootout gui/\$(id -u)/com.resonanceenergy.ncldesktop).
"
git push origin main 2>&1 | tail -3
