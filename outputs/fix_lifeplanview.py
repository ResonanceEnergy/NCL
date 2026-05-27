#!/usr/bin/env python3
"""Move the LifePlanView struct closing brace to after actionBtn."""

import sys


p = "/Users/natrix/Projects/FirstStrike/Sources/Views/Journal/LifePlanView.swift"
with open(p) as f:
    text = f.read()

# Find the misplaced struct-close.
# The pattern is:
#   ...        plans = await pT ?? []\n        }\n    }\n}\n\n    private var actionBar: ...
# We want to move that file-scope `}` to AFTER actionBtn closes.

needle = "        plans = await pT ?? []\n        }\n    }\n}\n\n    private var actionBar:"
if needle not in text:
    print("NEEDLE NOT FOUND — bail")
    sys.exit(1)

# Remove the struct-close `}` that comes right after the load method
text = text.replace(
    needle, "        plans = await pT ?? []\n        }\n    }\n\n    private var actionBar:", 1
)

# Insert `}\n\n` right before the `// MARK: - cardStyle helper` line, after actionBtn closes
marker = "// MARK: - cardStyle helper"
if marker not in text:
    print("CARDSTYLE MARKER NOT FOUND — bail")
    sys.exit(1)
text = text.replace(marker, "}\n\n" + marker, 1)

with open(p, "w") as f:
    f.write(text)

print("PATCHED. Verifying...")
with open(p) as f:
    new = f.read()
# Count braces to spot-check
opens = new.count("struct LifePlanView")
print(f"struct decl count: {opens}")
import re


ext_count = len(re.findall(r"private extension View", new))
print(f"private extension count: {ext_count}")
