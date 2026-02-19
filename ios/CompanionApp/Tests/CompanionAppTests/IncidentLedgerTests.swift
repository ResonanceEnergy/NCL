import XCTest
@testable import CompanionApp

final class IncidentLedgerTests: XCTestCase {
    func testIncidentAppendAndRead() throws {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("ncl_incident_test.jsonl")
        if fm.fileExists(atPath: temp.path) { try fm.removeItem(at: temp) }

        let ledger = LocalIncidentLedger(fileURL: temp)
        ledger.append(incident: ["id": "i1", "severity": "low"])
        ledger.append(incident: ["id": "i2", "severity": "high"])

        let entries = ledger.readAll()
        XCTAssertEqual(entries.count, 2)
        XCTAssertEqual(entries[0]["id"] as? String, "i1")
        XCTAssertNotNil(entries[0]["recorded_at"])
    }
}
