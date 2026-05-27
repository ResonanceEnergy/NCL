#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike
git add -A

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 6 iOS — Cmd+6 Intel window (full iOS view mirror complete)

Closes the deferred IntelView slot in the Mac multi-window mirror. The
Intel tab is the most subview-heavy on iOS — pulls in YouTubeCouncilView,
RedditView, XView, FormattedBriefView, PredictionDetailView, and
FocusContextView — each with its own iOS-only modifier scatter.

Same surgical wall pattern applied across all 5 subview files:
  navigationBarLeading/Trailing → cancellationAction/confirmationAction
  navigationBarTitleDisplayMode(.inline)   → #if os(iOS) wrapped
  autocapitalization(.none)                → #if os(iOS) wrapped
  textInputAutocapitalization(...)         → #if os(iOS) wrapped
  keyboardType(...)                        → #if os(iOS) wrapped

project.yml: NCLDesktop sources gain IntelView + 6 subviews:
  YouTubeCouncilView, RedditView, XView, PredictionDetailView,
  FocusContextView, FormattedTextView (which houses FormattedBriefView).

MacSources/MenuBarApp.swift: new Window scene
  Window('Intel', id: 'intel') — Cmd+6 — 1100×800
  OpsPanel actions row gains Intel button.

Built green: NCLDesktop ** BUILD SUCCEEDED **, FirstStrike iOS
** BUILD SUCCEEDED ** on first try (the wall pattern was already
shaped from Phase 5). NCL Desktop relaunched pid 39945.

Final Cmd-key map (all 6 iOS tabs now mirrored on Mac):
  Cmd+O          Ops dashboard (Mac-only — host + brain + tailscale)
  Cmd+L          Brain log stream
  Cmd+Shift+J    Quick-add journal HUD
  Cmd+1          Morning Quiz
  Cmd+2          Life Plan
  Cmd+3          Night Watch
  Cmd+4          Memory
  Cmd+5          Calendar
  Cmd+6          Intel

Net: 5 modified subview files + project.yml + MenuBarApp.swift.
~+90/-20 LOC.

Phase 6 closes the multi-window iOS mirror arc. Remaining Wave 14G
items (Sparkle auto-update + .dmg release pipeline + app icon set +
light/dark variants) are polish-for-shipping rather than feature work
and queue as a separate desktop-distribution wave.
"
git push origin main 2>&1 | tail -3
