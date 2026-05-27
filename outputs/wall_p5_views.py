#!/usr/bin/env python3
"""Wave 14G Phase 5 — wall iOS-only nav modifiers in 3 view files."""

import re


# Map placement: .navigationBarLeading → .topBarLeading (cross-platform on
# iOS 14+/macOS 13+). Same for trailing.
PLACEMENT_MAP = [
    ("placement: .navigationBarLeading", "placement: .topBarLeading"),
    ("placement: .navigationBarTrailing", "placement: .topBarTrailing"),
]


def wall_nav_title_mode(src: str) -> str:
    """Wrap each `.navigationBarTitleDisplayMode(.inline)` line in #if os(iOS)."""
    pattern = re.compile(r"^(\s*)\.navigationBarTitleDisplayMode\(\.inline\)\s*$", re.MULTILINE)

    def _wrap(m):
        indent = m.group(1)
        line = m.group(0)
        return f"{indent}#if os(iOS)\n{line}\n{indent}#endif"

    return pattern.sub(_wrap, src)


def apply(path: str) -> bool:
    s = open(path).read()
    orig = s
    for old, new in PLACEMENT_MAP:
        s = s.replace(old, new)
    s = wall_nav_title_mode(s)
    if s != orig:
        open(path, "w").write(s)
        return True
    return False


targets = [
    "/Users/natrix/Projects/FirstStrike/Sources/Views/CalendarView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/IntelView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/Memory/MemoryDetailView.swift",
]
for t in targets:
    changed = apply(t)
    print(f"{'PATCHED' if changed else 'noop'}: {t}")
