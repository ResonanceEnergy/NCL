#!/usr/bin/env python3
"""P9 fix — actually add Cmd+3/4/5/6 Window scenes that P5/P6 missed."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
s = open(p).read()

# Find the end of the .commands block + before the closing braces, insert the 4
# missing Window scenes
old = """        Window("Life Plan", id: "lifeplan") {
            NavigationStack { LifePlanView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)
        .commands {"""

new = """        Window("Life Plan", id: "lifeplan") {
            NavigationStack { LifePlanView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)

        // Wave 14G Phase 5/6/P9 — full iOS view mirror (Cmd+3..6)
        Window("Night Watch", id: "nightwatch") {
            NavigationStack { NightWatchContainer() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("3", modifiers: .command)
        .defaultSize(width: 900, height: 760)

        Window("Memory", id: "memory") {
            NavigationStack { MemoryView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("4", modifiers: .command)
        .defaultSize(width: 1000, height: 800)

        Window("Calendar", id: "calendar") {
            NavigationStack { CalendarView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("5", modifiers: .command)
        .defaultSize(width: 1000, height: 760)

        Window("Intel", id: "intel") {
            NavigationStack { IntelView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("6", modifiers: .command)
        .defaultSize(width: 1100, height: 800)
        .commands {"""

if 'Window("Night Watch"' not in s:
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("added Cmd+3..6 Window scenes")
else:
    print("already present")
