import SwiftUI
#if os(macOS)
import Charts
import AppKit

// MARK: - NCL Desktop — Wave 14G Phase 2: OpsView main window
//
// Live ops dashboard. WebSocket /system/ops/stream → @Published snapshot ring.
// Three big cards (Host / Brain / Tailscale) + Scheduler activity grid +
// LLM call breakdown + Recent events feed. Sparkline mini-charts via
// Swift Charts.

// MARK: - OpsStream — WebSocket consumer

@MainActor
final class OpsStream: ObservableObject {
    @Published var latest: OpsSnapshot? = nil
    @Published var ring: [OpsSnapshot] = []
    @Published var connected: Bool = false
    @Published var lastError: String? = nil

    private let baseURL = URL(string: "ws://100.72.223.123:8800")!
    private var task: URLSessionWebSocketTask? = nil
    private var session: URLSession? = nil
    private var reconnectTask: Task<Void, Never>? = nil
    private let maxRingSize = 720  // 60 min @ 5s

    init() {
        connect()
    }

    deinit {
        task?.cancel(with: .goingAway, reason: nil)
        reconnectTask?.cancel()
    }

    func connect() {
        let token = NCLConfig.shared.authToken
        guard !token.isEmpty else {
            lastError = "no STRIKE_AUTH_TOKEN"
            return
        }
        var comps = URLComponents(url: baseURL.appendingPathComponent("/system/ops/stream"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "token", value: token)]
        guard let url = comps.url else { return }

        session = URLSession(configuration: .default)
        task = session?.webSocketTask(with: url)
        task?.resume()
        connected = true
        receive()
    }

    private func receive() {
        task?.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor in
                switch result {
                case .failure(let e):
                    self.connected = false
                    self.lastError = "ws: \(e.localizedDescription)"
                    self.scheduleReconnect()
                case .success(let msg):
                    switch msg {
                    case .string(let s):
                        if let data = s.data(using: .utf8) { self.ingest(data) }
                    case .data(let d):
                        self.ingest(d)
                    @unknown default:
                        break
                    }
                    self.receive()
                }
            }
        }
    }

    private func ingest(_ data: Data) {
        // Filter out keepalive pings
        if let any = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           any["type"] as? String == "ping" {
            return
        }
        do {
            let snap = try JSONDecoder().decode(OpsSnapshot.self, from: data)
            latest = snap
            ring.append(snap)
            if ring.count > maxRingSize {
                ring.removeFirst(ring.count - maxRingSize)
            }
        } catch {
            lastError = "decode: \(error.localizedDescription)"
        }
    }

    private func scheduleReconnect() {
        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            await MainActor.run { self?.connect() }
        }
    }
}

// MARK: - OpsView

struct OpsView: View {
    @StateObject private var stream = OpsStream()

    var body: some View {
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
    }

