import SwiftUI

@main
struct CompanionApp: App {
    @StateObject private var health = HealthManager.shared
    @StateObject private var notifications = NotificationManager.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(health)
                .environmentObject(notifications)
        }
    }
}
