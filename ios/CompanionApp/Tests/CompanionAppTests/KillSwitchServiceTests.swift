// KillSwitchServiceTests.swift — NCL iOS Companion
// Tests for persistent kill-switch with AZ_PRIME gating.

import XCTest
@testable import CompanionApp

final class KillSwitchServiceTests: XCTestCase {

    // MARK: - Helpers

    private func makeSUT(engaged: Bool = false) -> (KillSwitchService, UserDefaults) {
        let defaults = UserDefaults(suiteName: "test.killswitch.\(UUID().uuidString)")!
        if engaged {
            defaults.set(true, forKey: "ncl.killswitch.engaged")
            defaults.set(Date(), forKey: "ncl.killswitch.engaged_at")
            defaults.set("setup", forKey: "ncl.killswitch.engaged_by")
        }
        let sut = KillSwitchService(defaults: defaults)
        return (sut, defaults)
    }

    // MARK: - Initial State

    func testDefaultStateDisengaged() {
        let (sut, _) = makeSUT()
        XCTAssertFalse(sut.isEngaged)
        XCTAssertNil(sut.engagedAt)
        XCTAssertNil(sut.engagedBy)
    }

    // MARK: - Engage

    func testEngageSetsState() {
        let (sut, _) = makeSUT()
        let result = sut.engage(by: "operator")
        XCTAssertTrue(result)
        XCTAssertTrue(sut.isEngaged)
        XCTAssertEqual(sut.engagedBy, "operator")
        XCTAssertNotNil(sut.engagedAt)
    }

    func testEngageWhenAlreadyEngagedReturnsFalse() {
        let (sut, _) = makeSUT(engaged: true)
        let result = sut.engage(by: "operator")
        XCTAssertFalse(result)
    }

    func testAnyRoleCanEngage() {
        for role in ["AZ_PRIME", "operator", "guest", "unknown", "robot"] {
            let (sut, _) = makeSUT()
            XCTAssertTrue(sut.engage(by: role), "Role '\(role)' should be able to engage")
        }
    }

    // MARK: - Disengage

    func testDisengageRequiresAZPrime() {
        let (sut, _) = makeSUT(engaged: true)
        let result = sut.disengage(by: "operator")
        XCTAssertFalse(result)
        XCTAssertTrue(sut.isEngaged, "Non-AZ_PRIME should not be able to disengage")
    }

    func testDisengageByAZPrimeSucceeds() {
        let (sut, _) = makeSUT(engaged: true)
        let result = sut.disengage(by: "AZ_PRIME")
        XCTAssertTrue(result)
        XCTAssertFalse(sut.isEngaged)
        XCTAssertNil(sut.engagedAt)
        XCTAssertNil(sut.engagedBy)
    }

    func testDisengageWhenNotEngagedReturnsFalse() {
        let (sut, _) = makeSUT()
        let result = sut.disengage(by: "AZ_PRIME")
        XCTAssertFalse(result)
    }

    func testDisengageClearsMetadata() {
        let (sut, _) = makeSUT(engaged: true)
        _ = sut.disengage(by: "AZ_PRIME")
        XCTAssertNil(sut.engagedAt)
        XCTAssertNil(sut.engagedBy)
    }

    // MARK: - Persistence

    func testStatePersistsAcrossInstances() {
        let suiteName = "test.persistence.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!

        let sut1 = KillSwitchService(defaults: defaults)
        _ = sut1.engage(by: "AZ_PRIME")
        XCTAssertTrue(sut1.isEngaged)

        // Create second instance with same UserDefaults — should read persisted state
        let sut2 = KillSwitchService(defaults: defaults)
        XCTAssertTrue(sut2.isEngaged)
        XCTAssertEqual(sut2.engagedBy, "AZ_PRIME")
    }

    // MARK: - Status

    func testStatusWhenDisengaged() {
        let (sut, _) = makeSUT()
        let s = sut.status()
        XCTAssertEqual(s["engaged"] as? Bool, false)
        XCTAssertEqual(s["engaged_at"] as? String, "n/a")
        XCTAssertEqual(s["engaged_by"] as? String, "n/a")
    }

    func testStatusWhenEngaged() {
        let (sut, _) = makeSUT()
        _ = sut.engage(by: "operator")
        let s = sut.status()
        XCTAssertEqual(s["engaged"] as? Bool, true)
        XCTAssertNotEqual(s["engaged_at"] as? String, "n/a")
        XCTAssertEqual(s["engaged_by"] as? String, "operator")
    }

    // MARK: - Drill

    func testDrillCycle() {
        let (sut, _) = makeSUT()
        let drill = sut.runDrill(by: "AZ_PRIME")
        XCTAssertTrue(drill.engageOK, "Drill engage should succeed")
        XCTAssertTrue(drill.wasEngaged, "Switch should be engaged during drill")
        XCTAssertTrue(drill.disengageOK, "AZ_PRIME should be able to disengage")
        XCTAssertFalse(sut.isEngaged, "Switch should be disengaged after drill")
    }

    func testDrillNonAZPrimeCannotDisengage() {
        let (sut, _) = makeSUT()
        let drill = sut.runDrill(by: "operator")
        XCTAssertTrue(drill.engageOK)
        XCTAssertTrue(drill.wasEngaged)
        XCTAssertFalse(drill.disengageOK, "Non-AZ_PRIME should fail disengage")
        XCTAssertTrue(sut.isEngaged, "Switch should remain engaged")
    }

    func testDrillAlreadyEngagedReturnsFalseForEngage() {
        let (sut, _) = makeSUT(engaged: true)
        let drill = sut.runDrill(by: "AZ_PRIME")
        XCTAssertFalse(drill.engageOK, "Already engaged — engage should fail")
        XCTAssertTrue(drill.wasEngaged)
        XCTAssertTrue(drill.disengageOK)
    }

    // MARK: - Audit Trail Integration

    func testEngageCreatesAuditEntry() {
        let ledger = AuditLedger(
            directory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            signingKey: nil
        )
        let defaults = UserDefaults(suiteName: "test.audit.\(UUID().uuidString)")!
        let sut = KillSwitchService(defaults: defaults, auditLedger: ledger)
        _ = sut.engage(by: "operator")
        XCTAssertEqual(ledger.count, 1)
        XCTAssertEqual(ledger.entries.first?.category, "killswitch.engage")
    }

    func testDisengageCreatesAuditEntry() {
        let ledger = AuditLedger(
            directory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString),
            signingKey: nil
        )
        let defaults = UserDefaults(suiteName: "test.audit2.\(UUID().uuidString)")!
        let sut = KillSwitchService(defaults: defaults, auditLedger: ledger)
        _ = sut.engage(by: "operator")
        _ = sut.disengage(by: "AZ_PRIME")
        XCTAssertEqual(ledger.count, 2)
        XCTAssertEqual(ledger.entries.last?.category, "killswitch.disengage")
    }
}
