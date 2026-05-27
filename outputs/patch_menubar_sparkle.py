#!/usr/bin/env python3
"""Wire SparkleUpdater + Commands menu Check for Updates into NCLDesktopApp."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
s = open(p).read()

# Add updater StateObject + .commands menu
old_app = """@main
struct NCLDesktopApp: App {
    @StateObject private var ops = OpsClient()
    @StateObject private var brainClient = NCLBrainClient()
    @StateObject private var appSettings = AppSettings()

    var body: some Scene {"""
new_app = """@main
struct NCLDesktopApp: App {
    @StateObject private var ops = OpsClient()
    @StateObject private var brainClient = NCLBrainClient()
    @StateObject private var appSettings = AppSettings()
    @StateObject private var updater = UpdaterHolder()

    var body: some Scene {"""
if "@StateObject private var updater" not in s:
    s = s.replace(old_app, new_app, 1)
    print("added updater StateObject")

# Append .commands modifier at the very end of body. The body ends with
# Window("Intel"...) .keyboardShortcut("6", modifiers: .command) .defaultSize(...).
# Tag the closing `}\n}` of the App struct and inject .commands { } before it.
old_close = """        .keyboardShortcut("6", modifiers: .command)
        .defaultSize(width: 1100, height: 800)
    }
}"""
new_close = """        .keyboardShortcut("6", modifiers: .command)
        .defaultSize(width: 1100, height: 800)
        .commands {
            CommandGroup(after: .appInfo) {
                CheckForUpdatesView(holder: updater)
            }
        }
    }
}"""
if ".commands {" not in s:
    s = s.replace(old_close, new_close, 1)
    print("added Commands menu for Check for Updates")

open(p, "w").write(s)
print("DONE")
