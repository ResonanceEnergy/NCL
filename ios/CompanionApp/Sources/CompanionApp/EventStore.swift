import Foundation

public struct NclEvent: Codable {
    public let id: String
    public let event_type: String
    public let recorded_at: String
    public let source: String?
    public let sensitivity: String?
    public let payload: [String: CodableValue]?
}

// Minimal CodableValue wrapper for heterogeneous payloads (starter)
public enum CodableValue: Codable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: CodableValue])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let s = try? container.decode(String.self) { self = .string(s); return }
        if let n = try? container.decode(Double.self) { self = .number(n); return }
        if let b = try? container.decode(Bool.self) { self = .bool(b); return }
        if let obj = try? container.decode([String: CodableValue].self) { self = .object(obj); return }
        throw DecodingError.typeMismatch(CodableValue.self, DecodingError.Context(codingPath: decoder.codingPath, debugDescription: "Unsupported value"))
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let s): try container.encode(s)
        case .number(let n): try container.encode(n)
        case .bool(let b): try container.encode(b)
        case .object(let o): try container.encode(o)
        }
    }
}

public final class EventStore {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "ncl.event.store")

    public init(fileURL: URL? = nil) {
        if let url = fileURL { self.fileURL = url }
        else { self.fileURL = FileManager.default.temporaryDirectory.appendingPathComponent("ncl_events.jsonl") }
        if !FileManager.default.fileExists(atPath: self.fileURL.path) {
            FileManager.default.createFile(atPath: self.fileURL.path, contents: nil, attributes: nil)
        }
    }

    public func addEvent(_ event: NclEvent) {
        queue.sync {
            do {
                let d = try JSONEncoder().encode(event)
                if let handle = try? FileHandle(forWritingTo: fileURL) {
                    handle.seekToEndOfFile()
                    handle.write(d)
                    handle.write("\n".data(using: .utf8)!)
                    try handle.close()
                } else {
                    try d.write(to: fileURL, options: [.atomic])
                }
            } catch {
                print("EventStore append error: \(error)")
            }
        }
    }

    // Naive full-text search over stored JSON lines (starter; replace with SQLite+FTS later)
    public func search(text: String, maxResults: Int = 50) -> [NclEvent] {
        return queue.sync {
            do {
                let data = try Data(contentsOf: fileURL)
                guard let textStr = String(data: data, encoding: .utf8) else { return [] }
                let lines = textStr.split(separator: "\n")
                var out: [NclEvent] = []
                for line in lines.reversed() { // return newest first
                    if line.lowercased().contains(text.lowercased()) {
                        if let d = String(line).data(using: .utf8) {
                            let e = try JSONDecoder().decode(NclEvent.self, from: d)
                            out.append(e)
                            if out.count >= maxResults { break }
                        }
                    }
                }
                return out
            } catch {
                return []
            }
        }
    }

    // Filter by time/source/sensitivity (simple implementations for starter)
    public func query(source: String? = nil, sensitivity: String? = nil) -> [NclEvent] {
        return queue.sync {
            do {
                let data = try Data(contentsOf: fileURL)
                guard let textStr = String(data: data, encoding: .utf8) else { return [] }
                let lines = textStr.split(separator: "\n")
                var out: [NclEvent] = []
                for line in lines.reversed() {
                    if let d = String(line).data(using: .utf8) {
                        let e = try JSONDecoder().decode(NclEvent.self, from: d)
                        if let s = source, e.source != s { continue }
                        if let sen = sensitivity, e.sensitivity != sen { continue }
                        out.append(e)
                    }
                }
                return out
            } catch { return [] }
        }
    }

    // Test helper
    public func clear() {
        queue.sync {
            try? FileManager.default.removeItem(at: fileURL)
            FileManager.default.createFile(atPath: fileURL.path, contents: nil, attributes: nil)
        }
    }
}
