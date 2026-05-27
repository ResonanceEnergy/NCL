#!/usr/bin/env python3
import re


# Wall VoiceEngine refs in ChatInputBar
p = "/Users/natrix/Projects/FirstStrike/Sources/Views/ChatInputBar.swift"
s = open(p).read()
orig = s
# Wrap @StateObject voice + voice.* refs in #if os(iOS) - safest: wrap whole file
if not s.startswith("#if os(iOS)"):
    s = "#if os(iOS)\n" + s + "\n#endif\n"
if s != orig:
    open(p, "w").write(s)
    print("walled ChatInputBar")

# Wall ChatInputBar callers if any in our target (Dashboard etc)
# Find #if-walled stubs needed
for p in [
    "/Users/natrix/Projects/FirstStrike/Sources/Views/CouncilTranscriptView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/CouncilView.swift",
    "/Users/natrix/Projects/FirstStrike/Sources/Views/ChatBubble.swift",
]:
    s = open(p).read()
    orig = s
    s = s.replace("placement: .navigationBarLeading", "placement: .cancellationAction")
    s = s.replace("placement: .navigationBarTrailing", "placement: .confirmationAction")
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
        open(p, "w").write(s)
        print("patched", p.split("/")[-1])
