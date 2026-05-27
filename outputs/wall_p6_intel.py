#!/usr/bin/env python3
"""Wall Intel subview iOS-only modifiers."""

import re


targets = [
    "/Users/natrix/Projects/FirstStrike/Sources/Views/YouTubeCouncilView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/RedditView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/XView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/PredictionDetailView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/FocusContextView.swift",
]


def apply(path: str) -> bool:
    s = open(path).read()
    orig = s
    # Placements → cross-platform actions
    s = s.replace("placement: .navigationBarLeading", "placement: .cancellationAction")
    s = s.replace("placement: .navigationBarTrailing", "placement: .confirmationAction")
    # Wall single-line iOS-only modifiers
    for pat in [
        r"^(\s*)\.navigationBarTitleDisplayMode\(\.inline\)\s*$",
        r"^(\s*)\.autocapitalization\(\.none\)\s*$",
        r"^(\s*)\.textInputAutocapitalization\([^)]+\)\s*$",
        r"^(\s*)\.keyboardType\([^)]+\)\s*$",
    ]:
        s = re.sub(
            pat,
            lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
            s,
            flags=re.MULTILINE,
        )
    if s != orig:
        open(path, "w").write(s)
        return True
    return False


for t in targets:
    print(("PATCHED" if apply(t) else "noop"), t.split("/")[-1])
