import SwiftUI
#if os(macOS)
import AppKit

// MARK: - NCL Desktop — Wave 14G menu-bar sentinel
//
// Always-visible status pill in the menu bar. Click expands to a small
// panel with live cost / loops / IMMEDIATE ACTION + admin actions.
//
// Polls /system/ops/snapshot every 5s. Future Phase 2 swaps polling for
// /system/ops/stream WebSocket.

@main
struct NCLDesktopApp: App {
    @StateObject private var ops = OpsClient()

    var body: some Scene {
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
    }
}

// MARK: - OpsClient (model)

@MainActor
final class OpsClient: ObservableObject {
    @Published var snapshot: OpsSnapshot? = nil
    @Published var lastError: String? = nil
    @Published var lastFetchedAt: Date? = nil

    // Tailscale IP for the Brain host. Hardcoded — matches CLAUDE.md.
    private let baseURL = URL(string: "http://100.72.223.123:8800")!
    private var pollTask: Task<Void, Never>? = nil

    init() {
        startPolling()
    }

    deinit {
        pollTask?.cancel()
    }

    var menuBarLabel: String {
        guard let s = snapshot else { return "NCL · …" }
        let cost = s.brain.todayCostUsd
        let loops = "\(s.brain.healthyTasks)/\(s.brain.activeTasks)"
        return String(format: "NCL · $%.2f · %@ loops", cost, loops)
    }

    var healthSymbol: String {
        guard let s = snapshot else { return "circle.dashed" }
        if !s.brain.deadTasks.isEmpty { return "exclamationmark.octagon.fill" }
        if s.brain.todayBudgetPct > 80 { return "exclamationmark.triangle.fill" }
        return "circle.fill"
    }

    var healthColor: Color {
        guard let s = snapshot else { return .secondary }
        if !s.brain.deadTasks.isEmpty { return .red }
        if s.brain.todayBudgetPct > 80 { return .orange }
        return .green
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.fetchSnapshot()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func fetchSnapshot() async {
        do {
            let snap = try await OpsAPI.fetchSnapshot(baseURL: baseURL, token: NCLConfig.shared.authToken)
            snapshot = snap
            lastFetchedAt = .init()
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func bounceBrain() async -> String {
        do {
            try await OpsAPI.bounceBrain()
            return "kickstart sent"
        } catch {
            return "ERR: \(error.localizedDescription)"
        }
    }
}

// MARK: - OpsPanel (UI)

struct OpsPanel: View {
    @EnvironmentObject var ops: OpsClient
    @State private var bouncingMsg: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            headerBlock
            Divider()
            healthGrid
            Divider()
            tailscaleBlock
            Divider()
            actionsRow
            if let m = bouncingMsg {
                Text(m).font(.caption).foregroundColor(.secondary)
            }
            if let e = ops.lastError {
                Text("⚠ \(e)").font(.caption).foregroundColor(.red).lineLimit(2)
            }
        }
        .padding(14)
        .frame(width: 320)
    }

    private var headerBlock: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("NCL Brain")
                .font(.system(size: 13, weight: .bold, design: .monospaced))
            if let s = ops.snapshot {
                Text("pid \(s.brain.pid.map(String.init) ?? "?") · \(formatUptime(s.brain.uptimeSeconds))")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(.secondary)
            }
        }
    }

    private var healthGrid: some View {
        let s = ops.snapshot
        return VStack(alignment: .leading, spacing: 4) {
            row("CPU",        s.map { "\($0.brain.cpuPct, specifier: "%.0f")% / host \($0.host.cpuPct, specifier: "%.0f")%" } ?? "—")
            row("RSS",        s.map { "\($0.brain.rssMb, specifier: "%.0f") MB · \($0.brain.threads) threads" } ?? "—")
            row("Loops",      s.map { "\($0.brain.healthyTasks)/\($0.brain.activeTasks) healthy" } ?? "—")
            row("Today $",    s.map { "$\($0.brain.todayCostUsd, specifier: "%.2f") (\($0.brain.todayBudgetPct, specifier: "%.0f")% cap)" } ?? "—")
            row("LLM (60m)",  s.map { "\($0.llmCalls.callCount) calls · $\($0.llmCalls.totalCostUsd, specifier: "%.2f")" } ?? "—")
            row("Host mem",   s.map { "\($0.host.memUsedGb, specifier: "%.1f")/\($0.host.memTotalGb, specifier: "%.1f") GB" } ?? "—")
            row("Disk free",  s.map { "\($0.host.diskFreeGb, specifier: "%.0f") GB" } ?? "—")
        }
    }

    private var tailscaleBlock: some View {
        let t = ops.snapshot?.tailscale
        return VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text("TAILSCALE").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundColor(.secondary)
                Spacer()
                if let t = t { Text("\(t.onlineCount)/\(t.peerCount) online").font(.system(size: 10, design: .monospaced)) }
            }
            if let peers = t?.peers, !peers.isEmpty {
                ForEach(peers.prefix(4), id: \.name) { p in
                    HStack {
                        Circle().fill(p.online ? .green : .secondary).frame(width: 6, height: 6)
                        Text(p.name).font(.system(size: 11, design: .monospaced))
                        Spacer()
                        Text(p.relayedViaDerp ? "DERP" : "direct").font(.system(size: 9)).foregroundColor(.secondary)
                    }
                }
            } else {
                Text("no peers (or CLI missing)").font(.system(size: 10)).foregroundColor(.secondary)
            }
        }
    }

    private var actionsRow: some View {
        HStack(spacing: 8) {
            Button("Refresh") {
                Task { await ops.fetchSnapshot() }
            }
            Spacer()
            Button("Bounce Brain") {
                Task {
                    bouncingMsg = "bouncing…"
                    bouncingMsg = await ops.bounceBrain()
                }
            }
            Button("Quit") {
                NSApp.terminate(nil)
            }
        }
    }

    private func row(_ key: String, _ val: String) -> some View {
        HStack {
            Text(key).font(.system(size: 10, weight: .semibold, design: .monospaced)).foregroundColor(.secondary).frame(width: 72, alignment: .leading)
            Text(val).font(.system(size: 11, design: .monospaced)).foregroundColor(.primary)
            Spacer()
        }
    }

    private func formatUptime(_ s: Int) -> String {
        let h = s / 3600, m = (s % 3600) / 60
        return "\(h)h \(m)m"
    }
}

