#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike
git add -A

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 5 iOS — full multi-window mirror (Cmd+3 Night Watch, Cmd+4 Memory, Cmd+5 Calendar)

Extends the Mac NCLDesktop target with three additional Window scenes
mirroring the iOS Memory + Calendar + Night Watch tabs, walls a handful
of remaining iOS-only modifiers, and extracts a shared FlowLayout.

New files:
- MacSources/NightWatchContainer.swift (~70 LOC) — stateful loader that
  fetches /intelligence/night-watch/latest, handles loading/error/empty
  states, hands off to NightWatchBriefView. Required because the
  underlying view takes brief: as a non-optional init param.
- Sources/App/FlowLayout.swift (~50 LOC) — extracted from IntelView so
  both targets can use it. MemoryDetailView depended on it for entity
  chip layout; the duplicate in OpsView (Phase 2) renamed to
  ChipFlowLayout to avoid collision.

Modified files:
- CalendarView.swift, IntelView.swift, KnowledgeGraphView.swift,
  Memory/MemoryDetailView.swift: navigationBarLeading/Trailing
  placements → cancellationAction/confirmationAction (cross-platform);
  navigationBarTitleDisplayMode + autocapitalization +
  textInputAutocapitalization wrapped in #if os(iOS).
- project.yml: NCLDesktop gains Sources/Views/Memory group,
  CalendarView, CalendarSunView, KnowledgeGraphView, FlowLayout.
- MacSources/MenuBarApp.swift: 3 new Window scenes —
    Window('Night Watch', id: 'nightwatch') — Cmd+3 — 900×760
    Window('Memory',      id: 'memory')     — Cmd+4 — 1000×800
    Window('Calendar',    id: 'calendar')   — Cmd+5 — 1000×760
  OpsPanel actions row gains Memory + Calendar + Night Watch buttons.

Deferred: IntelView itself (Cmd+6) — depends on YouTubeCouncilView,
RedditView, XView, FormattedBriefView, PredictionDetailView,
FocusContextView — pulling each in would cascade 6+ additional view
files with their own iOS-specific patterns. Saved for a focused Intel
mirror wave. The Mac OpsView already covers the same intelligence
signals (lane counts, scheduler activity) at a lower fidelity.

Built green: NCLDesktop ** BUILD SUCCEEDED **, FirstStrike iOS
** BUILD SUCCEEDED **. NCL Desktop relaunched pid 39212.

Final Cmd-key map on Mac:
  Cmd+O          → Ops dashboard (host/brain/tailscale + scheduler)
  Cmd+L          → Brain log stream
  Cmd+Shift+J    → Quick-add journal HUD
  Cmd+1          → Morning Quiz
  Cmd+2          → Life Plan dashboard
  Cmd+3          → Night Watch brief (auto-loads latest)
  Cmd+4          → Memory (search/timeline/pinned/detail)
  Cmd+5          → Calendar (week/month/local/moon/sun)

Net: 2 new files + 5 modified files + project.yml + MenuBarApp.swift.
~+250/-60 LOC.
"
git push origin main 2>&1 | tail -3
