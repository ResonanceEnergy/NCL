import SwiftUI

struct ContentView: View {
    @EnvironmentObject var health: HealthManager
    @EnvironmentObject var notif: NotificationManager

    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Permissions")) {
                    Button("Request HealthKit Read") { health.requestAuthorization() }
                    Button("Request Notification Permission") { notif.requestAuthorization() }
                }

                Section(header: Text("Quick Actions")) {
                    Button("Export Health Snapshot") { Task { await health.exportSnapshot() } }
                    Button("List Recent Notification Metadata") { notif.printRecentMetadata() }
                }
            }
            .navigationTitle("NCL Companion (prototype)")
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
