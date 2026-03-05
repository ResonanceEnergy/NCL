// CouncilRunnerTests.swift — NCL iOS Companion
// Tests for parallel agent execution, consensus/dissent, and transcript generation.

import XCTest
@testable import CompanionApp

// MARK: - Mock Agents

private final class MockAgent: CouncilAgent {
    let role: String
    let recommendation: String
    let confidence: Double
    let flags: [String]

    init(role: String, recommendation: String = "ok", confidence: Double = 0.9, flags: [String] = []) {
        self.role = role
        self.recommendation = recommendation
        self.confidence = confidence
        self.flags = flags
    }

    func evaluate(input: CouncilInput) -> AgentOutput {
        AgentOutput(
            agentRole: role,
            recommendation: recommendation,
            confidence: confidence,
            reasoning: ["mock reasoning for \(role)"],
            flags: flags,
            timestamp: Date()
        )
    }
}

final class CouncilRunnerTests: XCTestCase {

    // MARK: - Helpers

    private func makeInput(missionID: String = "M-001",
                            missionType: String = "NORMAL",
                            dataCount: Int = 5,
                            provenance: [String] = ["src-1"]) -> CouncilInput {
        var data: [String: Any] = [:]
        for i in 0..<dataCount { data["key\(i)"] = "val\(i)" }
        return CouncilInput(
            missionID: missionID,
            missionType: missionType,
            data: data,
            provenanceChain: provenance
        )
    }

    // MARK: - Default Agents

