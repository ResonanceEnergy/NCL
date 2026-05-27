#!/usr/bin/env python3
"""Wall ChatBubble.shareText with #if canImport(UIKit)."""

p = "/Users/natrix/Projects/FirstStrike/Sources/Views/ChatBubble.swift"
src = open(p).read()
old = """    // MARK: - Share Helper

    private func shareText(_ text: String) {
        let activityVC = UIActivityViewController("""
new = """    // MARK: - Share Helper

    #if canImport(UIKit)
    private func shareText(_ text: String) {
        let activityVC = UIActivityViewController("""
if "#if canImport(UIKit)" not in src:
    src = src.replace(old, new, 1)
    end_marker = "rootVC.present(activityVC, animated: true)\n    }"
    end_repl = (
        "rootVC.present(activityVC, animated: true)\n    }\n"
        "    #else\n"
        "    private func shareText(_ text: String) {\n"
        "        Platform.setPasteboard(text)\n"
        "    }\n"
        "    #endif"
    )
    src = src.replace(end_marker, end_repl, 1)
    open(p, "w").write(src)
    print("walled shareText")
else:
    print("already walled")
