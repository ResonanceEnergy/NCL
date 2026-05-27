#!/usr/bin/env python3
p = "/Users/natrix/Projects/FirstStrike/project.yml"
s = open(p).read()
old = "      - path: Sources/Views/CalendarSunView.swift\n      - path: Sources/Views/KnowledgeGraphView.swift\n"
new = (
    "      - path: Sources/Views/CalendarSunView.swift\n"
    "      - path: Sources/Views/KnowledgeGraphView.swift\n"
    "      - path: Sources/Views/DashboardView.swift\n"
    "      - path: Sources/Views/PortfolioView.swift\n"
    "      - path: Sources/Views/SchedulerView.swift\n"
    "      - path: Sources/Views/ChatBubble.swift\n"
    "      - path: Sources/Views/ChatInputBar.swift\n"
    "      - path: Sources/Views/CouncilView.swift\n"
    "      - path: Sources/Views/CouncilTranscriptView.swift\n"
)
if "Sources/Views/DashboardView.swift" not in s:
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("PATCHED")
else:
    print("already")
