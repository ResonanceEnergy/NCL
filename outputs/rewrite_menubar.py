#!/usr/bin/env python3
"""Replace the 8 separate Window scenes with one main NCLMainWindow."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
s = open(p).read()

# Find body opening and the App struct close, replace the whole block of
# Window() scenes with a single main scene + Quick Add HUD.
start_marker = "    var body: some Scene {\n"
end_marker = "    }\n}\n\n// MARK: - OpsClient (model)"

assert start_marker in s, "start marker missing"
assert end_marker in s, "end marker missing"

new_body = """    var body: some Scene {
        MenuBarExtra {
            OpsPanel().environmentObject(ops)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: ops.healthSymbol)
                    .foregroundColor(ops.healthColor)
                Text(ops.menuBarLabel)
                    .monospacedDigit()
            }
        }
        .menuBarExtraStyle(.window)

        // Wave 14G P9 — single unified dashboard window
        Window("NCL Desktop", id: "main") {
            NCLMainWindow()
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("0", modifiers: .command)
        .defaultSize(width: 1200, height: 820)
        .commands {
            CommandGroup(after: .appInfo) {
                CheckForUpdatesView(holder: updater)
            }
        }

        // Quick-add HUD stays a separate floating window — intentionally
        // global Cmd+Shift+J from anywhere on the Mac.
        Window("Quick Add Journal", id: "quickadd") {
            QuickAddJournalView()
        }
        .keyboardShortcut("J", modifiers: [.command, .shift])
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 480, height: 280)
"""

# Slice from start_marker through end_marker - extract the part to replace
body_start = s.index(start_marker)
body_end = s.index(end_marker)
prefix = s[:body_start]
suffix = s[body_end:]
# Append the closing braces that end_marker is anchored before
new_s = (
    prefix
    + new_body
    + "    }\n}\n\n// MARK: - OpsClient (model)"
    + suffix.split("// MARK: - OpsClient (model)", 1)[1]
)
open(p, "w").write(new_s)
print("rewrote MenuBarApp.swift body")
