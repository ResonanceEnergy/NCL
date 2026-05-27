#!/usr/bin/env python3
"""P9 — direct insert of missing Window scenes + .commands block.

The prior patch attempts had stale `old` blocks that didn't match, so they
silently no-op'd. This one anchors on the unambiguous `.defaultSize(width: 900, height: 760)`
line followed by the App struct close.
"""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
s = open(p).read()

old = """        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)
    }
}"""

new = """        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)

        // Wave 14G P9 — Cmd+3..6 Window scenes
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
        .commands {
            CommandGroup(after: .appInfo) {
                CheckForUpdatesView(holder: updater)
            }
        }
    }
}"""

if 'Window("Night Watch"' in s:
    print("already patched")
elif old in s:
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("inserted Cmd+3..6 + .commands")
else:
    print("OLD BLOCK NOT FOUND — manual edit needed")
