#!/usr/bin/env python3
"""Add .rotation case to IntelView's IntelSection enum + wire renderer."""

p = "/Users/natrix/Projects/FirstStrike/Sources/Views/IntelView.swift"
s = open(p).read()

# 1. Add the enum case
old_enum = '''        case predictions = "Predictions"
        case brief = "Brief"
        case nightWatch = "Night Watch"   // Wave 14A: surfaces the 2am ET maintenance brief
        case focus = "Focus"'''
new_enum = '''        case predictions = "Predictions"
        case brief = "Brief"
        case nightWatch = "Night Watch"   // Wave 14A: surfaces the 2am ET maintenance brief
        case rotation = "Rotation"        // Wave 14I item 10: capital rotation RRG widget
        case focus = "Focus"'''
if 'case rotation = "Rotation"' not in s:
    s = s.replace(old_enum, new_enum, 1)
    print("added .rotation enum case")

# 2. Wire the renderer — slot into the default ScrollView switch
old_switch = """                                case .nightWatch:
                                    nightWatchSection"""
new_switch = """                                case .nightWatch:
                                    nightWatchSection
                                case .rotation:
                                    RotationRRGView()
                                        .environmentObject(brainClient)"""
if "case .rotation:" not in s:
    s = s.replace(old_switch, new_switch, 1)
    print("added .rotation render branch")

# 3. Add to the .ytc, .reddit, .x, .focus EmptyView fallback so the
# exhaustiveness check stays happy
old_empty = """                                case .ytc, .reddit, .x, .focus:
                                    EmptyView()"""
new_empty = """                                case .ytc, .reddit, .x, .focus:
                                    EmptyView()"""  # unchanged but anchored for sanity check

# 4. Add to loadSectionData() switch — rotation doesn't need a server-side load
old_load = """        case .ytc, .reddit, .x:
            break"""
new_load = """        case .ytc, .reddit, .x, .rotation:
            // rotation loads its own data via RotationRRGView.task
            break"""
if ".rotation:" not in old_load and ".rotation" not in s.split("case .ytc, .reddit, .x:")[1][:200]:
    s = s.replace(old_load, new_load, 1)
    print("extended loadSectionData switch")

open(p, "w").write(s)
print("DONE")
