#!/bin/bash
set -e

# Backend commit (Tailscale parse fixes)
cd /Users/natrix/dev/NCL
git add runtime/system_monitor/collectors.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 3 — Tailscale parser polish (name + handshake)

Two fixes in runtime/system_monitor/collectors.py addressing the
remaining polish items from Phase 2:

1. Handshake epoch overflow. Tailscale uses 0001-01-01T00:00:00Z for
   peers that have never handshaked; the prior parse subtracted that
   epoch from now-UTC and rendered ~63 billion seconds. Added a year<2000
   sentinel that emits last_age=-1 so the desktop can render \"never\"
   instead of garbage.

2. Peer name fallback chain. iOS Tailscale clients sometimes report
   HostName as 'localhost' (the device's actual hostname). New fallback
   chain: HostName (if non-empty and != localhost) → DNSName leftmost
   label → OS-{pkey[:8]} → pkey[:12]. Result: peers now render as
   'ipad-pro-11-gen-1' + 'iphone-15-pro-max' instead of two 'localhost'
   rows.

Live verification post-bounce:
  PEERS: 2/2  self=NATRIX's Mac Studio 100.72.223.123
    ● ipad-pro-11-gen-1     100.76.184.123  hs=never DERP
    ● iphone-15-pro-max     100.82.59.60    hs=never DERP

Net: 1 file, ~+24/-7 LOC.
"
git push origin main 2>&1 | tail -3

# iOS commit
cd /Users/natrix/Projects/FirstStrike
git add MacSources/LogStreamView.swift MacSources/QuickAddJournalView.swift MacSources/MenuBarApp.swift

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 3 iOS — Log stream + Quick-add HUD windows

Two new MacSources/ views + MenuBarApp.swift extension implementing
the highest-leverage power-user surfaces from Phase 3 (weeks 6-7) of
docs/DESKTOP_OPTIONS_2026-05-25.md.

1. LogStreamView (~200 LOC): live tail of the Brain log file via
   Process(/usr/bin/tail -n 200 -F). Probes:
     ~/Library/Logs/ncl-brain.log
     /tmp/ncl-brain.log
     ~/dev/NCL/data/logs/brain.log
   First-hit wins. Renders monospaced black-bg pane with:
     - filter textfield (case-insensitive substring)
     - Pause/Resume button (Cmd+P) — stops scroll + accumulation
     - auto-scroll toggle
     - Clear (Cmd+K)
     - color coding by level: red=error/traceback, yellow=warn,
       gray=debug, green=info
     - 5,000-line cap with FIFO eviction
   Opens via Cmd+L on the new Window scene 'NCL Logs' (id: 'logs') or
   the new Logs button on OpsPanel.

2. QuickAddJournalView (~210 LOC): floating Cmd+Shift+J HUD for
   single-shot journal entries. Shows:
     - 120pt minimum TextEditor with drop target (text appends,
       image / file URL becomes attachment_path)
     - Kind picker (note/observation/lesson/reflection/morning_quiz)
     - 0-100 importance slider
     - Submit (Cmd+Return) → POST /journal/entries → auto-dismiss
     - Cancel (Esc) bound to dismissWindow
   Window style hiddenTitleBar + windowResizability(.contentSize)
   for a tight HUD feel. NSApp.activate(ignoringOtherApps: true) on
   appear pulls it to the front from any other app.

3. MenuBarApp.swift: 2 new Window scenes (logs, quickadd) wired with
   keyboard shortcuts; OpsPanel actions row gains Logs + Quick Add
   buttons next to the existing Dashboard button.

Built green for Mac target. NCL Desktop relaunched pid 32834. Cmd+L
opens the log stream, Cmd+Shift+J opens the quick-add HUD anywhere.

Net: 2 new files + 1 patched file, ~+440/-2 LOC.

Phase 3 remaining (deferred): multi-window iOS view mirror (Cmd+1..5),
multi-tab Council view, vision-board drag-edit, Sparkle auto-update,
GitHub release pipeline. The iOS mirror requires #if canImport(UIKit)
walls around ~15 view files before they'll compile against the Mac
target — separate refactor wave.
"
git push origin main 2>&1 | tail -3
