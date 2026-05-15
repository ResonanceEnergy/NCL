// FirstStrike — NCL Brain Companion
// The native iOS interface to NuRealCortexLink
// Built for NATRIX by Resonance Energy

import SwiftUI
import SwiftData

@main
struct FirstStrikeApp: App {
    @StateObject private var appState = AppState()

    var sharedModelContainer: ModelContainer = {
        let schema = Schema([
            Conversation.self,
            ChatMessage.self,
            ServerConfig.self,
        ])
        let config = ModelConfiguration(
            schema: schema,
            isStoredInMemoryOnly: false
        )
        do {
            return try ModelContainer(for: schema, configurations: [config])
        } catch {
            fatalError("Could not create ModelContainer: \(error)")
        }
    }()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .modelContainer(sharedModelContainer)
                .onAppear {
                    appState.configure(modelContainer: sharedModelContainer)
                }
        }
    }
}
