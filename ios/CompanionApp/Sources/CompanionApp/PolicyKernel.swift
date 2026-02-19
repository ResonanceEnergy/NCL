// PolicyKernel.swift — minimal pseudocode starter
// Purpose: single pure-authority module for authorizing Actions before execution.

import Foundation

public enum ActionTier: String {
    case suggest, draft, execute
}

public struct Action {
    public let id: String
    public let type: String
    public let tier: ActionTier
    public let riskTier: Int
    public let provenanceLinks: [String]
    public let sensitivity: String? // e.g. "neural_data"
    public let modality: String? // e.g. "keyboard", "shortcut", "neural_intent_signal"
    // payload omitted for brevity
}

public struct PolicyDecision {
    public let allow: Bool
    public let reasonCode: String
    public let requiredSteps: [String]
    public let enforcedTier: ActionTier?
}

public final class PolicyKernel {
    // MARK: - Invariants (implement strictly)
    // 1) Kill switch blocks Execute
    // 2) Execute requires provenance_links.length > 0
    // 3) Default deny for unknown actions
    // 4) RiskTier >= 2 requires Council
    // 5) Neural modality hard-off by default

    private let killSwitchService: KillSwitchServiceProtocol
    private let modalityRegistry: ModalityRegistryProtocol

    public init(killSwitch: KillSwitchServiceProtocol, modalityRegistry: ModalityRegistryProtocol) {
        self.killSwitchService = killSwitch
        self.modalityRegistry = modalityRegistry
    }

    // Primary API used by ActionRouter
    public func authorize(action: Action, context: [String:Any]) -> PolicyDecision {
        // Kill switch check
        if killSwitchService.isEngaged() && action.tier == .execute {
            return PolicyDecision(allow: false, reasonCode: "KILL_SWITCH_ENGAGED", requiredSteps: [], enforcedTier: nil)
        }

        // Default deny for unknown action types (action.type must be registered)
        guard isActionTypeRegistered(action.type) else {
            return PolicyDecision(allow: false, reasonCode: "UNKNOWN_ACTION_TYPE", requiredSteps: [], enforcedTier: nil)
        }

        // Provenance rule
        if action.tier == .execute && action.provenanceLinks.isEmpty {
            return PolicyDecision(allow: false, reasonCode: "NO_PROVENANCE", requiredSteps: ["ADD_PROVENANCE"], enforcedTier: .draft)
        }

        // Neuro hard boundary
        if let modality = action.modality, modality == "neural_intent_signal" {
            // ingestion hard-off by default
            return PolicyDecision(allow: false, reasonCode: "NEURO_HARD_OFF", requiredSteps: ["AZ_PRIME_APPROVAL"], enforcedTier: .draft)
        }

        // Risk tier -> council requirement
        if action.riskTier >= 2 {
            return PolicyDecision(allow: false, reasonCode: "COUNCIL_REQUIRED", requiredSteps: ["RUN_COUNCIL"], enforcedTier: .draft)
        }

        // Sensitive flows require consent receipt
        if let sensitivity = action.sensitivity, isSensitive(sensitivity) {
            let hasConsent = checkConsentForAction(action)
            if !hasConsent {
                return PolicyDecision(allow: false, reasonCode: "CONSENT_REQUIRED", requiredSteps: ["OBTAIN_CONSENT"], enforcedTier: .draft)
            }
        }

        // Allow Suggest / Draft flows if listed
        if action.tier == .suggest || action.tier == .draft {
            return PolicyDecision(allow: true, reasonCode: "ALLOWED", requiredSteps: [], enforcedTier: action.tier)
        }

        // Execute: final checks passed => allow
        if action.tier == .execute {
            return PolicyDecision(allow: true, reasonCode: "ALLOWED", requiredSteps: [], enforcedTier: .execute)
        }

        // Fallback deny
        return PolicyDecision(allow: false, reasonCode: "UNKNOWN_DENY", requiredSteps: [], enforcedTier: nil)
    }

    // ------ Helpers (stubs to be implemented) ------
    private func isActionTypeRegistered(_ type: String) -> Bool {
        // TODO: check allowlist stored in config or FeatureFlags
        return true // permit for starter; replace with real check
    }

    private func isSensitive(_ sensitivity: String) -> Bool {
        return ["sensitive","financial","health","neural_data"].contains(sensitivity)
    }

    private func checkConsentForAction(_ action: Action) -> Bool {
        // TODO: consult ConsentReceiptService
        return false
    }
}

// Protocol stubs used by PolicyKernel (implement in separate files)
public protocol KillSwitchServiceProtocol {
    func isEngaged() -> Bool
}

public protocol ModalityRegistryProtocol {
    func isAllowed(modality: String, forTier: ActionTier) -> Bool
}
