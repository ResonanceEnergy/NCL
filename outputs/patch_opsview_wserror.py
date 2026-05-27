#!/usr/bin/env python3
"""Clear stuck WS lastError when next snapshot arrives."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/OpsView.swift"
s = open(p).read()

# Look at line 89-95 — the decode success path. After successful decode + ring
# append, clear lastError.
old = """                if let s = try? JSONDecoder().decode(OpsSnapshot.self, from: data) {
                    await MainActor.run {
                        self.latest = s
                        self.ring.append(s)
                        if self.ring.count > 720 {
                            self.ring.removeFirst(self.ring.count - 720)
                        }
                    }
                }"""
new = """                if let s = try? JSONDecoder().decode(OpsSnapshot.self, from: data) {
                    await MainActor.run {
                        self.latest = s
                        self.ring.append(s)
                        if self.ring.count > 720 {
                            self.ring.removeFirst(self.ring.count - 720)
                        }
                        // Clear stuck error once data is flowing again.
                        if self.lastError != nil { self.lastError = nil }
                    }
                }"""
if "Clear stuck error once data is flowing again" not in s:
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("patched lastError clear")
else:
    print("already patched")

# Also rephrase the banner: instead of showing the raw "ws: …" error in red
# inline with the metrics, change "Disconnected — retrying" to be more
# accurate when polling is succeeding.
old_banner = """            Text(stream.connected ? "Connected · /system/ops/stream" : "Disconnected — retrying")"""
new_banner = """            Text(stream.connected ? "Connected · /system/ops/stream" : (stream.latest != nil ? "Polling · stream reconnecting" : "Connecting\\u{2026}"))"""
if "Polling · stream reconnecting" not in s:
    s = s.replace(old_banner, new_banner, 1)
    open(p, "w").write(s)
    print("patched banner text")
