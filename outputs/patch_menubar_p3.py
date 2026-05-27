#!/usr/bin/env python3
"""Wave 14G Phase 3 — extend MenuBarApp.swift with Log + QuickAdd windows."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
with open(p) as f:
    src = f.read()

old_body = """        .menuBarExtraStyle(.window)

        // Wave 14G Phase 2 — OpsView main window (Cmd+O)
        Window("NCL Ops", id: "ops") {
            OpsView()
        }
        .keyboardShortcut("O", modifiers: .command)
        .defaultSize(width: 1000, height: 800)
    }
}"""

new_body = """        .menuBarExtraStyle(.window)

        // Wave 14G Phase 2 — OpsView main window (Cmd+O)
        Window("NCL Ops", id: "ops") {
            OpsView()
        }
        .keyboardShortcut("O", modifiers: .command)
        .defaultSize(width: 1000, height: 800)

        // Wave 14G Phase 3 — Brain log stream (Cmd+L)
        Window("NCL Logs", id: "logs") {
            LogStreamView()
        }
        .keyboardShortcut("L", modifiers: .command)
        .defaultSize(width: 900, height: 600)

        // Wave 14G Phase 3 — Quick-add Journal HUD (Cmd+Shift+J)
        Window("Quick Add Journal", id: "quickadd") {
            QuickAddJournalView()
        }
        .keyboardShortcut("J", modifiers: [.command, .shift])
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 480, height: 280)
    }
}"""

if 'Window("NCL Logs"' not in src:
    src = src.replace(old_body, new_body, 1)
    print("added Log + QuickAdd windows")
else:
    print("already patched, skipping")

# Add Dashboard / Log / Quick-add buttons to OpsPanel actions row
old_actions = """            Button("Dashboard") {
                openWindow(id: "ops")
            }
            Spacer()
            Button("Bounce Brain") {"""
new_actions = """            Button("Dashboard") {
                openWindow(id: "ops")
            }
            Button("Logs") {
                openWindow(id: "logs")
            }
            Button("Quick Add") {
                openWindow(id: "quickadd")
            }
            Spacer()
            Button("Bounce Brain") {"""
if 'openWindow(id: "logs")' not in src:
    src = src.replace(old_actions, new_actions, 1)
    print("added Logs + Quick Add buttons to OpsPanel")

with open(p, "w") as f:
    f.write(src)
print("DONE")
