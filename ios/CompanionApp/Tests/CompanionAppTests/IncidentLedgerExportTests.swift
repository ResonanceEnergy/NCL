import XCTest
@testable import CompanionApp

final class IncidentLedgerExportTests: XCTestCase {
    func testExportAsJSONArrayWritesFile() throws {
        let fm = FileManager.default
        let tempLedger = fm.temporaryDirectory.appendingPathComponent("ncl_incident_export_test.jsonl")
        if fm.fileExists(atPath: tempLedger.path) { try fm.removeItem(at: tempLedger) }

        let ledger = LocalIncidentLedger(fileURL: tempLedger)
        ledger.append(incident: ["id": "i1", "severity": "low"])
        ledger.append(incident: ["id": "i2", "severity": "high"])

        let exportURL = fm.temporaryDirectory.appendingPathComponent("ncl_incident_export.json")
        if fm.fileExists(atPath: exportURL.path) { try fm.removeItem(at: exportURL) }

        try ledger.exportAsJSONArray(to: exportURL)
        let data = try Data(contentsOf: exportURL)
        let obj = try JSONSerialization.jsonObject(with: data, options: [])
        guard let arr = obj as? [[String: Any]] else { XCTFail("export not array"); return }
        XCTAssertEqual(arr.count, 2)
        XCTAssertEqual(arr[0]["id"] as? String, "i1")
    }
}
