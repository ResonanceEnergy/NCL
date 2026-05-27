#!/usr/bin/env python3
"""Add empty/error state to OpsView."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/OpsView.swift"
s = open(p).read()

old = """    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                connectionBanner
                cardsRow
                schedulerCard
                llmCard
                recentEventsCard
            }
            .padding(16)
        }
        .frame(minWidth: 900, minHeight: 700)
        .navigationTitle("NCL Ops")
    }"""

new = """    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                connectionBanner
                if stream.latest == nil {
                    emptyState
                } else {
                    cardsRow
                    schedulerCard
                    llmCard
                    recentEventsCard
                }
            }
            .padding(16)
        }
        .frame(minWidth: 900, minHeight: 700)
        .navigationTitle("NCL Ops")
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            if stream.lastError != nil {
                Image(systemName: "wifi.exclamationmark")
                    .font(.system(size: 36))
                    .foregroundColor(.orange)
                Text("Can't reach the Brain")
                    .font(.headline)
                Text(stream.lastError ?? "")
                    .font(.caption.monospaced())
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
                Text("Verify the Brain is up at 100.72.223.123:8800 and STRIKE_AUTH_TOKEN is in ~/dev/NCL/.env.")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
            } else {
                ProgressView()
                    .controlSize(.large)
                Text("Waiting for first snapshot from /system/ops/stream\\u{2026}")
                    .font(.caption.monospaced())
                    .foregroundColor(.secondary)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 320)
        .padding(.top, 60)
    }"""

if "emptyState" not in s:
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("added emptyState")
else:
    print("already patched")
