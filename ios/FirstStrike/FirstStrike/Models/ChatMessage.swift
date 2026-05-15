import Foundation
import SwiftData

@Model
final class ChatMessage {
    var id: String
    var conversationId: String
    var role: String             // "user" | "assistant" | "system" | "council" | "intel"
    var content: String
    var timestamp: Date
    var messageType: String      // "text" | "pump" | "council" | "intel" | "prediction" | "mandate" | "error"
    var isStreaming: Bool
    var metadata: String?        // JSON-encoded extra data (council results, intel brief, etc.)

    // Relationships
    var conversation: Conversation?

    init(
        role: String,
        content: String,
        conversationId: String = "",
        messageType: String = "text",
        isStreaming: Bool = false,
        metadata: String? = nil
    ) {
        self.id = UUID().uuidString
        self.conversationId = conversationId
        self.role = role
        self.content = content
        self.timestamp = Date()
        self.messageType = messageType
        self.isStreaming = isStreaming
        self.metadata = metadata
    }

    var isUser: Bool { role == "user" }
    var isAssistant: Bool { role == "assistant" || role == "council" || role == "intel" }

    var decodedMetadata: [String: Any]? {
        guard let data = metadata?.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    var formattedTime: String {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return formatter.string(from: timestamp)
    }
}
