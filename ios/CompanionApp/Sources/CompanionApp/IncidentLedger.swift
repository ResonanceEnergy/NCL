// IncidentLedger.swift — NCL iOS Companion
// Append-only incident store. Records handler failures, policy violations, anomalies.

import Foundation

// MARK: - IncidentEntry

struct IncidentEntry: Codable {
    enum Severity: String, Codable { case info, warning, error, critical }

    let id: String
    let severity: Severity
    let summary: String
    let actionID: String?
    let timestamp: Date
    var resolved: Bool = false
    var resolvedAt: Date? = nil
    var resolvedBy: String? = nil
}

// MARK: - IncidentLedger

final class IncidentLedger {

    private let fileURL: URL
    private let queue = DispatchQueue(label: "ncl.incidentledger", qos: .utility)
    private(set) var entries: [IncidentEntry] = []

    init(directory: URL? = nil) {
        let dir = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("NCL", isDirectory: true)

        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("incident_ledger.ndjson")

        loadEntries()
    }

    // MARK: - Public API

    /// Record a new incident.
    func append(entry: IncidentEntry) {
        queue.sync {
            entries.append(entry)
            persistEntry(entry)
        }
    }

    /// Mark an incident as resolved.
    func resolve(incidentID: String, by user: String) -> Bool {
        queue.sync {
            guard let idx = entries.firstIndex(where: { $0.id == incidentID && !$0.resolved }) else {
                return false
            }
            entries[idx].resolved = true
            entries[idx].resolvedAt = Date()
            entries[idx].resolvedBy = user
            rewriteAll()
            return true
        }
    }

    /// All unresolved incidents.
    func openIncidents() -> [IncidentEntry] {
        queue.sync { entries.filter { !$0.resolved } }
    }

    /// Incidents by severity.
    func incidents(severity: IncidentEntry.Severity) -> [IncidentEntry] {
        queue.sync { entries.filter { $0.severity == severity } }
    }

    /// Export for forensics.
    func exportJSON() -> Data? {
        queue.sync { try? JSONEncoder().encode(entries) }
    }

    var count: Int { queue.sync { entries.count } }

    // MARK: - Private

    private func persistEntry(_ entry: IncidentEntry) {
        guard let data = try? JSONEncoder().encode(entry),
              let line = String(data: data, encoding: .utf8) else { return }

        let record = line + "\n"
        if let recordData = record.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: fileURL.path) {
                if let fh = try? FileHandle(forWritingTo: fileURL) {
                    fh.seekToEndOfFile()
                    fh.write(recordData)
                    fh.closeFile()
                }
            } else {
                try? recordData.write(to: fileURL, options: .atomic)
            }
        }
    }

    private func loadEntries() {
        guard let data = try? Data(contentsOf: fileURL),
              let text = String(data: data, encoding: .utf8) else { return }

        let decoder = JSONDecoder()
        for line in text.components(separatedBy: "\n") where !line.isEmpty {
            if let entryData = line.data(using: .utf8),
               let entry = try? decoder.decode(IncidentEntry.self, from: entryData) {
                entries.append(entry)
            }
        }
    }

    private func rewriteAll() {
        let encoder = JSONEncoder()
        var output = ""
        for entry in entries {
            if let data = try? encoder.encode(entry),
               let line = String(data: data, encoding: .utf8) {
                output += line + "\n"
            }
        }
        try? output.data(using: .utf8)?.write(to: fileURL, options: .atomic)
    }
}
