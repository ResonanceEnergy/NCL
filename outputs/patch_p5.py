#!/usr/bin/env python3
"""Wave 14G Phase 5 — pull Memory/Calendar/Intel into Mac target + Cmd+3..6."""

# 1) project.yml — add new view files to NCLDesktop sources
yml_path = "/Users/natrix/Projects/FirstStrike/project.yml"
src = open(yml_path).read()
old_block = """      - path: Sources/Views/Intel/NightWatchView.swift
      - path: Sources/Views/Intel/IntelSignalCard.swift
      - path: Sources/Views/BriefRenderer.swift"""
new_block = """      - path: Sources/Views/Intel/NightWatchView.swift
      - path: Sources/Views/Intel/IntelSignalCard.swift
      - path: Sources/Views/BriefRenderer.swift
      - path: Sources/Views/Memory
        type: group
      - path: Sources/Views/CalendarView.swift
      - path: Sources/Views/IntelView.swift"""
if "Sources/Views/Memory" not in src:
    src = src.replace(old_block, new_block, 1)
    open(yml_path, "w").write(src)
    print("patched project.yml")

# 2) MenuBarApp.swift — add Cmd+3..6 Window scenes
mb_path = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
mb = open(mb_path).read()

old_tail = """        Window("Life Plan", id: "lifeplan") {
            NavigationStack { LifePlanView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)
    }
}"""
new_tail = """        Window("Life Plan", id: "lifeplan") {
            NavigationStack { LifePlanView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("2", modifiers: .command)
        .defaultSize(width: 900, height: 760)

        // Wave 14G Phase 5 — full iOS view mirror (Cmd+3..6)
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
    }
}"""
if 'Window("Night Watch"' not in mb:
    mb = mb.replace(old_tail, new_tail, 1)
    print("added Cmd+3..6 Window scenes")

# 3) Add buttons to OpsPanel actions row
old_actions = """            Button("Quiz") {
                openWindow(id: "quiz")
            }
            Button("Life") {
                openWindow(id: "lifeplan")
            }"""
new_actions = """            Button("Quiz") {
                openWindow(id: "quiz")
            }
            Button("Life") {
                openWindow(id: "lifeplan")
            }
            Button("Memory") {
                openWindow(id: "memory")
            }
            Button("Calendar") {
                openWindow(id: "calendar")
            }
            Button("Intel") {
                openWindow(id: "intel")
            }
            Button("Night Watch") {
                openWindow(id: "nightwatch")
            }"""
if 'openWindow(id: "memory")' not in mb:
    mb = mb.replace(old_actions, new_actions, 1)
    print("added Memory/Calendar/Intel/NightWatch buttons")

open(mb_path, "w").write(mb)
print("DONE")
