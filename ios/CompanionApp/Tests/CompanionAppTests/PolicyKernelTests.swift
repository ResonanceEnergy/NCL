// PolicyKernelTests.swift — NCL iOS Companion
// Comprehensive tests for the 6-step authorization chain in PolicyKernel.

import XCTest
@testable import CompanionApp

final class PolicyKernelTests: XCTestCase {

    // MARK: - Helpers

    private func makeKernel(engaged: Bool = false) -> (PolicyKernel, KillSwitchService) {
        let defaults = UserDefaults(suiteName: "test.policykernel.\(UUID().uuidString)")!
        defaults.set(engaged, forKey: "ncl.killswitch.engaged")
        let ks = KillSwitchService(defaults: defaults)
        let pk = PolicyKernel(killSwitch: ks)
        return (pk, ks)
    }

    private func normalContext(role: String = "AZ_PRIME") -> AuthorizationContext {
        AuthorizationContext(userRole: role, systemMode: .normal, killSwitchEngaged: false)
    }

    private func suggestOnlyContext() -> AuthorizationContext {
        AuthorizationContext(userRole: "operator", systemMode: .suggestOnly, killSwitchEngaged: false)
    }

    private func lockdownContext() -> AuthorizationContext {
        AuthorizationContext(userRole: "AZ_PRIME", systemMode: .lockdown, killSwitchEngaged: false)
    }

    private func safeAction(tier: ActionTier = .suggest,
                            category: String = "note.create",
                            sensitivity: String = "P3",
                            consent: String? = nil,
                            provenance: [String] = ["src-1"]) -> ActionRequest {
        ActionRequest(
            id: UUID().uuidString,
            tier: tier,
            category: category,
            provenanceChain: provenance,
            sensitivityLevel: sensitivity,
            consentReceiptID: consent,
            metadata: [:]
        )
    }

    // MARK: - Step 1: Kill Switch