// MARK: - Config

final class NCLConfig {
    static let shared = NCLConfig()
    var authToken: String = ""

    init() {
        // Read from ~/dev/NCL/.env at launch — same pattern the iOS app uses
        // via Keychain, but on Mac we can read the file directly.
        let envPath = NSHomeDirectory() + "/dev/NCL/.env"
        if let content = try? String(contentsOfFile: envPath, encoding: .utf8) {
            for line in content.split(separator: "\n") {
                if line.hasPrefix("STRIKE_AUTH_TOKEN=") {
                    authToken = String(line.dropFirst("STRIKE_AUTH_TOKEN=".count))
                        .trimmingCharacters(in: CharacterSet(charactersIn: "\"' "))
                    break
                }
            }
        }
    }
}

// MARK: - OpsAPI

enum OpsAPI {
    static func fetchSnapshot(baseURL: URL, token: String) async throws -> OpsSnapshot {
        var req = URLRequest(url: baseURL.appendingPathComponent("/system/ops/snapshot"))
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 5
        let (data, _) = try await URLSession.shared.data(for: req)
        let env = try JSONDecoder().decode(SnapshotEnvelope.self, from: data)
        return env.snapshot
    }

    static func bounceBrain() async throws {
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = ["kickstart", "-k", "gui/\(getuid())/com.resonanceenergy.ncl-brain"]
        try task.run()
        task.waitUntilExit()
    }
}

// MARK: - Decodable models (mirror runtime/system_monitor/models.py)

struct SnapshotEnvelope: Decodable {
    let status: String
    let snapshot: OpsSnapshot
}

struct OpsSnapshot: Decodable {
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
}

struct HostStats: Decodable {
    let cpuPct: Double
    let memUsedGb: Double
    let memTotalGb: Double
    let diskFreeGb: Double
    let netRxMbps: Double
    let netTxMbps: Double
    let hostname: String
    enum CodingKeys: String, CodingKey {
        case hostname
        case cpuPct = "cpu_pct"
        case memUsedGb = "mem_used_gb"
        case memTotalGb = "mem_total_gb"
        case diskFreeGb = "disk_free_gb"
        case netRxMbps = "net_rx_mbps"
        case netTxMbps = "net_tx_mbps"
    }
}

struct BrainStats: Decodable {
    let pid: Int?
    let cpuPct: Double
    let rssMb: Double
    let threads: Int
    let uptimeSeconds: Int
    let activeTasks: Int
    let healthyTasks: Int
    let deadTasks: [String]
    let todayCostUsd: Double
    let todayBudgetPct: Double
    enum CodingKeys: String, CodingKey {
        case pid, threads
        case cpuPct = "cpu_pct"
        case rssMb = "rss_mb"
        case uptimeSeconds = "uptime_seconds"
        case activeTasks = "active_tasks"
        case healthyTasks = "healthy_tasks"
        case deadTasks = "dead_tasks"
        case todayCostUsd = "today_cost_usd"
        case todayBudgetPct = "today_budget_pct"
    }
}

struct TailscaleMesh: Decodable {
    let selfName: String
    let selfAddr: String
    let peerCount: Int
    let onlineCount: Int
    let peers: [TailscalePeer]
    enum CodingKeys: String, CodingKey {
        case peers
        case selfName = "self_name"
        case selfAddr = "self_addr"
        case peerCount = "peer_count"
        case onlineCount = "online_count"
    }
}

struct TailscalePeer: Decodable {
    let name: String
    let addr: String
    let online: Bool
    let relayedViaDerp: Bool
    let lastHandshakeSecs: Int
    enum CodingKeys: String, CodingKey {
        case name, addr, online
        case relayedViaDerp = "relayed_via_derp"
        case lastHandshakeSecs = "last_handshake_secs"
    }
}

struct LLMCallSummary: Decodable {
    let callCount: Int
    let totalCostUsd: Double
    let windowMinutes: Int
    enum CodingKeys: String, CodingKey {
        case callCount = "call_count"
        case totalCostUsd = "total_cost_usd"
        case windowMinutes = "window_minutes"
    }
}

#endif
