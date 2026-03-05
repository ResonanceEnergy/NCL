// ShortcutsHandler.swift — NCL iOS Companion
// Intents / App Group import plumbing for iOS Shortcuts capture flows.

import Foundation

// MARK: - ShortcutsHandler

final class ShortcutsHandler {

    /// App Group identifier for sharing data with Shortcuts.
    static let appGroupID = "group.com.ncl.companion"

    private let eventStore: EventStore
    private let auditLedger: AuditLedger

    init(eventStore: EventStore, auditLedger: AuditLedger) {
        self.eventStore = eventStore
        self.auditLedger = auditLedger
    }

    // MARK: - Public API

    /// Process an event envelope received from an iOS Shortcut via App Group.
    func processShortcutPayload(_ payload: [String: Any]) -> Bool {
        guard let eventID = payload["event_id"] as? String,
              let eventType = payload["event_type"] as? String,
              let occurredAt = payload["occurred_at"] as? String else {
            return false
        }

        let schemaVersion = payload["schema_version"] as? String ?? "ncl.event.v1"
        let sourceDevice = (payload["source"] as? [String: Any])?["device"] as? String ?? "iphone"
        let sourceOrigin = (payload["source"] as? [String: Any])?["origin"] as? String ?? "shortcut"
        let privacyLevel = (payload["privacy"] as? [String: Any])?["level"] as? String ?? "P3"

        // Flatten payload for FTS
        var flatPayload: [String: String] = [:]
        if let p = payload["payload"] as? [String: Any] {
            for (k, v) in p {
                flatPayload[k] = "\(v)"
            }
        }

        let rawJSON: String
        if let data = try? JSONSerialization.data(withJSONObject: payload),
           let str = String(data: data, encoding: .utf8) {
            rawJSON = str
        } else {
            rawJSON = "{}"
        }

        let event = StoredEvent(
            eventID: eventID,
            schemaVersion: schemaVersion,
            eventType: eventType,
            occurredAt: occurredAt,
            sourceDevice: sourceDevice,
            sourceOrigin: sourceOrigin,
            sensitivityLevel: privacyLevel,
            payload: flatPayload,
            provenanceLinks: [],
            rawJSON: rawJSON,
            indexedAt: Date()
        )

        let stored = eventStore.insert(event: event)

        // Audit
        auditLedger.append(entry: AuditEntry(
            id: "shortcut-\(eventID)",
            actionID: eventID,
            tier: "capture",
            category: "shortcut.capture",
            verdict: stored ? "stored" : "failed",
            reason: stored ? "event_captured_from_shortcut" : "storage_failed",
            timestamp: Date(),
            provenanceChain: []
        ))

        return stored
    }

    /// Check for pending events in the App Group shared container.
    func checkAppGroupInbox() -> [[String: Any]] {
        guard let containerURL = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: Self.appGroupID
        ) else { return [] }

        let inboxDir = containerURL.appendingPathComponent("inbox")
        guard FileManager.default.fileExists(atPath: inboxDir.path) else { return [] }

        var events: [[String: Any]] = []
        if let files = try? FileManager.default.contentsOfDirectory(
            at: inboxDir, includingPropertiesForKeys: nil
        ) {
            for file in files where file.pathExtension == "json" {
                if let data = try? Data(contentsOf: file),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    events.append(json)
                    try? FileManager.default.removeItem(at: file)
                }
            }
        }

        return events
    }

    /// Process all pending inbox items.
    func processInbox() -> Int {
        let pending = checkAppGroupInbox()
        var processed = 0
        for payload in pending {
            if processShortcutPayload(payload) {
                processed += 1
            }
        }
        return processed
    }
}