    private var connectionBanner: some View {
        HStack(spacing: 8) {
            Circle().fill(stream.connected ? .green : .red).frame(width: 8, height: 8)
            Text(stream.connected ? "Connected · /system/ops/stream" : "Disconnected — retrying")
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.secondary)
            Spacer()
            if let s = stream.latest {
                Text("sample \(Int(s.sampleDurationMs))ms · ring \(stream.ring.count)/720")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(.secondary)
            }
            if let e = stream.lastError {
                Text(e).foregroundColor(.red).font(.system(size: 10)).lineLimit(1)
            }
        }
    }

    private var cardsRow: some View {
        HStack(alignment: .top, spacing: 12) {
            hostCard
            brainCard
            tailscaleCard
        }
    }

    private var hostCard: some View {
        CardView(title: "HOST", subtitle: stream.latest?.host.hostname ?? "—") {
            VStack(alignment: .leading, spacing: 8) {
                metricRow("CPU", String(format: "%.0f%%", stream.latest?.host.cpuPct ?? 0))
                sparkline(values: stream.ring.suffix(60).map { $0.host.cpuPct },
                          color: .orange, height: 28, range: 0...100)
                metricRow("Memory", "\(String(format: "%.1f", stream.latest?.host.memUsedGb ?? 0))/\(String(format: "%.0f", stream.latest?.host.memTotalGb ?? 0)) GB")
                sparkline(values: stream.ring.suffix(60).map { $0.host.memUsedGb },
                          color: .blue, height: 24)
                metricRow("Disk free", "\(String(format: "%.0f", stream.latest?.host.diskFreeGb ?? 0)) GB")
                metricRow("Net ↓↑", "\(String(format: "%.2f", stream.latest?.host.netRxMbps ?? 0)) / \(String(format: "%.2f", stream.latest?.host.netTxMbps ?? 0)) Mbps")
            }
        }
    }

    private var brainCard: some View {
        CardView(title: "BRAIN", subtitle: "pid \(stream.latest?.brain.pid.map(String.init) ?? "?")") {
            VStack(alignment: .leading, spacing: 8) {
                metricRow("CPU", String(format: "%.0f%%", stream.latest?.brain.cpuPct ?? 0))
                sparkline(values: stream.ring.suffix(60).map { $0.brain.cpuPct },
                          color: .green, height: 28, range: 0...300)
                metricRow("RSS", "\(String(format: "%.0f", stream.latest?.brain.rssMb ?? 0)) MB")
                sparkline(values: stream.ring.suffix(60).map { $0.brain.rssMb },
                          color: .purple, height: 24)
                metricRow("Threads", "\(stream.latest?.brain.threads ?? 0)")
                metricRow("Loops", "\(stream.latest?.brain.healthyTasks ?? 0)/\(stream.latest?.brain.activeTasks ?? 0)")
                metricRow("Today $", String(format: "$%.2f (%.0f%% cap)",
                                            stream.latest?.brain.todayCostUsd ?? 0,
                                            stream.latest?.brain.todayBudgetPct ?? 0))
                sparkline(values: stream.ring.suffix(120).map { $0.brain.todayCostUsd },
                          color: .red, height: 20)
                if let dead = stream.latest?.brain.deadTasks, !dead.isEmpty {
                    Text("DEAD: \(dead.joined(separator: ", "))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.red)
                }
            }
        }
    }

    private var tailscaleCard: some View {
        CardView(title: "TAILSCALE",
                 subtitle: stream.latest?.tailscale.selfName ?? "—") {
            VStack(alignment: .leading, spacing: 6) {
                metricRow("Self", stream.latest?.tailscale.selfAddr ?? "—")
                metricRow("Online", "\(stream.latest?.tailscale.onlineCount ?? 0)/\(stream.latest?.tailscale.peerCount ?? 0)")
                Divider().padding(.vertical, 2)
                if let peers = stream.latest?.tailscale.peers, !peers.isEmpty {
                    ForEach(peers.prefix(6), id: \.name) { p in
                        HStack(spacing: 6) {
                            Circle().fill(p.online ? .green : .secondary).frame(width: 6, height: 6)
                            Text(p.name).font(.system(size: 11, design: .monospaced))
                            Spacer()
                            Text(p.relayedViaDerp ? "DERP" : "direct")
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundColor(.secondary)
                        }
                    }
                } else {
                    Text("no peers / CLI missing").font(.system(size: 10)).foregroundColor(.secondary)
                }
            }
        }
    }

    private var schedulerCard: some View {
        CardView(title: "SCHEDULER ACTIVITY",
                 subtitle: "\(stream.latest?.brain.activeTasks ?? 0) ncl-* tasks") {
            // Show task chips. Color = state.
            let activity = stream.latest?.schedulerActivity ?? []
            if activity.isEmpty {
                Text("awaiting first sample…").font(.system(size: 11)).foregroundColor(.secondary)
            } else {
                FlowLayout(spacing: 6) {
                    ForEach(activity, id: \.name) { a in
                        Text(a.name.replacingOccurrences(of: "ncl-", with: ""))
                            .font(.system(size: 10, design: .monospaced))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(stateColor(a.state).opacity(0.18))
                            .foregroundColor(stateColor(a.state))
                            .cornerRadius(4)
                    }
                }
            }
        }
    }

    private var llmCard: some View {
        let l = stream.latest?.llmCalls
        return CardView(title: "LLM CALLS (last 60 min)",
                        subtitle: "\(l?.callCount ?? 0) calls · $\(String(format: "%.2f", l?.totalCostUsd ?? 0))") {
            VStack(alignment: .leading, spacing: 6) {
                if let byModel = l?.byModel, !byModel.isEmpty {
                    ForEach(byModel.keys.sorted(), id: \.self) { model in
                        if let v = byModel[model] {
                            HStack {
                                Text(model)
                                    .font(.system(size: 11, design: .monospaced))
                                    .frame(maxWidth: 260, alignment: .leading)
                                    .lineLimit(1)
                                Spacer()
                                Text("\(v.count) calls")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(.secondary)
                                Text(String(format: "$%.4f", v.costUsd))
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(.green)
                                    .frame(width: 80, alignment: .trailing)
                            }
                        }
                    }
                } else {
                    Text("no LLM calls in window").font(.system(size: 11)).foregroundColor(.secondary)
                }
            }
        }
    }

    private var recentEventsCard: some View {
        CardView(title: "RECENT TICKS",
                 subtitle: "last 12 of \(stream.ring.count)") {
            VStack(alignment: .leading, spacing: 3) {
                ForEach(Array(stream.ring.suffix(12).reversed().enumerated()), id: \.offset) { _, snap in
                    HStack {
                        Text(timeLabel(snap.timestamp))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(.secondary)
                            .frame(width: 80, alignment: .leading)
                        Text(String(format: "cpu %.0f%%", snap.brain.cpuPct))
                            .font(.system(size: 10, design: .monospaced))
                            .frame(width: 70, alignment: .leading)
                        Text(String(format: "rss %.0fM", snap.brain.rssMb))
                            .font(.system(size: 10, design: .monospaced))
                            .frame(width: 80, alignment: .leading)
                        Text("\(snap.brain.healthyTasks)/\(snap.brain.activeTasks) loops")
                            .font(.system(size: 10, design: .monospaced))
                            .frame(width: 100, alignment: .leading)
                        Spacer()
                        Text(String(format: "sample %.0fms", snap.sampleDurationMs))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                }
            }
        }
    }

    // MARK: helpers

    @ViewBuilder
    private func sparkline(values: [Double], color: Color, height: CGFloat, range: ClosedRange<Double>? = nil) -> some View {
        if values.isEmpty {
            Color.clear.frame(height: height)
        } else {
            Chart {
                ForEach(Array(values.enumerated()), id: \.offset) { i, v in
                    LineMark(x: .value("i", i), y: .value("v", v))
                        .foregroundStyle(color)
                        .interpolationMethod(.monotone)
                    AreaMark(x: .value("i", i), y: .value("v", v))
                        .foregroundStyle(color.opacity(0.15))
                        .interpolationMethod(.monotone)
                }
            }
            .chartXAxis(.hidden).chartYAxis(.hidden)
            .chartYScale(domain: range ?? (values.min()!...max(values.max()!, values.min()! + 0.001)))
            .frame(height: height)
        }
    }

    private func metricRow(_ key: String, _ val: String) -> some View {
        HStack {
            Text(key).font(.system(size: 11, weight: .semibold, design: .monospaced)).foregroundColor(.secondary)
                .frame(width: 80, alignment: .leading)
            Text(val).font(.system(size: 13, design: .monospaced))
            Spacer()
        }
    }

    private func stateColor(_ state: String) -> Color {
        switch state {
        case "running": return .green
        case "dead":    return .red
        case "idle":    return .orange
        default:        return .secondary
        }
    }

    private func timeLabel(_ iso: String) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: iso) {
            let df = DateFormatter()
            df.dateFormat = "HH:mm:ss"
            return df.string(from: d)
        }
        return String(iso.prefix(19))
    }
}

