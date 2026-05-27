import SwiftUI

#if os(macOS)
// MARK: - Wave 14G Phase 4 — Mac stubs for LifePlan editor sheets
//
// LifePlanEditors.swift (the rich iOS implementation) uses several
// iOS-only APIs: navigationBarLeading/Trailing toolbar placements,
// keyboardType, and ForEach($collection) binding-overload that the
// macOS SDK can't infer. Walling the file iOS-only and providing these
// Mac shims so LifePlanView still compiles + renders against the same
// references. The Mac sheets present a "use iOS / iPad to edit" hint.

struct VisionEditorSheet: View {
    var existing: VisionMac? = nil
    var onSaved: (() -> Void)? = nil
    var body: some View { LifePlanEditorPlaceholder(title: "Vision") }
}

struct GoalEditorSheet: View {
    var onSaved: (() -> Void)? = nil
    var body: some View { LifePlanEditorPlaceholder(title: "Goal") }
}

struct PlanEditorSheet: View {
    var onSaved: (() -> Void)? = nil
    var body: some View { LifePlanEditorPlaceholder(title: "Plan") }
}

struct WeeklyReviewSheet: View {
    var onSaved: (() -> Void)? = nil
    var body: some View { LifePlanEditorPlaceholder(title: "Weekly Review") }
}

struct YearlyReviewSheet: View {
    var onSaved: (() -> Void)? = nil
    var body: some View { LifePlanEditorPlaceholder(title: "Yearly Review") }
}

struct VisionBoardSheet: View {
    var body: some View { LifePlanEditorPlaceholder(title: "Vision Board") }
}

// Lightweight Vision typealias so the stub VisionEditorSheet signature
// doesn't require us to import the real iOS Vision struct (which is fine
// — the Vision model is in Sources/Models and IS imported, but its name
// collides with the system Vision framework on macOS in some contexts).
typealias VisionMac = Any

private struct LifePlanEditorPlaceholder: View {
    let title: String
    @Environment(\.dismiss) var dismiss
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "lock.shield")
                .font(.system(size: 36))
                .foregroundColor(.secondary)
            Text("\(title) editor")
                .font(.title3.bold())
            Text("Editing \(title.lowercased())s on the desktop is queued for a future build. For now, please use the iOS or iPad version.")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal, 24)
            Button("Close") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
        .padding(28)
        .frame(width: 380, height: 220)
    }
}
#endif
