#!/usr/bin/env python3
import re


for p in ["/Users/natrix/Projects/FirstStrike/Sources/Views/DashboardView.swift"]:
    s = open(p).read()
    orig = s
    s = s.replace("placement: .navigationBarLeading", "placement: .cancellationAction")
    s = s.replace("placement: .navigationBarTrailing", "placement: .confirmationAction")
    s = re.sub(
        r"^(\s*)\.navigationBarTitleDisplayMode\(\.inline\)\s*$",
        lambda m: f"{m.group(1)}#if os(iOS)\n{m.group(0)}\n{m.group(1)}#endif",
        s,
        flags=re.MULTILINE,
    )
    if s != orig:
        open(p, "w").write(s)
        print("PATCHED", p)
