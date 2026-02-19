import XCTest
@testable import CompanionApp

final class KillSwitchAuditTests: XCTestCase {

    func testKillSwitchBlocksAuthorizeExecute() {
        let kill = LocalKillSwitchService(suiteName: "test.ncl.killswitch")
        // ensure clean
        kill.clear()

        // create PolicyKernel with kill switch
        let modality = StubModalityRegistry()
        let kernel = PolicyKernel(killSwitch: kill, modalityRegistry: modality)

        // create an action that would otherwise be allowed (has provenance)
        let action = Action(id: "a1", type: "ncl.action.test", tier: .execute, riskTier: 0, provenanceLinks: ["e1"], sensitivity: nil, modality: "shortcut")

        // engaged -> should block
        kill.engage()
        let decision = kernel.authorize(action: action, context: [:])
        XCTAssertFalse(decision.allow)
        XCTAssertEqual(decision.reasonCode, "KILL_SWITCH_ENGAGED")

        // clear -> should allow (fallback to other checks)
        kill.clear()
        let decision2 = kernel.authorize(action: action, context: [:])
        // PolicyKernel currently will allow execute if no other rule blocks
        XCTAssertTrue(decision2.allow)
    }

    func testLocalAuditLedgerAppendsAndReads() throws {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("ncl_audit_test.jsonl")
        if fm.fileExists(atPath: temp.path) { try fm.removeItem(at: temp) }

        let ledger = LocalAuditLedger(fileURL: temp)
        ledger.append(record: ["action_id": "x1", "event": "test"])
        ledger.append(record: ["action_id": "x2", "event": "test2"])

        let entries = ledger.readAll()
        XCTAssertEqual(entries.count, 2)
        XCTAssertEqual(entries[0]["action_id"] as? String, "x1")
        XCTAssertEqual(entries[1]["action_id"] as? String, "x2")
    }
}

// Simple stub for modality registry used in tests
fileprivate final class StubModalityRegistry: ModalityRegistryProtocol {
    func isAllowed(modality: String, forTier: ActionTier) -> Bool { return true }
}
