#!/usr/bin/env python3
"""Fix the corrupted format specifiers in MenuBarApp.swift."""

import re


p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
with open(p) as f:
    src = f.read()

# Pattern matches the corrupted form: "String(format: "%.Xf", EXPR)"
# embedded in a string literal where it should be \(String(format: "%.Xf", EXPR)).
# Strategy: find the original "\\(EXPR, specifier: \"%.Xf\")" pattern in the
# Swift file (whatever's still there from the original write) and replace.
# Then also clean up the corrupted insertions.

# First: undo the corruption — replace inline "String(format: "%.Xf", EXPR)"
# (inside string literals) with proper \(String(format: "%.Xf", EXPR)).
pattern = re.compile(r'String\(format: "(%\.\d+f)", ([^)]+)\)')


def repl(m):
    fmt = m.group(1)
    expr = m.group(2)
    return f'\\(String(format: "{fmt}", {expr}))'


src = pattern.sub(repl, src)

with open(p, "w") as f:
    f.write(src)

print("DONE")
# Sanity check
import subprocess


r = subprocess.run(["grep", "-c", "String(format:", p], capture_output=True, text=True)
print(f"String(format:) occurrences: {r.stdout.strip()}")
