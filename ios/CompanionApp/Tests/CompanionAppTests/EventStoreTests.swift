import XCTest
@testable import CompanionApp

final class EventStoreTests: XCTestCase {
    func testAddAndSearchEvent() throws {
        let fm = FileManager.default
        let temp = fm.temporaryDirectory.appendingPathComponent("ncl_events_test.jsonl")
        if fm.fileExists(atPath: temp.path) { try fm.removeItem(at: temp) }

        let store = EventStore(fileURL: temp)
        store.clear()

        let e1 = NclEvent(id: "e1", event_type: "ncl.note.captured", recorded_at: "2026-02-19T00:00:00Z", source: "shortcut", sensitivity: "personal", payload: ["text": .string("buy milk")])
        let e2 = NclEvent(id: "e2", event_type: "ncl.note.captured", recorded_at: "2026-02-19T01:00:00Z", source: "shortcut", sensitivity: "personal", payload: ["text": .string("call Alice")])

        store.addEvent(e1)
        store.addEvent(e2)

        let results = store.search(text: "call")
        XCTAssertEqual(results.count, 1)
        XCTAssertEqual(results.first?.id, "e2")

        let all = store.query(source: "shortcut", sensitivity: "personal")
        XCTAssertEqual(all.count, 2)
    }
}
