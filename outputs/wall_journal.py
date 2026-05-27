#!/usr/bin/env python3
import re


p = "/Users/natrix/Projects/FirstStrike/Sources/Views/JournalView.swift"
s = open(p).read()
orig = s
s = re.sub(
    r"^(\s*)\.navigationBarTitleDisplayMode\([^)]+\)\s*$",
    lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
    s,
    flags=re.MULTILINE,
)
if s != orig:
    open(p, "w").write(s)
    print("walled JournalView")
