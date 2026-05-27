#!/usr/bin/env python3
"""Wall KnowledgeGraphView iOS-only modifiers."""

import re


p = "/Users/natrix/Projects/FirstStrike/Sources/Views/KnowledgeGraphView.swift"
s = open(p).read()

# nav placements → cross-platform actions
s = s.replace("placement: .navigationBarLeading", "placement: .cancellationAction")
s = s.replace("placement: .navigationBarTrailing", "placement: .confirmationAction")

# Wall `.navigationBarTitleDisplayMode(.inline)`
s = re.sub(
    r"^(\s*)\.navigationBarTitleDisplayMode\(\.inline\)\s*$",
    lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
    s,
    flags=re.MULTILINE,
)

# Wall `.autocapitalization(.none)` lines
s = re.sub(
    r"^(\s*)\.autocapitalization\(\.none\)\s*$",
    lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
    s,
    flags=re.MULTILINE,
)

# Wall `.textInputAutocapitalization(...)` lines
s = re.sub(
    r"^(\s*)\.textInputAutocapitalization\([^)]+\)\s*$",
    lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
    s,
    flags=re.MULTILINE,
)

open(p, "w").write(s)
print("walled KnowledgeGraphView")
