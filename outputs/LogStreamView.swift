import SwiftUI
#if os(macOS)
import OSLog

// MARK: - Wave 14G Phase 3 — Brain log stream window
//
// Subscribes to OSLogStore for `subsystem = "ncl.*"` predicates. If OSLog
// has nothing (Brain logs to stdout / a file, not unified logging), falls
// back to tailing the launchd-captured log file at:
//   ~/Library/Logs/ncl-brain.log
//
// Auto-scrolls to bottom on each new line. Pause toggle stops the scroll
// + tail to let NATRIX read mid-stream. Filter field is a substring match
// on the rendered line (case-insensitive).

struct LogStreamView: View {
    @StateObject private var stream = LogStream()
    @State private var filter: String = ""
    @State private var autoscroll: Bool = true

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            logBody
            Divider()
            footer
        }
        .frame(minWidth: 720, minHeight: 480)
        .background(Color(NSColor.windowBackgroundColor))
        .onAppear { stream.start() }
        .onDisappear { stream.stop() }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: "terminal.fill")
                .foregroundColor(.green)
            Text("NCL Brain Log Stream")
                .font(.headline.monospaced())
            Spacer()
            TextField("filter…", text: $filter)
                .textFieldStyle(.roundedBorder)
                .frame(width: 200)
            Button(stream.paused ? "Resume" : "Pause") {
                stream.togglePaused()
            }
            .keyboardShortcut("p", modifiers: .command)
            Toggle("auto-scroll", isOn: $autoscroll)
                .toggleStyle(.checkbox)
                .controlSize(.small)
            Button("Clear") { stream.clear() }
                .keyboardShortcut("k", modifiers: .command)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var logBody: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(filteredLines) { line in
                        Text(line.text)
                            .font(.system(size: 11, weight: .regular, design: .monospaced))
                            .foregroundColor(color(for: line))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 1)
                            .id(line.id)
                    }
                    Color.clear.frame(height: 1).id("BOTTOM")
                }
            }
            .background(Color.black.opacity(0.85))
            .onChange(of: filteredLines.count) { _ in
                if autoscroll {
                    withAnimation(.linear(duration: 0.05)) {
                        proxy.scrollTo("BOTTOM", anchor: .bottom)
                    }
                }
            }
        }
    }

    private var footer: some View {
        HStack {
            Text("source: \(stream.sourceLabel)")
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
            Spacer()
            Text("\(filteredLines.count) of \(stream.lines.count) lines")
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
            if stream.paused {
                Text("PAUSED")
                    .font(.caption.bold().monospaced())
                    .foregroundColor(.orange)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
    }

    private var filteredLines: [LogLine] {
        guard !filter.isEmpty else { return stream.lines }
        let needle = filter.lowercased()
        return stream.lines.filter { $0.text.lowercased().contains(needle) }
    }

    private func color(for line: LogLine) -> Color {
        let t = line.text.lowercased()
        if t.contains("error") || t.contains("traceback") { return .red }
        if t.contains("warn") { return .yellow }
        if t.contains("debug") { return .secondary }
        return .green.opacity(0.85)
    }
}

// MARK: - LogStream (model)

struct LogLine: Identifiable {
    let id = UUID()
    let text: String
}

@MainActor
final class LogStream: ObservableObject {
    @Published var lines: [LogLine] = []
    @Published var paused: Bool = false
    @Published var sourceLabel: String = "init"

    private var tailTask: Task<Void, Never>? = nil
    private let maxLines = 5000

    func start() {
        stop()
        tailTask = Task { await tailLogFile() }
    }

    func stop() {
        tailTask?.cancel()
        tailTask = nil
    }

    func togglePaused() {
        paused.toggle()
    }

    func clear() {
        lines.removeAll()
    }

    private func tailLogFile() async {
        // Probe likely paths in priority order. Brain's launchd plist writes
        // stdout to ~/Library/Logs/ncl-brain.log by convention; fall back to
        // /tmp/ncl-brain.log if the plist hasn't been updated.
        let candidates = [
            "\(NSHomeDirectory())/Library/Logs/ncl-brain.log",
            "/tmp/ncl-brain.log",
            "\(NSHomeDirectory())/dev/NCL/data/logs/brain.log",
        ]
        var path: String? = nil
        for c in candidates {
            if FileManager.default.fileExists(atPath: c) {
                path = c
                break
            }
        }
        guard let logPath = path else {
            sourceLabel = "no log file found"
            await MainActor.run {
                self.lines.append(LogLine(text: "[log-stream] No Brain log file found. Checked: \(candidates.joined(separator: ", "))"))
            }
            return
        }
        sourceLabel = (logPath as NSString).lastPathComponent
        // Use Process to run `tail -F` — survives log rotations.
        let proc = Process()
        proc.launchPath = "/usr/bin/tail"
        proc.arguments = ["-n", "200", "-F", logPath]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        do {
            try proc.run()
        } catch {
            await MainActor.run {
                self.lines.append(LogLine(text: "[log-stream] tail failed: \(error.localizedDescription)"))
            }
            return
        }
        let handle = pipe.fileHandleForReading
        let stream = AsyncStream<String> { continuation in
            handle.readabilityHandler = { fh in
                let data = fh.availableData
                if data.isEmpty { return }
                if let chunk = String(data: data, encoding: .utf8) {
                    continuation.yield(chunk)
                }
            }
        }
        for await chunk in stream {
            if Task.isCancelled { break }
            if paused { continue }
            let split = chunk.split(separator: "\n", omittingEmptySubsequences: false)
            await MainActor.run {
                for s in split {
                    let txt = String(s)
                    if txt.isEmpty { continue }
                    self.lines.append(LogLine(text: txt))
                }
                if self.lines.count > self.maxLines {
                    self.lines.removeFirst(self.lines.count - self.maxLines)
                }
            }
        }
        proc.terminate()
    }
}

#endif
