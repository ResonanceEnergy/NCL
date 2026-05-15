import Foundation
import SwiftData

@Model
final class ServerConfig {
    var id: String
    var name: String
    var baseURL: String
    var authToken: String
    var isActive: Bool
    var lastConnected: Date?

    init(name: String = "NCL Brain", baseURL: String, authToken: String) {
        self.id = UUID().uuidString
        self.name = name
        self.baseURL = baseURL
        self.authToken = authToken
        self.isActive = true
        self.lastConnected = nil
    }
}
