import XCTest
@testable import CompanionApp

final class GoldenTasksPresenceTests: XCTestCase {
    func testGoldenTasksDirectoryHasFiles() throws {
        let fm = FileManager.default
        let folder = URL(fileURLWithPath: #file).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("evaluation/golden_tasks")
        XCTAssertTrue(fm.fileExists(atPath: folder.path), "evaluation/golden_tasks directory must exist")
        let files = try fm.contentsOfDirectory(atPath: folder.path)
        XCTAssertTrue(files.count > 0, "golden tasks must include at least one file")
    }
}
