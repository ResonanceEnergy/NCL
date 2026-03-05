// SystemMode.swift — NCL iOS Companion
// NORMAL / SUGGEST_ONLY / LOCKDOWN with metrics-driven auto-downgrade.

import Foundation

// MARK: - SystemMode

final class SystemMode: ObservableObject {

    @Published private(set) var current: SystemModeState = .normal
    @Published private(set) var lastTransition: Date = Date()
    @Published private(set) var transitionReason: String = "initialization"

    private let defaults: UserDefaults
    private let auditLedger: AuditLedger?
    private static let persistenceKey = "ncl.system_mode"

    // Metrics thresholds for auto-downgrade
    struct Thresholds {
        var errorRateForSuggestOnly: Double = 0.10   // 10% error rate
        var errorRateForLockdown: Double = 0.25       // 25% error rate
        var latencyP99ForSuggestOnly: Double = 5000   // 5 seconds
        var consecutiveFailuresForLockdown: Int = 5
    }

    var thresholds = Thresholds()
    private var consecutiveFailures: Int = 0
    private var recentErrorRate: Double = 0.0

    init(defaults: UserDefaults = .standard, auditLedger: AuditLedger? = nil) {
        self.defaults = defaults
        self.auditLedger = auditLedger

        // Restore persisted mode
        if let raw = defaults.string(forKey: Self.persistenceKey),
           let mode = SystemModeState(rawValue: raw) {
            self.current = mode
        }
    }

    // MARK: - Public API

    /// Manually set mode (AZ_PRIME only for upgrade, anyone can downgrade).
    @discardableResult
    func setMode(_ newMode: SystemModeState, by userRole: String, reason: String) -> Bool {
        // Only AZ_PRIME can upgrade mode
        let isUpgrade = newMode.sortOrder > current.sortOrder
        if isUpgrade && userRole != "AZ_PRIME" { return false }

        let oldMode = current
        current = newMode
        lastTransition = Date()
        transitionReason = reason

        defaults.set(newMode.rawValue, forKey: Self.persistenceKey)

        auditLedger?.append(entry: AuditEntry(
            id: "mode-\(Int(Date().timeIntervalSince1970))",
            actionID: "system_mode",
            tier: "system",
            category: "system_mode.transition",
            verdict: "executed",
            reason: "\(oldMode.rawValue) → \(newMode.rawValue): \(reason)",
            timestamp: Date(),
            provenanceChain: []
        ))

        return true
    }

    /// Report a success — resets failure counter.
    func reportSuccess() {
        consecutiveFailures = 0
    }

    /// Report a failure — may trigger auto-downgrade.
    func reportFailure() {
        consecutiveFailures += 1
        evaluateAutoDowngrade()
    }

    /// Update error rate from recent telemetry (called periodically).
    func updateErrorRate(_ rate: Double) {
        recentErrorRate = rate
        evaluateAutoDowngrade()
    }

    // MARK: - Private

    private func evaluateAutoDowngrade() {
        switch current {
        case .normal:
            if consecutiveFailures >= thresholds.consecutiveFailuresForLockdown {
                setMode(.lockdown, by: "system", reason: "auto_downgrade: \(consecutiveFailures) consecutive failures")
            } else if recentErrorRate >= thresholds.errorRateForSuggestOnly {
                setMode(.suggestOnly, by: "system", reason: "auto_downgrade: error rate \(recentErrorRate)")
            }

        case .suggestOnly:
            if consecutiveFailures >= thresholds.consecutiveFailuresForLockdown ||
               recentErrorRate >= thresholds.errorRateForLockdown {
                setMode(.lockdown, by: "system", reason: "auto_downgrade: critical error threshold")
            }

        case .lockdown:
            break // Cannot auto-recover from lockdown
        }
    }
}

// MARK: - SystemModeState extension

extension SystemModeState {
    var sortOrder: Int {
        switch self {
        case .normal:      return 2
        case .suggestOnly: return 1
        case .lockdown:    return 0
        }
    }
}
