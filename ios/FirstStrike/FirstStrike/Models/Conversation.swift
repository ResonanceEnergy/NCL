import Foundation
import SwiftData

@Model
final class Conversation {
    var id: String
    var title: String
    var createdAt: Date
    var updatedAt: Date
    var isPinned: Bool

    @Relationship(deleteRule: .cascade, inverse: \ChatMessage.conversation)
    var messages: [ChatMessage]?

    init(title: String = "New Conversation") {
        self.id = UUID().uuidString
        self.title = title
        self.createdAt = Date()
        self.updatedAt = Date()
        self.isPinned = false
        self.messages = []
    }

    var sortedMessages: [ChatMessage] {
        (messages ?? []).sorted { $0.timestamp < $1.timestamp }
    }

    var lastMessage: ChatMessage? {
        sortedMessages.last
    }

    var messageCount: Int {
        messages?.count ?? 0
    }
}
