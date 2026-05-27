#!/usr/bin/env python3
"""Remove wholesale #if os(iOS) wrappers from 4 files so they can be
re-walled surgically."""

files = [
    "/Users/natrix/Projects/FirstStrike/Sources/Views/ChatView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/ChatSettingsSheet.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/ChatInputBar.swift",
]
for p in files:
    s = open(p).read()
    if s.startswith("#if os(iOS)\n") and s.rstrip().endswith("#endif"):
        s = s[len("#if os(iOS)\n") :]
        idx = s.rfind("#endif")
        s = s[:idx]
        open(p, "w").write(s)
        print(f'unwrapped {p.split("/")[-1]}')
    else:
        print(f'noop {p.split("/")[-1]}')
