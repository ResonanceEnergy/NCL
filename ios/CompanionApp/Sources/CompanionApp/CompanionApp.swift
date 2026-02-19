import SwiftUI

@main
struct CompanionApp: App {
    @StateObject private var health = HealthManager.shared
    @StateObject private var notifications = NotificationManager.shared

    // instantiate kernel + router with local implementations (starter wiring)
    let killSwitch = LocalKillSwitchService()
    let modalityRegistry = StubModalityRegistry()
    let policyKernel = PolicyKernel(killSwitch: killSwitch, modalityRegistry: modalityRegistry)
    let auditLedger = LocalAuditLedger()
    let actionRouter = ActionRouter(policyKernel: policyKernel, audit: auditLedger, incident: DummyIncidentLedger())

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(health)
                .environmentObject(notifications)
        }
    }
}
