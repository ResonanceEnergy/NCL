// ConsentReceiptService.swift — NCL iOS Companion
// Local signed consent receipts for sensitive data flows (health, location).

import Foundation
import CryptoKit
import Security

// MARK: - ConsentReceipt

struct ConsentReceipt: Codable, Identifiable {
    let id: String
    let dataCategory: String        // e.g. "health.data", "location.share"
    let purpose: String             // why this data is being collected
    let grantedAt: Date
    let grantedBy: String           // user role
    var revokedAt: Date?
    var revokedBy: String?
    let expiresAt: Date?            // nil = indefinite until revoked
    let signature: String           // HMAC signature for tamper detection

    var isActive: Bool {
        if revokedAt != nil { return false }
        if let exp = expiresAt, Date() > exp { return false }
        return true
    }
}

// MARK: - ConsentReceiptService

final class ConsentReceiptService {

    private let fileURL: URL
    private let signingKey: SymmetricKey
    private let queue = DispatchQueue(label: "ncl.consent", qos: .utility)
    private(set) var receipts: [ConsentReceipt] = []

    init(directory: URL? = nil, signingKey: SymmetricKey? = nil) {
        let dir = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("NCL", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        self.fileURL = dir.appendingPathComponent("consent_receipts.json")

        // Use provided key, or load/create from Keychain
        if let key = signingKey {
            self.signingKey = key
        } else {
            self.signingKey = Self.loadOrCreateKeychainKey(service: "ncl.consent.hmac")
        }

        loadReceipts()
    }

    // MARK: - Keychain Key Management

    private static func loadOrCreateKeychainKey(service: String) -> SymmetricKey {
        let account = "hmac-signing-key"

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

    /// Grant consent for a data category, returning a receipt.
    func grantConsent(dataCategory: String, purpose: String,
                      grantedBy: String, expiresIn: TimeInterval? = nil) -> ConsentReceipt {
        let id = "consent-\(dataCategory)-\(Int(Date().timeIntervalSince1970))"
        let expires = expiresIn.map { Date().addingTimeInterval($0) }

        let payloadToSign = "\(id)|\(dataCategory)|\(purpose)|\(grantedBy)"
        let sig = hmac(for: payloadToSign)

        let receipt = ConsentReceipt(
            id: id, dataCategory: dataCategory, purpose: purpose,
            grantedAt: Date(), grantedBy: grantedBy,
            revokedAt: nil, revokedBy: nil,
            expiresAt: expires, signature: sig
        )

        queue.sync {
            receipts.append(receipt)
            persist()
        }

        return receipt
    }

    /// Revoke consent by receipt ID.
    @discardableResult
    func revokeConsent(receiptID: String, revokedBy: String) -> Bool {
        queue.sync {
            guard let idx = receipts.firstIndex(where: { $0.id == receiptID && $0.isActive }) else {
                return false
            }
            receipts[idx].revokedAt = Date()
            receipts[idx].revokedBy = revokedBy
            persist()
            return true
        }
    }

    /// Check if a valid consent receipt exists for a data category.
    func hasActiveConsent(for dataCategory: String) -> Bool {
        queue.sync {
            receipts.contains { $0.dataCategory == dataCategory && $0.isActive }
        }
    }

    /// Get the active receipt ID for a data category (used by PolicyKernel).
    func activeReceiptID(for dataCategory: String) -> String? {
        queue.sync {
            receipts.first { $0.dataCategory == dataCategory && $0.isActive }?.id
        }
    }

    /// All active receipts.
    func activeReceipts() -> [ConsentReceipt] {
        queue.sync { receipts.filter { $0.isActive } }
    }

    /// Verify receipt signature integrity.
    func verifyReceipt(_ receipt: ConsentReceipt) -> Bool {
        let payload = "\(receipt.id)|\(receipt.dataCategory)|\(receipt.purpose)|\(receipt.grantedBy)"
        return hmac(for: payload) == receipt.signature
    }

    // MARK: - Private

    private func persist() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(receipts) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }

    private func loadReceipts() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        if let loaded = try? decoder.decode([ConsentReceipt].self, from: data) {
            receipts = loaded
        }
    }

    private func hmac(for string: String) -> String {
        let data = Data(string.utf8)
        let mac = HMAC<SHA256>.authenticationCode(for: data, using: signingKey)
        return mac.map { String(format: "%02x", $0) }.joined()
    }
}
