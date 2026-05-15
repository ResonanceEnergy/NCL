import SwiftUI
import SwiftData
import Combine

@MainActor
final class AppState: ObservableObject {
    @Published var isOnboarded: Bool = UserDefaults.standard.bool(forKey: "isOnboarded")
    @Published var connectionStatus: ConnectionStatus = .disconnected
    @Published var serverURL: String = UserDefaults.standard.string(forKey: "serverURL") ?? ""
    @Published var authToken: String = UserDefaults.standard.string(forKey: "authToken") ?? ""

    private(set) var apiClient: NCLAPIClient?
    private var modelContainer: ModelContainer?

    enum ConnectionStatus: String {
        case connected = "Connected"
        case connecting = "Connecting..."
        case disconnected = "Disconnected"
        case error = "Error"

        var color: Color {
            switch self {
            case .connected: return .green
            case .connecting: return .yellow
            case .disconnected: return .gray
            case .error: return .red
            }
        }

        var icon: String {
            switch self {
            case .connected: return "wifi"
            case .connecting: return "wifi.exclamationmark"
            case .disconnected: return "wifi.slash"
            case .error: return "exclamationmark.triangle.fill"
            }
        }
    }

    func configure(modelContainer: ModelContainer) {
        self.modelContainer = modelContainer
        if !serverURL.isEmpty && !authToken.isEmpty {
            setupClient()
        }
    }

    func setupClient() {
        guard !serverURL.isEmpty else { return }
        let baseURL = serverURL.hasPrefix("http") ? serverURL : "http://\(serverURL)"
        apiClient = NCLAPIClient(baseURL: baseURL, authToken: authToken)
        checkConnection()
    }

    func completeOnboarding(url: String, token: String) {
        serverURL = url
        authToken = token
        UserDefaults.standard.set(url, forKey: "serverURL")
        UserDefaults.standard.set(token, forKey: "authToken")
        UserDefaults.standard.set(true, forKey: "isOnboarded")
        isOnboarded = true
        setupClient()
    }

    func checkConnection() {
        guard let client = apiClient else {
            connectionStatus = .disconnected
            return
        }
        connectionStatus = .connecting
        Task {
            do {
                let health = try await client.healthCheck()
                connectionStatus = health.status == "ok" ? .connected : .error
            } catch {
                connectionStatus = .error
            }
        }
    }

    func resetOnboarding() {
        UserDefaults.standard.removeObject(forKey: "isOnboarded")
        UserDefaults.standard.removeObject(forKey: "serverURL")
        UserDefaults.standard.removeObject(forKey: "authToken")
        isOnboarded = false
        serverURL = ""
        authToken = ""
        apiClient = nil
        connectionStatus = .disconnected
    }
}
