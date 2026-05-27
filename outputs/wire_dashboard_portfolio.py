#!/usr/bin/env python3
"""Wire real DashboardView + PortfolioView into MainWindow detail pane."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MainWindow.swift"
s = open(p).read()

# Add the binding state at top of struct (we'll feed DashboardView via @State)
old_state = '@AppStorage("ncl.dashboard.section") private var rawSection: String = FSTab.dashboard.rawValue\n    @State private var section: FSTab = .dashboard'
new_state = """@AppStorage("ncl.dashboard.section") private var rawSection: String = FSTab.dashboard.rawValue
    @State private var section: FSTab = .dashboard
    @State private var intelSection: IntelView.IntelSection = .focus"""
if "intelSection: IntelView.IntelSection" not in s:
    s = s.replace(old_state, new_state, 1)
    print("added intelSection state")

# Replace stub detail cases with the real views
old_detail = """        case .dashboard:
            DashboardHomeView()
        case .portfolio:
            PortfolioStubView()
        case .intel:
            NavigationStack { IntelView() }"""
new_detail = """        case .dashboard:
            NavigationStack {
                DashboardView(selectedTab: $section, intelSection: $intelSection)
            }
        case .portfolio:
            NavigationStack { PortfolioView() }
        case .intel:
            NavigationStack { IntelView(initialSection: intelSection) }"""
if "DashboardView(selectedTab:" not in s:
    s = s.replace(old_detail, new_detail, 1)
    print("swapped detail to real views")

open(p, "w").write(s)
print("DONE")
