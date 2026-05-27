#!/usr/bin/env python3
p = "/Users/natrix/Projects/FirstStrike/project.yml"
s = open(p).read()
# Find the block from "Sources/Views/Memory" to "Sources/Views/JournalView.swift"
# (last cherry-pick before any other directives) and replace with a group include.
start = s.index("      - path: Sources/Views/Memory")
# Find the LAST Sources/Views/ line in the block
end_marker = "      - path: Sources/Views/JournalView.swift"
end = s.index(end_marker) + len(end_marker)
# Replace
s = s[:start] + "      - path: Sources/Views\n        type: group" + s[end:]
open(p, "w").write(s)
print("YML PATCHED — wholesale Sources/Views")
