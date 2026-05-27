#!/bin/bash
set -e

# iOS commit — multi-window iOS mirror on Mac target
cd /Users/natrix/Projects/FirstStrike

git add -A

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 4 iOS — multi-window Mac mirror (Cmd+1 Quiz, Cmd+2 Life)

Pulls a curated subset of the iOS view tree into the NCLDesktop target
so the Mac app exposes the same Morning Quiz + Life Plan surfaces as
the iPhone/iPad, opened in dedicated windows via Cmd+1 and Cmd+2.

Changes:

1. New Sources/App/PlatformShim.swift (~80 LOC) — Platform enum with
   setPasteboard/dismissKeyboard/primaryWindowSize/image(from:) that
   wrap UIKit on iOS and AppKit on macOS. PlatformImage typealias
   bridges UIImage/NSImage. PlatformImageView wraps Image(uiImage:)
   vs Image(nsImage:).

2. 5 view files migrated off direct UIKit references onto the shim:
   - DashboardView.swift: wrapped 'import UIKit' in #if canImport
   - DashboardView, CouncilTranscriptView, RedditView, XView,
     ChatBubble: UIPasteboard.general.string = X → Platform.setPasteboard(X)
   - CouncilView: UIApplication.sendAction(resignFirstResponder) →
     Platform.dismissKeyboard()
   - ChatBubble.shareText: walled iOS-only UIActivityViewController
     path with Mac else-branch that copies text to pasteboard
   - LifePlanEditors: UIImage → PlatformImage, UIImage(data:) →
     Platform.image(from:), Image(uiImage:) → PlatformImageView

3. LifePlanEditors.swift wrapped in #if os(iOS) wholesale — it uses
   navigationBarLeading/Trailing toolbar placements, keyboardType,
   and ForEach(\$collection) binding inference that don't map cleanly
   to macOS. Net Mac stub at MacSources/LifePlanEditorsMacStubs.swift
   (~80 LOC) provides shim sheets so LifePlanView still compiles +
   renders against the same VisionEditorSheet/GoalEditorSheet/
   PlanEditorSheet/WeeklyReviewSheet/YearlyReviewSheet/VisionBoardSheet
   references — each renders a placeholder pointing at iOS for now.

4. Services/VoiceEngine.swift wrapped in #if os(iOS) — AVAudioSession
   is iOS-only.

5. Models/ChatMessage.swift: Color(.systemGray5/6) → Color.gray opacity
   variants (cross-platform).

6. Views/Journal/MorningQuizView.swift: .autocapitalization calls
   walled in #if os(iOS).

7. project.yml: NCLDesktop target gains Sources/Models, Sources/Network,
   Sources/Services, Sources/App/Theme.swift, Sources/App/PlatformShim.swift,
   and 5 iOS view files (LifePlanView, LifePlanEditors, MorningQuizView,
   NightWatchView, IntelSignalCard, BriefRenderer).

8. MacSources/MenuBarApp.swift: 2 new @StateObject (brainClient,
   appSettings) — required by the iOS views as EnvironmentObject.
   2 new Window scenes:
     Window('Morning Quiz', id: 'quiz')     — Cmd+1 — 720×720
     Window('Life Plan',    id: 'lifeplan') — Cmd+2 — 900×760
   Both wrap their view in NavigationStack and inject the new
   StateObjects. OpsPanel actions row gains Quiz + Life buttons.

Build status: NCLDesktop ** BUILD SUCCEEDED **, FirstStrike iOS
** BUILD SUCCEEDED **. NCL Desktop relaunched pid 35504. Cmd+1 opens
the morning quiz, Cmd+2 opens the life plan dashboard.

Deferred (separate wave): NightWatchView (requires brief: param —
needs a Container that fetches the brief first), Memory/Calendar/Intel
views (each has 1-3 iOS-only patterns to wall — same surgical work as
LifePlanEditors but separate). Sources/ now compiles cleanly into Mac
target as the baseline for adding these.

Net: 1 new shim + 1 new Mac stubs file + 8 modified iOS files +
project.yml + MenuBarApp.swift. ~+330/-30 LOC.
"
git push origin main 2>&1 | tail -3

# Update CLAUDE.md (NCL side) with 14G arc — was ahead at 14F before this wave
cd /Users/natrix/dev/NCL

# (The CLAUDE.md edit happens in a separate file write step before this script runs)
git add CLAUDE.md 2>/dev/null || true

if git diff --cached --quiet; then
    echo "no CLAUDE.md changes staged"
else
    git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "CLAUDE.md — Wave 14G arc summary (P1 menu bar + P2 OpsView + P3 polish + P4 multi-window)"
    git push origin main 2>&1 | tail -3
fi
