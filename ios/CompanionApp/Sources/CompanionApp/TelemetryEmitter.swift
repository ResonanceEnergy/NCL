// TelemetryEmitter.swift — NCL iOS Companion
// Privacy-safe telemetry: counts, latency, availability, error classes ONLY.
// Never emits raw payloads, PII, or event content.

import Foundation

// MARK: - TelemetryEvent

struct TelemetryEvent: Codable {
    enum MetricType: String, Codable {
        case count         // e.g. events_captured_total
        case latency       // milliseconds
        case availability  // 0.0–1.0 ratio
        case errorClass    // bucketed error category
    }

    let metricName: String
    let metricType: MetricType
    let value: Double
    let labels: [String: String]   // e.g. {"workflow": "capture", "device": "iphone"}
    let timestamp: Date

    /// Validate that no PII or raw payload snuck in.
    var isPrivacySafe: Bool {
        let forbiddenKeys: Set<String> = ["content", "body", "message", "text", "raw", "payload", "ssn", "email"]
        for key in labels.keys {
            if forbiddenKeys.contains(key.lowercased()) { return false }
        }
        for value in labels.values {
            if value.count > 128 { return false }  // suspiciously long value
        }
        return true
    }
}

// MARK: - TelemetryEmitter

final class TelemetryEmitter {

    private let queue = DispatchQueue(label: "ncl.telemetry", qos: .utility)
    private var buffer: [TelemetryEvent] = []
    private let maxBuffer: Int
    private let flushInterval: TimeInterval
    private var flushTimer: Timer?
    private let fileURL: URL

    /// Called on each flush with the batch of events.
    var onFlush: (([TelemetryEvent]) -> Void)?

    init(directory: URL? = nil, maxBuffer: Int = 500, flushInterval: TimeInterval = 60) {
        let dir = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("NCL/telemetry", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        self.fileURL = dir.appendingPathComponent("telemetry.ndjson")
        self.maxBuffer = maxBuffer
        self.flushInterval = flushInterval

        startFlushTimer()
    }

    // MARK: - Public API

    /// Emit a count metric.
    func emitCount(_ name: String, value: Double = 1, labels: [String: String] = [:]) {
        emit(TelemetryEvent(metricName: name, metricType: .count, value: value,
                            labels: labels, timestamp: Date()))
    }

    /// Emit a latency metric (ms).
    func emitLatency(_ name: String, milliseconds: Double, labels: [String: String] = [:]) {
        emit(TelemetryEvent(metricName: name, metricType: .latency, value: milliseconds,
                            labels: labels, timestamp: Date()))
    }

    /// Emit an availability metric (0.0–1.0).
    func emitAvailability(_ name: String, ratio: Double, labels: [String: String] = [:]) {
        emit(TelemetryEvent(metricName: name, metricType: .availability,
                            value: min(1.0, max(0.0, ratio)),
                            labels: labels, timestamp: Date()))
    }

    /// Emit an error class metric.
    func emitError(_ name: String, errorClass: String, labels: [String: String] = [:]) {
        var enriched = labels
        enriched["error_class"] = errorClass
        emit(TelemetryEvent(metricName: name, metricType: .errorClass, value: 1,
                            labels: enriched, timestamp: Date()))
    }

    /// Force flush the buffer now.
    func flush() {
        queue.sync {
            guard !buffer.isEmpty else { return }
            let batch = buffer
            buffer.removeAll()
            persistBatch(batch)
            onFlush?(batch)
        }
    }

    var pendingCount: Int { queue.sync { buffer.count } }

    // MARK: - Private

    private func emit(_ event: TelemetryEvent) {
        guard event.isPrivacySafe else {
            print("[Telemetry] Rejected non-privacy-safe event: \(event.metricName)")
            return
        }
        queue.sync {
            buffer.append(event)
            if buffer.count >= maxBuffer { flushUnsafe() }
        }
    }

    private func flushUnsafe() {
        guard !buffer.isEmpty else { return }
        let batch = buffer
        buffer.removeAll()
        persistBatch(batch)
        onFlush?(batch)
    }

    private func persistBatch(_ batch: [TelemetryEvent]) {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        var lines = ""
        for event in batch {
            if let data = try? encoder.encode(event),
               let line = String(data: data, encoding: .utf8) {
                lines += line + "\n"
            }
        }
        if let data = lines.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: fileURL.path) {
                if let fh = try? FileHandle(forWritingTo: fileURL) {
                    fh.seekToEndOfFile()
                    fh.write(data)
                    fh.closeFile()
                }
            } else {
                try? data.write(to: fileURL, options: .atomic)
            }
        }
    }

    private func startFlushTimer() {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.flushTimer = Timer.scheduledTimer(withTimeInterval: self.flushInterval, repeats: true) { [weak self] _ in
                self?.flush()
            }
        }
    }
}
