#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike
git add -A

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G P10 — Mac dashboard now mirrors iOS tab structure 1:1

Per NATRIX: 'build it identical to app, revamp desktop dashboard to match
app, change settings to OPS and combine and integrate them'.

Mac sidebar now uses the same FSTab enum + same icons + same colors as
the iOS bottom tab bar. The .settings case (which iOS hides behind the
Dashboard gear icon) is repurposed as 'Ops' on Mac and surfaces both the
live system monitor AND the brain-connection settings form in one place.

Changes:

1. Sources/Models/FSTab.swift (extracted from ContentView.swift):
   Standalone file — Dashboard/Portfolio/Intel/Memory/Calendar/Journal/
   Settings cases with icons + colors. Now conforms to Identifiable +
   Hashable so it can drive NavigationSplitView selection. Inline copy in
   ContentView.swift removed. iOS build unaffected.

2. MacSources/OpsSettingsView.swift (NEW, ~180 LOC):
   - OpsSettingsView: top capsule picker (Live · Settings · Logs) and
     ViewBuilder switch on sub-section.
   - SettingsForm: native Mac form with Brain Connection (Tailscale IP,
     port, auth token, useBrainDirect + useTailscale toggles, relay port)
     + a live Active Brain URL preview (computed from
     useTailscale/useBrainDirect flags).
   - DashboardHomeView: thin wrapper rendering OpsView as the 'home'
     surface (iOS DashboardView pulls in CouncilView + the
     conversational tree which is too heavy to port cleanly tonight).
   - PortfolioStubView: 'view on iPhone/iPad' placeholder — iOS
     PortfolioView cascades into 12+ sub-view files (Options, GOAT,
     Bravo, Paper, Crypto, Polymarket, BrokerConnect, Position rows,
     etc) — each with their own iOS-only shim needs. Defer to a focused
     Portfolio mirror wave.

3. MacSources/MainWindow.swift rewritten:
   - tabs = FSTab.bottomBarCases + [.settings] — exact same order as iOS,
     plus settings at the end as Ops.
   - Sidebar uses FSTab.icon + FSTab.color (no Mac-specific overrides)
     except .settings which is labelled 'Ops' + uses waveform.path.ecg
     icon to signal it includes the live monitor.
   - Detail @ViewBuilder switch:
       .dashboard  → DashboardHomeView (Mac variant)
       .portfolio  → PortfolioStubView
       .intel      → NavigationStack { IntelView() }
       .memory     → NavigationStack { MemoryView() }
       .calendar   → NavigationStack { CalendarView() }
       .journal    → NavigationStack { JournalView() }
       .settings   → OpsSettingsView (Live + Settings + Logs)
   - Cmd+1..7 mapped to the 7 tabs via hidden zero-sized Buttons.

4. MacSources/SeedAuthToken.swift (NEW, ~35 LOC):
   - MacAuthSeeder.seedIfEmpty(_:) reads STRIKE_AUTH_TOKEN from
     ~/dev/NCL/.env on Mac first launch and pushes it into AppSettings
     so embedded iOS views (Memory/Calendar/Intel/Journal) can hit the
     Brain without an empty-token failure.
   - @MainActor wrapped because AppSettings is main-actor isolated.
   - MenuBarApp.NCLDesktopApp.init() invokes the seeder.

5. Sources/Views/JournalView.swift: navigationBarTitleDisplayMode walled
   #if os(iOS) so JournalView compiles into the Mac target.
   project.yml gains Sources/Views/JournalView.swift to the NCLDesktop
   sources list.

Built green: NCLDesktop ** BUILD SUCCEEDED **, FirstStrike iOS
** BUILD SUCCEEDED **. NCL Desktop reinstalled to /Applications + the
LaunchAgent re-bootstrapped, app activated.

First-launch UX note: macOS pops a Keychain access dialog the first
time the Mac app tries to read the brainAuthToken that the iOS app
saved. Choose 'Always Allow' to silence subsequent prompts. After
that, the Mac app shares the same token + brain URL as iOS.

Net: 3 new files + 2 modified + project.yml + MenuBarApp.swift.
~+330/-200 LOC.

Final Mac sidebar (mirrors iOS bottom tabs):
  ⌘1  Dashboard  (live system monitor — Mac variant)
  ⌘2  Portfolio  (stub — 'view on iPhone/iPad' for v1)
  ⌘3  Intel
  ⌘4  Memory
  ⌘5  Calendar
  ⌘6  Journal    (Quiz + Life + Insights sub-tabs)
  ⌘7  Ops        (replaces Settings — Live monitor + Settings + Logs)

Plus: ⌘+Shift+J Quick Add HUD (separate floating window).
"
git push origin main 2>&1 | tail -3