// MARK: - CardView wrapper

private struct CardView<Content: View>: View {
    let title: String
    let subtitle: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title).font(.system(size: 11, weight: .bold, design: .monospaced)).foregroundColor(.cyan).kerning(1.2)
                Spacer()
                Text(subtitle).font(.system(size: 10, design: .monospaced)).foregroundColor(.secondary)
            }
            Divider()
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(NSColor.windowBackgroundColor).opacity(0.55))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.gray.opacity(0.2)))
        .cornerRadius(8)
    }
}

// MARK: - FlowLayout (simple wrap for scheduler chips)

private struct FlowLayout: Layout {
    let spacing: CGFloat
    init(spacing: CGFloat = 6) { self.spacing = spacing }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0
        for sub in subviews {
            let s = sub.sizeThatFits(.unspecified)
            if x + s.width > maxW {
                x = 0
                y += lineH + spacing
                lineH = 0
            }
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
        return CGSize(width: maxW, height: y + lineH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = bounds.minX, y: CGFloat = bounds.minY, lineH: CGFloat = 0
        for sub in subviews {
            let s = sub.sizeThatFits(.unspecified)
            if x + s.width > bounds.maxX {
                x = bounds.minX
                y += lineH + spacing
                lineH = 0
            }
            sub.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
    }
}

// MARK: - Extra Decodable types used by OpsView only

struct SchedulerTaskActivity: Decodable, Hashable {
    let name: String
    let state: String
    let lastRunIso: String?
    enum CodingKeys: String, CodingKey {
        case name, state
        case lastRunIso = "last_run_iso"
    }
}

struct ModelStat: Decodable {
    let count: Int
    let costUsd: Double
    enum CodingKeys: String, CodingKey {
        case count
        case costUsd = "cost_usd"
    }
}

#endif
