// AuditLedgerTests.swift — NCL iOS Companion
// Tests for HMAC-signed NDJSON append-only ledger.

import XCTest
import CryptoKit
@testable import CompanionApp

final class AuditLedgerTests: XCTestCase {

    // MARK: - Helpers

    private func makeTempDir() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("AuditLedgerTests-\(UUID().uuidString)")
    }

    private func makeSUT(dir: URL? = nil, key: SymmetricKey? = nil) -> AuditLedger {
        AuditLedger(directory: dir ?? makeTempDir(), signingKey: key)
    }

    private func sampleEntry(id: String = "test-1",
                              category: String = "test.action",
                              verdict: String = "allow") -> AuditEntry {
        AuditEntry(
            id: id,
            actionID: "action-\(id)",
            tier: "execute",
            category: category,
            verdict: verdict,
            reason: "test_reason",
            timestamp: Date(),
            provenanceChain: ["src-1", "src-2"]
        )
    }

    // MARK: - Initial State

    func testEmptyLedgerHasZeroEntries() {
        let sut = makeSUT()
        XCTAssertEqual(sut.count, 0)
        XCTAssertTrue(sut.entries.isEmpty)
    }

    // MARK: - Append

    func testAppendIncreasesCount() {
        let sut = makeSUT()
        sut.append(entry: sampleEntry())
        XCTAssertEqual(sut.count, 1)
    }

    func testAppendMultipleEntries() {
        let sut = makeSUT()
        for i in 1...5 {
            sut.append(entry: sampleEntry(id: "e-\(i)"))
        }
        XCTAssertEqual(sut.count, 5)
    }

    func testAppendedEntryAccessible() {
        let sut = makeSUT()
        let entry = sampleEntry(id: "unique-42")
        sut.append(entry: entry)
        XCTAssertEqual(sut.entries.first?.id, "unique-42")
    }

    // MARK: - Search

    func testSearchByCategory() {
        let sut = makeSUT()
        sut.append(entry: sampleEntry(category: "alpha"))
        sut.append(entry: sampleEntry(id: "2", category: "beta"))
        sut.append(entry: sampleEntry(id: "3", category: "alpha"))

        let results = sut.search { $0.category == "alpha" }
        XCTAssertEqual(results.count, 2)
    }

    func testSearchByVerdict() {
        let sut = makeSUT()
        sut.append(entry: sampleEntry(verdict: "allow"))
        sut.append(entry: sampleEntry(id: "2", verdict: "deny"))

        let denied = sut.search { $0.verdict == "deny" }
        XCTAssertEqual(denied.count, 1)
        XCTAssertEqual(denied.first?.id, "2")
    }

    func testSearchNoMatch() {
        let sut = makeSUT()
        sut.append(entry: sampleEntry())
        let results = sut.search { $0.category == "nonexistent" }
        XCTAssertTrue(results.isEmpty)
    }

    // MARK: - Export JSON

    func testExportJSONReturnsValidData() throws {
        let sut = makeSUT()
        sut.append(entry: sampleEntry())
        let data = try XCTUnwrap(sut.exportJSON())
        let decoded = try JSONDecoder().decode([AuditEntry].self, from: data)
        XCTAssertEqual(decoded.count, 1)
        XCTAssertEqual(decoded.first?.id, "test-1")
    }

    func testExportEmptyLedgerReturnsEmptyArray() throws {
        let sut = makeSUT()
        let data = try XCTUnwrap(sut.exportJSON())
        let decoded = try JSONDecoder().decode([AuditEntry].self, from: data)
        XCTAssertTrue(decoded.isEmpty)
    }

    // MARK: - Integrity Verification

    func testIntegrityValidOnFreshLedger() {
        let sut = makeSUT()
        sut.append(entry: sampleEntry())
        sut.append(entry: sampleEntry(id: "2"))
        XCTAssertTrue(sut.verifyIntegrity())
    }

    func testIntegrityValidOnEmptyLedger() {
        let sut = makeSUT()
        XCTAssertTrue(sut.verifyIntegrity())
    }

    func testIntegrityFailsOnTamperedFile() throws {
        let dir = makeTempDir()
        let sut = makeSUT(dir: dir)
        sut.append(entry: sampleEntry())

        // Tamper with the file
        let fileURL = dir.appendingPathComponent("audit_ledger.ndjson")
        var contents = try String(contentsOf: fileURL, encoding: .utf8)
        contents = contents.replacingOccurrences(of: "test_reason", with: "TAMPERED")
        try contents.write(to: fileURL, atomically: true, encoding: .utf8)

        XCTAssertFalse(sut.verifyIntegrity(), "Integrity check should fail after tampering")
    }

    // MARK: - Persistence Across Instances

    func testEntriesPersistAcrossInstances() {
        let dir = makeTempDir()
        let key = SymmetricKey(size: .bits256)

        let sut1 = AuditLedger(directory: dir, signingKey: key)
        sut1.append(entry: sampleEntry(id: "persist-1"))
        sut1.append(entry: sampleEntry(id: "persist-2"))
        XCTAssertEqual(sut1.count, 2)

        // New instance with same directory & key should load entries
        let sut2 = AuditLedger(directory: dir, signingKey: key)
        XCTAssertEqual(sut2.count, 2)
        XCTAssertEqual(sut2.entries.first?.id, "persist-1")
    }

    // MARK: - AuditEntry Codable

    func testAuditEntryCodable() throws {
        let entry = sampleEntry()
        let data = try JSONEncoder().encode(entry)
        let decoded = try JSONDecoder().decode(AuditEntry.self, from: data)
        XCTAssertEqual(decoded.id, entry.id)
        XCTAssertEqual(decoded.actionID, entry.actionID)
        XCTAssertEqual(decoded.category, entry.category)
        XCTAssertEqual(decoded.provenanceChain, entry.provenanceChain)
    }

    // MARK: - Thread Safety

    func testConcurrentAppendsDoNotCrash() {
        let sut = makeSUT()
        let expectation = expectation(description: "concurrent appends")
        expectation.expectedFulfillmentCount = 50

        for i in 0..<50 {
            DispatchQueue.global().async {
                sut.append(entry: self.sampleEntry(id: "concurrent-\(i)"))
                expectation.fulfill()
            }
        }

        waitForExpectations(timeout: 10)
        XCTAssertEqual(sut.count, 50)
    }
}
