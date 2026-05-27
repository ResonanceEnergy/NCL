#!/usr/bin/env python3
import re


p = "/Users/natrix/Projects/FirstStrike/Sources/Views/Journal/LifePlanView.swift"
with open(p) as f:
    lines = f.readlines()

# Sanity
assert lines[193] == "}\n", f"expected struct close on line 194, got {lines[193]!r}"

# Delete the misplaced struct close
del lines[193]

# Find // MARK: - cardStyle helper and insert struct close before it
inserted = False
for i, ln in enumerate(lines):
    if ln.startswith("// MARK: - cardStyle helper"):
        lines.insert(i, "}\n\n")
        inserted = True
        break

assert inserted, "marker not found"

with open(p, "w") as f:
    f.writelines(lines)

print("DONE")
print(f"new len: {len(lines)}")
# Verify the struct close is now in the right place
with open(p) as f:
    new = f.read()
ext = re.search(r"^private extension View", new, re.MULTILINE)
struct_close_before_ext = new.rfind("}\n\n// MARK: - cardStyle helper")
print(f"struct close before cardStyle helper: pos {struct_close_before_ext}")
