import Foundation

public final class LocalAuditLedger: AuditLedgerProtocol {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "ncl.audit.ledger")

    public init(fileURL: URL? = nil) {
        if let url = fileURL {
            self.fileURL = url
        } else {
            let fm = FileManager.default
            let docs = fm.temporaryDirectory // use temp for safety in unit tests
            self.fileURL = docs.appendingPathComponent("ncl_audit_ledger.jsonl")
        }

        // create file if missing
        if !FileManager.default.fileExists(atPath: self.fileURL.path) {
            FileManager.default.createFile(atPath: self.fileURL.path, contents: nil, attributes: nil)
        }
    }

    public func append(record: [String: Any]) {
        queue.sync {
            do {
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
                // best-effort logging — in production surface this to IncidentLedger
                print("LocalAuditLedger append error: \(error)")
            }
        }
    }

    // Test helper: read all entries
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
