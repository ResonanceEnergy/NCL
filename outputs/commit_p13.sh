#!/bin/bash
set -e

# Backend commit — start-all.sh cleanup + CLAUDE.md Wave 14G full arc
cd /Users/natrix/dev/NCL
git add CLAUDE.md start-all.sh

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G P13 backend — CLAUDE.md full arc + start-all.sh prune

CLAUDE.md updated with the full 13-phase Wave 14G summary (P1-P13)
that took the Mac NCL Desktop from zero to an iOS-identical desktop
projection with working data.

start-all.sh: Paperclip stub removed (cost_tracker.py owns this since
Wave May-19; the stub was dead weight running an empty FastAPI on :3100
every boot). Service count 4 → 3 (Brain + One-Drop + Ollama). Header
comment updated to record the retirement date.

Net: 2 modified files. CLAUDE.md +1 large section. start-all.sh -25/+5.
"
git push origin main 2>&1 | tail -3

# iOS commit — P13 surgical re-walls (Chat/Options + VoiceEngine stub)
cd /Users/natrix/Projects/FirstStrike
git add -A

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G P13 iOS — surgical Chat re-wall + VoiceEngine Mac stub

NATRIX: 'all' (P11 wholesale #if os(iOS) wrappers meant Chat / Options
didn't render on Mac at all). Re-walled surgically so Mac users get the
full conversational + options surfaces.

Changes:
1. MacSources/VoiceEngineMacStub.swift (NEW, ~35 LOC):
   @MainActor class VoiceEngine: NSObject, ObservableObject with the
   same @Published surface (isListening, voiceEnabled, transcribedText,
   audioLevel, errorMessage, etc) but all methods are silent no-ops.
   voiceEnabled stays false so ChatInputBar's mic button stays inert.
   Mac users author via keyboard. Sources/Services/VoiceEngine.swift
   stays wrapped #if os(iOS) so the real AVAudioSession-backed engine
   is only included on iOS.

2. ChatView.swift, ChatSettingsSheet.swift, ChatInputBar.swift —
   removed the wholesale #if os(iOS) wrappers from P11. The
   VoiceEngine stub resolves the missing-type errors on Mac.

3. DashboardView.swift — un-walled the `.chat case ChatView()` site
   (was rendering 'Chat lives on iPhone/iPad' Mac stub). Mac now
   shows the real ChatView when Dashboard sub-section is 'Chat'.

Built green both targets. iOS deployed to 4 devices:
  ✓ iPhone 16e sim
  ✓ iPad Pro M5 sim
  ✓ Physical iPhone (00008130-000675C822A2001C)
  ✓ Physical iPad (00008027-001664301E07002E)

Net: 1 new file + 4 modified files. ~+50/-25 LOC.
"
git push origin main 2>&1 | tail -3
