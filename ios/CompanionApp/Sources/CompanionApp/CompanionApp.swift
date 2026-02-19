import SwiftUI

@main
struct CompanionApp: App {
    @StateObject private var health = HealthManager.shared
    @StateObject private var notifications = NotificationManager.shared

    // TODO: instantiate PolicyKernel + ActionRouter here and inject into the environment
    // Example (starter):
    // let killSwitch = LocalKillSwitchService()
    // let modalityRegistry = DefaultModalityRegistry()
    // let policyKernel = PolicyKernel(killSwitch: killSwitch, modalityRegistry: modalityRegistry)
    // let actionRouter = ActionRouter(policyKernel: policyKernel, audit: LocalAuditLedger(), incident: LocalIncidentLedger())

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(health)
                .environmentObject(notifications)
        }
    }
}
