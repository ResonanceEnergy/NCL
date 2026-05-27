#!/usr/bin/env python3
"""Wave 14G Phase 6 — pull IntelView + 6 subviews into Mac target + Cmd+6."""

yml_path = "/Users/natrix/Projects/FirstStrike/project.yml"
src = open(yml_path).read()
old_block = """      - path: Sources/Views/CalendarView.swift
      - path: Sources/Views/CalendarSunView.swift
      - path: Sources/Views/KnowledgeGraphView.swift"""
new_block = """      - path: Sources/Views/CalendarView.swift
      - path: Sources/Views/CalendarSunView.swift
      - path: Sources/Views/KnowledgeGraphView.swift
      - path: Sources/Views/IntelView.swift
      - path: Sources/Views/YouTubeCouncilView.swift
      - path: Sources/Views/RedditView.swift
      - path: Sources/Views/XView.swift
      - path: Sources/Views/PredictionDetailView.swift
      - path: Sources/Views/FocusContextView.swift
      - path: Sources/Views/FormattedTextView.swift"""
if "Sources/Views/IntelView.swift" not in src:
    src = src.replace(old_block, new_block, 1)
    open(yml_path, "w").write(src)
    print("patched project.yml")

mb_path = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
mb = open(mb_path).read()
old_tail = """        Window("Calendar", id: "calendar") {
            NavigationStack { CalendarView() }
                .environmentObject(brainClient)
                .environmentObject(appSettings)
        }
        .keyboardShortcut("5", modifiers: .command)
        .defaultSize(width: 1000, height: 760)
    }
}"""
new_tail = """        Window("Calendar", id: "calendar") {
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
if 'Window("Intel"' not in mb:
    mb = mb.replace(old_tail, new_tail, 1)
    print("added Cmd+6 Intel scene")

old_actions = """            Button("Night Watch") {
                openWindow(id: "nightwatch")
            }"""
new_actions = """            Button("Night Watch") {
                openWindow(id: "nightwatch")
            }
            Button("Intel") {
                openWindow(id: "intel")
            }"""
if 'openWindow(id: "intel")' not in mb:
    mb = mb.replace(old_actions, new_actions, 1)
    print("added Intel button")

open(mb_path, "w").write(mb)
print("DONE")
