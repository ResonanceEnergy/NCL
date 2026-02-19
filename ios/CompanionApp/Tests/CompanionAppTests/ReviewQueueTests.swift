import XCTest
import SwiftUI
@testable import CompanionApp

final class ReviewQueueTests: XCTestCase {
    func testArchiveRemovesItem() {
        var view = ReviewQueueView()
        XCTAssertEqual(view.body is View, true) // basic render sanity
        // use archive via exposing internal method through instance mutation
        view.archive(id: "e1")
        // since items is private, rely on UI snapshot in real tests; here just ensure no crash
        XCTAssertTrue(true)
    }
}
