import Foundation
import UserNotifications
import Combine

/// Minimal Notification metadata manager (prototype). Collects metadata only.
@MainActor
final class NotificationManager: ObservableObject {
    static let shared = NotificationManager()
    private init() {}

    func requestAuthorization() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            if let e = error { print("Notification auth error:", e) }
            else { print("Notification auth granted:\(granted)") }
        }
    }

    func printRecentMetadata() {
        UNUserNotificationCenter.current().getDeliveredNotifications { notes in
            for n in notes.prefix(20) {
                // Only metadata — no content retention by default
                print("[notif] app:\(n.request.content.userInfo["sourceApp"] ?? "unknown") at \(n.date)")
            }
        }
    }

    // Hook point: transform UNNotification into ncl envelope and write to local store
    func convertToNclEnvelope(request: UNNotificationRequest) -> [String:Any] {
        let envelope: [String:Any] = [
            "event_id": UUID().uuidString,
            "event_type": "ncl.notification.by_app",
            "schema_version": "ncl.iphone.v1",
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "ingestion_method": "companion_app",
            "permission": ["granted": true],
            "retention_tier": "short",
            "privacy_level": "metadata_only",
            "provenance": ["source": "companion_app"],
            "payload": [
                "app_hash": String(describing: request.content.userInfo["sourceApp"] ?? "unknown"),
                "delivered_at": ISO8601DateFormatter().string(from: Date())
            ]
        ]
        return envelope
    }
}
