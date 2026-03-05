// FeatureFlags.swift — NCL iOS Companion
// Staged rollout support with AZ_PRIME-only visibility for certain flags.

import Foundation

// MARK: - FeatureFlag

struct FeatureFlag: Codable, Identifiable {
    let id: String
    let name: String
    let description: String
    var enabled: Bool
    let requiredRole: String     // "AZ_PRIME", "operator", "any"
    let createdAt: Date
    var updatedAt: Date
}

// MARK: - FeatureFlags

final class FeatureFlags: ObservableObject {

    @Published private(set) var flags: [String: FeatureFlag] = [:]

    private let defaults: UserDefaults
    private static let persistenceKey = "ncl.feature_flags"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        loadFlags()
        registerDefaults()
    }

    // MARK: - Public API

    /// Check if a feature is enabled.
    func isEnabled(_ flagID: String) -> Bool {
        flags[flagID]?.enabled ?? false
    }

    /// Set flag state (respects role requirement).
    @discardableResult
    func setFlag(_ flagID: String, enabled: Bool, by userRole: String) -> Bool {
        guard var flag = flags[flagID] else { return false }
        guard userRole == "AZ_PRIME" || flag.requiredRole != "AZ_PRIME" else { return false }

        flag.enabled = enabled
        flag.updatedAt = Date()
        flags[flagID] = flag
        persist()
        return true
    }

    /// Register a new flag.
    func register(_ flag: FeatureFlag) {
        if flags[flag.id] == nil {
            flags[flag.id] = flag
            persist()
        }
    }

    /// Flags visible to a given role.
    func visibleFlags(for role: String) -> [FeatureFlag] {
        flags.values.filter { flag in
            role == "AZ_PRIME" || flag.requiredRole != "AZ_PRIME"
        }.sorted { $0.id < $1.id }
    }

    // MARK: - Private

    private func registerDefaults() {
        let defaultFlags: [FeatureFlag] = [
            FeatureFlag(id: "neural_intent_signal", name: "Neural Intent Signal",
                        description: "Experimental intent prediction. Hard-off by default.",
                        enabled: false, requiredRole: "AZ_PRIME",
                        createdAt: Date(), updatedAt: Date()),
            FeatureFlag(id: "council_runner", name: "Council Runner",
                        description: "Multi-agent council for risk assessment.",
                        enabled: true, requiredRole: "operator",
                        createdAt: Date(), updatedAt: Date()),
            FeatureFlag(id: "auto_downgrade", name: "Auto System Downgrade",
                        description: "Automatic mode transitions on error thresholds.",
                        enabled: true, requiredRole: "operator",
                        createdAt: Date(), updatedAt: Date()),
            FeatureFlag(id: "telemetry", name: "Privacy-Safe Telemetry",
                        description: "Emit counts/latency/availability metrics.",
                        enabled: true, requiredRole: "any",
                        createdAt: Date(), updatedAt: Date()),
        ]
        for flag in defaultFlags { register(flag) }
    }

    private func persist() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(Array(flags.values)) {
            defaults.set(data, forKey: Self.persistenceKey)
        }
    }

    private func loadFlags() {
        guard let data = defaults.data(forKey: Self.persistenceKey) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        if let loaded = try? decoder.decode([FeatureFlag].self, from: data) {
            for flag in loaded { flags[flag.id] = flag }
        }
    }
}
