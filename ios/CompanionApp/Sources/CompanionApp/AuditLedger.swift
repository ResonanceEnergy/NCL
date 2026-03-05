// AuditLedger.swift — NCL iOS Companion
// Append-only, tamper-evident audit trail for every PolicyKernel decision.
// Local SQLite storage with HMAC signature per row.

import Foundation
import CryptoKit
import Security

// MARK: - AuditEntry

struct AuditEntry: Codable {
    let id: String
    let actionID: String
    let tier: String
    let category: String
    let verdict: String
    let reason: String
    let timestamp: Date
    let provenanceChain: [String]
}

// MARK: - AuditLedger

final class AuditLedger {

    private let fileURL: URL
    private let queue = DispatchQueue(label: "ncl.auditledger", qos: .utility)
    private let signingKey: SymmetricKey

    /// In-memory buffer (flushed on each append for durability)
    private(set) var entries: [AuditEntry] = []

    init(directory: URL? = nil, signingKey: SymmetricKey? = nil) {
        let dir = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("NCL", isDirectory: true)

        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        self.fileURL = dir.appendingPathComponent("audit_ledger.ndjson")

        // Use provided key, or attempt to load from Keychain, or generate new
        if let key = signingKey {
            self.signingKey = key
        } else {
            self.signingKey = Self.loadOrCreateKeychainKey(service: "ncl.auditledger.hmac")
        }

        // Load existing entries on init
        loadEntries()
    }

    // MARK: - Keychain Key Management

    /// Load HMAC key from Keychain, or create and store a new one.
    private static func loadOrCreateKeychainKey(service: String) -> SymmetricKey {
        let account = "hmac-signing-key"

        // Try to load existing key
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        if status == errSecSuccess, let data = result as? Data {
            return SymmetricKey(data: data)
        }

        // Generate new key and store in Keychain
        let newKey = SymmetricKey(size: .bits256)
        let keyData = newKey.withUnsafeBytes { Data(Array($0)) }

        let addQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: keyData,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        SecItemAdd(addQuery as CFDictionary, nil)

        return newKey
    }

    // MARK: - Public API

    /// Append an audit entry. Thread-safe, durable.
    func append(entry: AuditEntry) {
        queue.sync {
            entries.append(entry)
            persistEntry(entry)
        }
    }

    /// Return all entries matching a predicate.
    func search(where predicate: (AuditEntry) -> Bool) -> [AuditEntry] {
        queue.sync { entries.filter(predicate) }
    }

    /// Export ledger as JSON array (for forensics / external tooling).
    func exportJSON() -> Data? {
        queue.sync {
            try? JSONEncoder().encode(entries)
        }
    }

    /// Verify integrity of the ledger file (HMAC per line).
    func verifyIntegrity() -> Bool {
        queue.sync {
            guard let data = try? Data(contentsOf: fileURL) else { return entries.isEmpty }
            let lines = String(data: data, encoding: .utf8)?.components(separatedBy: "\n").filter { !$0.isEmpty } ?? []
            for line in lines {
                guard let separatorRange = line.range(of: "|SIG:", options: .backwards) else { return false }
                let payload = String(line[line.startIndex..<separatorRange.lowerBound])
                let storedSig = String(line[separatorRange.upperBound...])
                let expectedSig = hmac(for: payload)
                if storedSig != expectedSig { return false }
            }
            return true
        }
    }

    var count: Int { queue.sync { entries.count } }

    // MARK: - Private

    private func persistEntry(_ entry: AuditEntry) {
        guard let jsonData = try? JSONEncoder().encode(entry),
              let jsonString = String(data: jsonData, encoding: .utf8) else { return }

        let sig = hmac(for: jsonString)
        let line = "\(jsonString)|SIG:\(sig)\n"

        if let lineData = line.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: fileURL.path) {
                if let fh = try? FileHandle(forWritingTo: fileURL) {
                    fh.seekToEndOfFile()
                    fh.write(lineData)
                    fh.closeFile()
                }
            } else {
                try? lineData.write(to: fileURL, options: .atomic)
            }
        }
    }

    private func loadEntries() {
        guard let data = try? Data(contentsOf: fileURL),
              let text = String(data: data, encoding: .utf8) else { return }

        let decoder = JSONDecoder()
        for line in text.components(separatedBy: "\n") where !line.isEmpty {
            if let separatorRange = line.range(of: "|SIG:", options: .backwards) {
                let payload = String(line[line.startIndex..<separatorRange.lowerBound])
                if let entryData = payload.data(using: .utf8),
                   let entry = try? decoder.decode(AuditEntry.self, from: entryData) {
                    entries.append(entry)
                }
            }
        }
    }

    private func hmac(for string: String) -> String {
        let data = Data(string.utf8)
        let mac = HMAC<SHA256>.authenticationCode(for: data, using: signingKey)
        return mac.map { String(format: "%02x", $0) }.joined()
    }
}