    func testDefaultRunnerHasThreeAgents() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput())
        XCTAssertEqual(transcript.agents.count, 3)
    }

    func testDefaultAgentRoles() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput())
        let roles = Set(transcript.agents.map { $0.agentRole })
        XCTAssertTrue(roles.contains("planner"))
        XCTAssertTrue(roles.contains("skeptic"))
        XCTAssertTrue(roles.contains("risk"))
    }

    func testTranscriptSortedByRole() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput())
        let roles = transcript.agents.map { $0.agentRole }
        XCTAssertEqual(roles, roles.sorted())
    }

    // MARK: - Consensus Path (no blocking flags)

    func testCleanDataYieldsConsensus() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(dataCount: 5, provenance: ["src"]))
        XCTAssertEqual(transcript.consensus, "proceed")
        XCTAssertTrue(transcript.dissent.isEmpty)
        XCTAssertEqual(transcript.finalRecommendation, "proceed_with_plan")
    }

    // MARK: - Dissent Path (blocking flags)

    func testInsufficientDataCausesDissent() {
        let runner = CouncilRunner()
        // Fewer than 3 data points triggers SkepticAgent's "data_insufficient"
        let transcript = runner.run(input: makeInput(dataCount: 2))
        XCTAssertNil(transcript.consensus)
        XCTAssertFalse(transcript.dissent.isEmpty)
        XCTAssertEqual(transcript.finalRecommendation, "hold_for_review")
    }

    func testMissingProvenanceCausesDissent() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(provenance: []))
        XCTAssertNil(transcript.consensus)
        XCTAssertEqual(transcript.finalRecommendation, "hold_for_review")
    }

    // MARK: - Custom Agents

    func testCustomAgentsUsed() {
        let agents: [CouncilAgent] = [
            MockAgent(role: "alpha"),
            MockAgent(role: "beta"),
        ]
        let runner = CouncilRunner(agents: agents)
        let transcript = runner.run(input: makeInput())
        XCTAssertEqual(transcript.agents.count, 2)
        let roles = transcript.agents.map { $0.agentRole }
        XCTAssertTrue(roles.contains("alpha"))
        XCTAssertTrue(roles.contains("beta"))
    }

    func testCustomAgentWithBlockingFlag() {
        let agents: [CouncilAgent] = [
            MockAgent(role: "strict", flags: ["data_insufficient"]),
        ]
        let runner = CouncilRunner(agents: agents)
        let transcript = runner.run(input: makeInput())
        XCTAssertNil(transcript.consensus)
        XCTAssertEqual(transcript.finalRecommendation, "hold_for_review")
    }

    func testCustomAgentsNoFlags() {
        let agents: [CouncilAgent] = [
            MockAgent(role: "a", recommendation: "go"),
            MockAgent(role: "b", recommendation: "go"),
        ]
        let runner = CouncilRunner(agents: agents)
        let transcript = runner.run(input: makeInput())
        XCTAssertEqual(transcript.consensus, "proceed")
        XCTAssertTrue(transcript.dissent.isEmpty)
    }

    // MARK: - Transcript Fields

    func testTranscriptMissionID() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(missionID: "ALPHA-7"))
        XCTAssertEqual(transcript.missionID, "ALPHA-7")
    }

    func testTranscriptProvenanceLinks() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(provenance: ["ev-1", "ev-2"]))
        XCTAssertEqual(transcript.provenanceLinks, ["ev-1", "ev-2"])
    }

    func testTranscriptCreatedAtIsRecent() {
        let runner = CouncilRunner()
        let before = Date()
        let transcript = runner.run(input: makeInput())
        let after = Date()
        XCTAssertTrue(transcript.createdAt >= before)
        XCTAssertTrue(transcript.createdAt <= after)
    }

    // MARK: - Risk Agent Flags

    func testRiskAgentFlagsOverloadMission() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(missionType: "OVERLOAD_ALERT"))
        let risk = transcript.agents.first { $0.agentRole == "risk" }
        XCTAssertTrue(risk?.flags.contains("elevated_risk_mission") ?? false)
    }

    func testRiskAgentFlagsDriftMission() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(missionType: "drift_detection"))
        let risk = transcript.agents.first { $0.agentRole == "risk" }
        XCTAssertTrue(risk?.flags.contains("elevated_risk_mission") ?? false)
    }

    func testRiskAgentNoFlagsNormalMission() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(missionType: "NORMAL"))
        let risk = transcript.agents.first { $0.agentRole == "risk" }
        XCTAssertTrue(risk?.flags.isEmpty ?? false)
    }

    // MARK: - Skeptic Agent

    func testSkepticLowersConfidenceOnSparseData() {
        let runner = CouncilRunner()
        let transcript = runner.run(input: makeInput(dataCount: 1))
        let skeptic = transcript.agents.first { $0.agentRole == "skeptic" }
        XCTAssertNotNil(skeptic)
        XCTAssertLessThan(skeptic!.confidence, 0.8)
    }

    // MARK: - Audit Ledger Integration

    func testCouncilRunCreatesAuditEntry() {
        let ledger = AuditLedger(
            directory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            signingKey: nil
        )
        let runner = CouncilRunner(auditLedger: ledger)
        _ = runner.run(input: makeInput(missionID: "AUDIT-TEST"))
        XCTAssertEqual(ledger.count, 1)
        XCTAssertTrue(ledger.entries.first?.id.hasPrefix("council-AUDIT-TEST") ?? false)
    }

    // MARK: - Codable Types

    func testAgentOutputCodable() throws {
        let output = AgentOutput(
            agentRole: "test", recommendation: "ok",
            confidence: 0.5, reasoning: ["r1"],
            flags: ["f1"], timestamp: Date()
        )
        let data = try JSONEncoder().encode(output)
        let decoded = try JSONDecoder().decode(AgentOutput.self, from: data)
        XCTAssertEqual(decoded.agentRole, "test")
        XCTAssertEqual(decoded.confidence, 0.5)
    }

    func testCouncilTranscriptCodable() throws {
        let transcript = CouncilTranscript(
            missionID: "M-1",
            agents: [],
            consensus: "proceed",
            dissent: [],
            finalRecommendation: "go",
            provenanceLinks: ["p1"],
            createdAt: Date()
        )
        let data = try JSONEncoder().encode(transcript)
        let decoded = try JSONDecoder().decode(CouncilTranscript.self, from: data)
        XCTAssertEqual(decoded.missionID, "M-1")
        XCTAssertEqual(decoded.consensus, "proceed")
    }

    // MARK: - Determinism

    func testMultipleRunsSameOutputRoles() {
        let runner = CouncilRunner()
        let input = makeInput()
        let t1 = runner.run(input: input)
        let t2 = runner.run(input: input)
        XCTAssertEqual(t1.agents.map { $0.agentRole }, t2.agents.map { $0.agentRole })
    }
}
