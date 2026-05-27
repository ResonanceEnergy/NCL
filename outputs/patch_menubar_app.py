#!/usr/bin/env python3
"""Patch MenuBarApp.swift: add OpsView Window scene + extend models."""

p = "/Users/natrix/Projects/FirstStrike/MacSources/MenuBarApp.swift"
with open(p) as f:
    src = f.read()

# 1) Add Window scene for OpsView + Cmd+O menu command
old_scene = """    var body: some Scene {
        MenuBarExtra {
            OpsPanel().environmentObject(ops)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: ops.healthSymbol)
                    .foregroundColor(ops.healthColor)
                Text(ops.menuBarLabel)
                    .monospacedDigit()
            }
        }
        .menuBarExtraStyle(.window)
    }"""
new_scene = """    var body: some Scene {
        MenuBarExtra {
            OpsPanel().environmentObject(ops)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: ops.healthSymbol)
                    .foregroundColor(ops.healthColor)
                Text(ops.menuBarLabel)
                    .monospacedDigit()
            }
        }
        .menuBarExtraStyle(.window)

        // Wave 14G Phase 2 — OpsView main window (Cmd+O)
        Window("NCL Ops", id: "ops") {
            OpsView()
        }
        .keyboardShortcut("O", modifiers: .command)
        .defaultSize(width: 1000, height: 800)
    }"""
if 'Window("NCL Ops"' not in src:
    src = src.replace(old_scene, new_scene, 1)
    print("added Window scene")

# 2) Extend OpsSnapshot struct with the missing fields the OpsView consumes
old_snap = """struct OpsSnapshot: Decodable {
    let timestamp: String
    let sampleId: String
    let sampleDurationMs: Double
    let host: HostStats
    let brain: BrainStats
    let tailscale: TailscaleMesh
    let llmCalls: LLMCallSummary
    enum CodingKeys: String, CodingKey {
        case timestamp, host, brain, tailscale
        case sampleId = "sample_id"
        case sampleDurationMs = "sample_duration_ms"
        case llmCalls = "llm_calls"
    }
}"""
new_snap = """struct OpsSnapshot: Decodable {
    let timestamp: String
    let sampleId: String
    let sampleDurationMs: Double
    let host: HostStats
    let brain: BrainStats
    let tailscale: TailscaleMesh
    let llmCalls: LLMCallSummary
    let schedulerActivity: [SchedulerTaskActivity]
    enum CodingKeys: String, CodingKey {
        case timestamp, host, brain, tailscale
        case sampleId = "sample_id"
        case sampleDurationMs = "sample_duration_ms"
        case llmCalls = "llm_calls"
        case schedulerActivity = "scheduler_activity"
    }
}"""
if "schedulerActivity: [SchedulerTaskActivity]" not in src:
    src = src.replace(old_snap, new_snap, 1)
    print("extended OpsSnapshot")

# 3) Extend LLMCallSummary with byModel field
old_llm = """struct LLMCallSummary: Decodable {
    let callCount: Int
    let totalCostUsd: Double
    let windowMinutes: Int
    enum CodingKeys: String, CodingKey {
        case callCount = "call_count"
        case totalCostUsd = "total_cost_usd"
        case windowMinutes = "window_minutes"
    }
}"""
new_llm = """struct LLMCallSummary: Decodable {
    let callCount: Int
    let totalCostUsd: Double
    let windowMinutes: Int
    let byModel: [String: ModelStat]
    enum CodingKeys: String, CodingKey {
        case callCount = "call_count"
        case totalCostUsd = "total_cost_usd"
        case windowMinutes = "window_minutes"
        case byModel = "by_model"
    }
}"""
if "byModel: [String: ModelStat]" not in src:
    src = src.replace(old_llm, new_llm, 1)
    print("extended LLMCallSummary")

# 4) Add OpenWindow action to OpsPanel button row (so the panel can pop the dashboard)
old_actions = """    private var actionsRow: some View {
        HStack(spacing: 8) {
            Button("Refresh") {
                Task { await ops.fetchSnapshot() }
            }
            Spacer()
            Button("Bounce Brain") {"""
new_actions = """    @Environment(\\.openWindow) private var openWindow

    private var actionsRow: some View {
        HStack(spacing: 8) {
            Button("Refresh") {
                Task { await ops.fetchSnapshot() }
            }
            Button("Dashboard") {
                openWindow(id: "ops")
            }
            Spacer()
            Button("Bounce Brain") {"""
if 'openWindow(id: "ops")' not in src:
    src = src.replace(old_actions, new_actions, 1)
    print("added Dashboard button to OpsPanel")

with open(p, "w") as f:
    f.write(src)
print("DONE")
