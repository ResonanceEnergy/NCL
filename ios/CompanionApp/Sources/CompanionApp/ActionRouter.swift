// ActionRouter.swift — single execution entry point (starter pseudocode)
// Responsibilities:
//  - Accept Action objects
//  - Call PolicyKernel.authorize()
//  - Log to AuditLedger / IncidentLedger
//  - Execute safe side effects (local only)

import Foundation

public enum ActionResult {
    case success(details: [String:Any])
    case denied(reason: String)
    case error(message: String)
}

public final class ActionRouter {
    private let policyKernel: PolicyKernel
    private let auditLedger: AuditLedgerProtocol
    private let incidentLedger: IncidentLedgerProtocol

    public init(policyKernel: PolicyKernel, audit: AuditLedgerProtocol, incident: IncidentLedgerProtocol) {
        self.policyKernel = policyKernel
        self.auditLedger = audit
        self.incidentLedger = incident
    }

    // Single execution entry: all side effects must go through here
    public func execute(action: Action, context: [String:Any] = [:]) -> ActionResult {
        // 1) Ask PolicyKernel
        let decision = policyKernel.authorize(action: action, context: context)

        // 2) Write audit record for decision
        auditLedger.append(record: ["action_id": action.id, "decision": decision.reasonCode, "allow": decision.allow])

        // 3) Deny -> emit incident and return
        if !decision.allow {
            incidentLedger.append(incident: ["action_id": action.id, "reason": decision.reasonCode])
            return .denied(reason: decision.reasonCode)
        }

        // 4) Perform the effect (local-only)
        do {
            // TODO: dispatch to concrete action handlers (e.g., reminderSet, calendarAdd)
            let result = try performSideEffect(action: action)
            auditLedger.append(record: ["action_id": action.id, "status": "executed"])
            return .success(details: result)
        } catch {
            incidentLedger.append(incident: ["action_id": action.id, "error": "execution_failed"])
            return .error(message: "execution_failed")
        }
    }

    private func performSideEffect(action: Action) throws -> [String:Any] {
        // NOTE: keep all side effects local-only and small. Examples:
        // - write a local reminder
        // - create a local event in the EventStore
        // - modify a local tag
        // Do NOT call external networks here unless explicitly allowed by PolicyKernel and user consent.

        // TODO: route action.type -> handler
        // Example stub:
        switch action.type {
        case "ncl.action.create_reminder":
            // write to EventStore + schedule local notification
            return ["status": "reminder_created"]
        default:
            throw NSError(domain: "ActionRouter", code: 1, userInfo: [NSLocalizedDescriptionKey: "handler_not_implemented"])
        }
    }
}

// Protocol stubs
public protocol AuditLedgerProtocol {
    func append(record: [String:Any])
}

public protocol IncidentLedgerProtocol {
    func append(incident: [String:Any])
}
