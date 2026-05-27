#!/usr/bin/env python3
"""Wave 14G Phase 4 — add Cmd+1/2/3 Window scenes for iOS view mirror."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
src = open(p).read()

# 1) Add the brainClient StateObject so it can be passed to windows that
# expect @EnvironmentObject var brainClient: NCLBrainClient
old_app = """@main
struct NCLDesktopApp: App {
    @StateObject private var ops = OpsClient()

    var body: some Scene {"""
new_app = """@main
struct NCLDesktopApp: App {
    @StateObject private var ops = OpsClient()
    @StateObject private var brainClient = NCLBrainClient()
    @StateObject private var appSettings = AppSettings()

    var body: some Scene {"""
if "@StateObject private var brainClient" not in src:
    src = src.replace(old_app, new_app, 1)
    print("added brainClient + appSettings StateObjects")

# 2) Add 3 new Window scenes after the Phase 3 quickadd scene
old_tail = """        // Wave 14G Phase 3 — Quick-add Journal HUD (Cmd+Shift+J)
        Window("Quick Add Journal", id: "quickadd") {
            QuickAddJournalView()
        }
        .keyboardShortcut("J", modifiers: [.command, .shift])
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 480, height: 280)
    }
}"""
new_tail = """        // Wave 14G Phase 3 — Quick-add Journal HUD (Cmd+Shift+J)
        Window("Quick Add Journal", id: "quickadd") {
            QuickAddJournalView()
        }
        .keyboardShortcut("J", modifiers: [.command, .shift])
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 480, height: 280)

        // Wave 14G Phase 4 — iOS view mirror (Cmd+1..3)
        Window("Morning Quiz", id: "quiz") {
            NavigationStack { MorningQuizView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("1", modifiers: .command)
        .defaultSize(width: 720, height: 720)

        Window("Life Plan", id: "lifeplan") {
            NavigationStack { LifePlanView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)

        Window("Night Watch", id: "nightwatch") {
            NavigationStack { NightWatchView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("3", modifiers: .command)
        .defaultSize(width: 900, height: 720)
    }
}"""
if 'Window("Morning Quiz"' not in src:
    src = src.replace(old_tail, new_tail, 1)
    print("added Cmd+1/2/3 Window scenes")

# 3) Extend the OpsPanel actions row with shortcuts to the new windows
old_actions = """            Button("Logs") {
                openWindow(id: "logs")
            }
            Button("Quick Add") {
                openWindow(id: "quickadd")
            }"""
new_actions = """            Button("Logs") {
                openWindow(id: "logs")
            }
            Button("Quick Add") {
                openWindow(id: "quickadd")
            }
            Button("Quiz") {
                openWindow(id: "quiz")
            }
            Button("Life") {
                openWindow(id: "lifeplan")
            }"""
if 'openWindow(id: "quiz")' not in src:
    src = src.replace(old_actions, new_actions, 1)
    print("added Quiz + Life buttons")

open(p, "w").write(src)
print("DONE")
