import Foundation

public final class LocalIncidentLedger: IncidentLedgerProtocol {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "ncl.incident.ledger")

    public init(fileURL: URL? = nil) {
        if let url = fileURL {
            self.fileURL = url
        } else {
            let fm = FileManager.default
            let docs = fm.temporaryDirectory
            self.fileURL = docs.appendingPathComponent("ncl_incident_ledger.jsonl")
        }

        if !FileManager.default.fileExists(atPath: self.fileURL.path) {
            FileManager.default.createFile(atPath: self.fileURL.path, contents: nil, attributes: nil)
        }
    }

    public func append(incident: [String: Any]) {
        queue.sync {
            do {
                var record = incident
                record["recorded_at"] = ISO8601DateFormatter().string(from: Date())
                let json = try JSONSerialization.data(withJSONObject: record, options: [])
                if let handle = try? FileHandle(forWritingTo: fileURL) {
                    handle.seekToEndOfFile()
                    handle.write(json)
                    handle.write("\n".data(using: .utf8)!)
                    try handle.close()
                } else {
                    try json.write(to: fileURL, options: [.atomic])
                }
            } catch {
                print("LocalIncidentLedger append error: \(error)")
            }
        }
    }

    // Test helper: read entries
    public func readAll() -> [[String: Any]] {
        queue.sync {
            do {
                let data = try Data(contentsOf: fileURL)
                guard let text = String(data: data, encoding: .utf8) else { return [] }
                let lines = text.split(separator: "\n")
                var out: [[String: Any]] = []
                for line in lines {
                    if let d = String(line).data(using: .utf8),
                       let obj = try JSONSerialization.jsonObject(with: d, options: []) as? [String: Any] {
                        out.append(obj)
                    }
                }
                return out
            } catch {
                return []
            }
        }
    }
}
