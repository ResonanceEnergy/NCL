#!/usr/bin/env python3
p = "/Users/natrix/Projects/FirstStrike/project.yml"
s = open(p).read()
start = s.index("      - path: Sources/Views/Memory")
end = s.index("      - path: Sources/Views/CouncilTranscriptView.swift") + len(
    "      - path: Sources/Views/CouncilTranscriptView.swift"
)
new = "      - path: Sources/Views\n        type: group"
s = s[:start] + new + s[end:]
# Trim any extra blank line right after
s = s.replace("group\n\n    settings:", "group\n    settings:", 1)
open(p, "w").write(s)
print("switched to Sources/Views group")