    func testKillSwitchBlocksAllActions() {
        let (pk, _) = makeKernel(engaged: true)
        let action = safeAction(tier: .execute)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "kill_switch_engaged")
    }

    func testKillSwitchBlocksSuggestToo() {
        let (pk, _) = makeKernel(engaged: true)
        let action = safeAction(tier: .suggest)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "kill_switch_engaged")
    }

    func testKillSwitchDisengagedAllowsThrough() {
        let (pk, _) = makeKernel(engaged: false)
        let action = safeAction(tier: .suggest)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    // MARK: - Step 2: System Mode

    func testLockdownDeniesAll() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest)
        let decision = pk.authorize(action: action, context: lockdownContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "system_lockdown")
    }

    func testSuggestOnlyAllowsSuggest() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest)
        let decision = pk.authorize(action: action, context: suggestOnlyContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    func testSuggestOnlyBlocksDraft() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .draft)
        let decision = pk.authorize(action: action, context: suggestOnlyContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "suggest_only_mode")
    }

    func testSuggestOnlyBlocksExecute() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .execute)
        let decision = pk.authorize(action: action, context: suggestOnlyContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "suggest_only_mode")
    }

    func testNormalModeAllowsAll() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .draft)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    // MARK: - Step 3: Provenance

    func testExecuteWithoutProvenanceDenied() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .execute, provenance: [])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "no_provenance")
    }

    func testDraftWithoutProvenanceAllowed() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .draft, provenance: [])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    func testExecuteWithProvenancePasses() {
        let (pk, _) = makeKernel()
        // Use a non-sensitive, non-high-risk category so it reaches step 6
        let action = safeAction(tier: .execute, category: "note.create", sensitivity: "P3", provenance: ["ev-1"])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    // MARK: - Step 4: Consent

    func testSensitiveCategoryWithoutConsentDenied() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "health.data", consent: nil)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "missing_consent_receipt")
    }

    func testSensitiveCategoryWithConsentAllowed() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "health.data", consent: "CR-001")
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    func testNonSensitiveCategoryNoConsentAllowed() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "note.create", consent: nil)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    func testMessageSendSensitive() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "message.send", consent: nil)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "missing_consent_receipt")
    }

    func testLocationShareSensitive() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "location.share", consent: nil)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "missing_consent_receipt")
    }

    // MARK: - Step 5: High-Risk Council

    func testHighRiskExecuteNeedsCouncil() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .execute, category: "file.delete", sensitivity: "P2", consent: nil, provenance: ["ev-1"])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .needsCouncil)
        XCTAssertEqual(decision.reason, "high_risk_requires_council")
    }

    func testP0SensitivityExecuteNeedsCouncil() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .execute, category: "note.create", sensitivity: "P0", provenance: ["ev-1"])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .needsCouncil)
        XCTAssertEqual(decision.reason, "high_risk_requires_council")
    }

    func testP1SensitivityExecuteNeedsCouncil() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .execute, category: "note.create", sensitivity: "P1", provenance: ["ev-1"])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .needsCouncil)
        XCTAssertEqual(decision.reason, "high_risk_requires_council")
    }

    func testSuggestHighRiskCategoryAllowed() {
        // High-risk gating only applies to execute tier
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "purchase.confirm", consent: nil, provenance: [])
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
    }

    // MARK: - Step 6: Default Allow

    func testSafeActionAllowed() {
        let (pk, _) = makeKernel()
        let action = safeAction(tier: .suggest, category: "note.create", sensitivity: "P3")
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .allow)
        XCTAssertEqual(decision.reason, "policy_passed")
    }

    // MARK: - AuditRef Format

    func testAuditRefContainsActionID() {
        let (pk, _) = makeKernel()
        let action = safeAction()
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertTrue(decision.auditRef.hasPrefix("audit-"))
        XCTAssertTrue(decision.auditRef.contains(action.id))
    }

    // MARK: - ActionTier Comparable

    func testActionTierOrdering() {
        XCTAssertTrue(ActionTier.suggest < ActionTier.draft)
        XCTAssertTrue(ActionTier.draft < ActionTier.execute)
        XCTAssertFalse(ActionTier.execute < ActionTier.suggest)
    }

    // MARK: - Priority: Kill Switch > System Mode

    func testKillSwitchTakesPriorityOverLockdown() {
        let (pk, _) = makeKernel(engaged: true)
        let action = safeAction()
        let decision = pk.authorize(action: action, context: lockdownContext())
        // Kill switch checked first (step 1) → reason is kill_switch, not lockdown
        XCTAssertEqual(decision.reason, "kill_switch_engaged")
    }

    // MARK: - Edge Cases

    func testCustomSensitiveCategoriesRespected() {
        let defaults = UserDefaults(suiteName: "test.custom.\(UUID().uuidString)")!
        let ks = KillSwitchService(defaults: defaults)
        let pk = PolicyKernel(killSwitch: ks, sensitiveCategories: ["custom.action"])
        let action = safeAction(category: "custom.action", consent: nil)
        let decision = pk.authorize(action: action, context: normalContext())
        XCTAssertEqual(decision.verdict, .deny)
        XCTAssertEqual(decision.reason, "missing_consent_receipt")
    }

    func testSystemModeStateCodable() throws {
        let data = try JSONEncoder().encode(SystemModeState.normal)
        let decoded = try JSONDecoder().decode(SystemModeState.self, from: data)
        XCTAssertEqual(decoded, .normal)
    }

    func testPolicyDecisionCodable() throws {
        let pd = PolicyDecision(verdict: .allow, reason: "test", auditRef: "ref-1", timestamp: Date())
        let data = try JSONEncoder().encode(pd)
        let decoded = try JSONDecoder().decode(PolicyDecision.self, from: data)
        XCTAssertEqual(decoded.verdict, .allow)
        XCTAssertEqual(decoded.reason, "test")
    }
}
