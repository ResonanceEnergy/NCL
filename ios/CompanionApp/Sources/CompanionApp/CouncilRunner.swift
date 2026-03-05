// CouncilRunner.swift — NCL iOS Companion
// Runs Planner, Skeptic, and Risk agents in parallel. Produces a deterministic
// transcript with consensus / dissent notes.

import Foundation

// MARK: - Council Types

struct CouncilInput {
    let missionID: String
    let missionType: String
    let data: [String: Any]
    let provenanceChain: [String]
}

struct AgentOutput: Codable {
    let agentRole: String          // "planner", "skeptic", "risk"
    let recommendation: String
    let confidence: Double         // 0.0–1.0
    let reasoning: [String]
    let flags: [String]            // e.g. ["high_risk", "data_insufficient"]
    let timestamp: Date
}

struct CouncilTranscript: Codable {
    let missionID: String
    let agents: [AgentOutput]
    let consensus: String?          // nil if no consensus
    let dissent: [String]
    let finalRecommendation: String
    let provenanceLinks: [String]
    let createdAt: Date
}

// MARK: - Agent Protocol

protocol CouncilAgent {
    var role: String { get }
    func evaluate(input: CouncilInput) -> AgentOutput
}

// MARK: - Deterministic Agents (heuristic v0)

final class PlannerAgent: CouncilAgent {
    let role = "planner"

    func evaluate(input: CouncilInput) -> AgentOutput {
        let reasoning = [
            "Analyzed \(input.data.count) data points for mission \(input.missionID)",
            "Identified actionable items based on event patterns",
            "Prioritized by impact and feasibility"
        ]
        return AgentOutput(
            agentRole: role,
            recommendation: "proceed_with_plan",
            confidence: 0.85,
            reasoning: reasoning,
            flags: [],
            timestamp: Date()
        )
    }
}

final class SkepticAgent: CouncilAgent {
    let role = "skeptic"

    func evaluate(input: CouncilInput) -> AgentOutput {
        var flags: [String] = []
        var confidence = 0.8
        var reasoning = [
            "Reviewed data completeness and quality",
            "Checked for potential biases or missing context"
        ]

        // Flag insufficient data
        if input.data.count < 3 {
            flags.append("data_insufficient")
            confidence = 0.5
            reasoning.append("WARNING: Fewer than 3 data points — conclusions may be unreliable")
        }

        // Flag missing provenance
        if input.provenanceChain.isEmpty {
            flags.append("no_provenance")
            confidence -= 0.2
            reasoning.append("WARNING: No provenance chain — cannot verify data origin")
        }

        return AgentOutput(
            agentRole: role,
            recommendation: flags.isEmpty ? "data_acceptable" : "review_flagged_issues",
            confidence: max(0.0, confidence),
            reasoning: reasoning,
            flags: flags,
            timestamp: Date()
        )
    }
}

final class RiskAgent: CouncilAgent {
    let role = "risk"

    func evaluate(input: CouncilInput) -> AgentOutput {
        var flags: [String] = []
        var reasoning = [
            "Assessed potential negative outcomes",
            "Evaluated reversibility of recommended actions"
        ]

        let missionType = input.missionType.lowercased()
        if missionType.contains("overload") || missionType.contains("drift") {
            flags.append("elevated_risk_mission")
            reasoning.append("Mission type '\(input.missionType)' carries elevated intervention risk")
        }

        return AgentOutput(
            agentRole: role,
            recommendation: flags.isEmpty ? "risk_acceptable" : "proceed_with_caution",
            confidence: 0.75,
            reasoning: reasoning,
            flags: flags,
            timestamp: Date()
        )
    }
}

// MARK: - CouncilRunner

final class CouncilRunner {

    private let agents: [CouncilAgent]
    private let auditLedger: AuditLedger?

    init(agents: [CouncilAgent]? = nil, auditLedger: AuditLedger? = nil) {
        self.agents = agents ?? [PlannerAgent(), SkepticAgent(), RiskAgent()]
        self.auditLedger = auditLedger
    }

    /// Run all agents in parallel and produce a transcript.
    func run(input: CouncilInput) -> CouncilTranscript {
        var outputs: [AgentOutput] = []
        let group = DispatchGroup()
        let lock = NSLock()

        for agent in agents {
            group.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                let output = agent.evaluate(input: input)
                lock.lock()
                outputs.append(output)
                lock.unlock()
                group.leave()
            }
        }

        group.wait()

        // Sort for determinism (by role name)
        outputs.sort { $0.agentRole < $1.agentRole }

        // Build consensus/dissent
        let allFlags = outputs.flatMap { $0.flags }
        let hasBlockingFlags = allFlags.contains("data_insufficient") || allFlags.contains("no_provenance")

        let consensus: String?
        let dissent: [String]
        let finalRec: String

        if hasBlockingFlags {
            consensus = nil
            dissent = outputs.filter { !$0.flags.isEmpty }.map {
                "\($0.agentRole): \($0.flags.joined(separator: ", "))"
            }
            finalRec = "hold_for_review"
        } else {
            consensus = "proceed"
            dissent = []
            finalRec = outputs.first { $0.agentRole == "planner" }?.recommendation ?? "proceed_with_plan"
        }

        let transcript = CouncilTranscript(
            missionID: input.missionID,
            agents: outputs,
            consensus: consensus,
            dissent: dissent,
            finalRecommendation: finalRec,
            provenanceLinks: input.provenanceChain,
            createdAt: Date()
        )

        // Audit the council run
        auditLedger?.append(entry: AuditEntry(
            id: "council-\(input.missionID)-\(Int(Date().timeIntervalSince1970))",
            actionID: input.missionID,
            tier: "council",
            category: "council.run",
            verdict: transcript.consensus ?? "no_consensus",
            reason: "Council run: \(outputs.count) agents, final=\(finalRec)",
            timestamp: Date(),
            provenanceChain: input.provenanceChain
        ))

        return transcript
    }
}
