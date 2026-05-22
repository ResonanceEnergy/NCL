// CalendarTodosView.swift
// Priority-sorted list of CalendarTodos.
// Local "done" state lives in @AppStorage as a CSV of todo IDs — purely a UI hint
// (no backend write).  energy_aligned todos get a moon badge.

import SwiftUI

struct CalendarTodosView: View {
    let cityID: String
    @Binding var window: CalendarWindow
    let todos: [CalendarTodo]
    let isLoading: Bool
    let errorMessage: String?
    let onPullRefresh: () async -> Void

    /// CSV of completed-locally todo IDs; survives restarts but is purely local.
    @AppStorage("calendar.completedTodoIDs") private var completedCSV: String = ""

    var body: some View {
        ZStack {
            AppTheme.background.ignoresSafeArea()

            if isLoading && todos.isEmpty {
                ProgressView("Loading to-dos…")
                    .tint(AppTheme.accent)
                    .foregroundColor(.white.opacity(0.7))
            } else if let err = errorMessage, todos.isEmpty {
                emptyState(symbol: "exclamationmark.triangle.fill", text: err)
            } else if todos.isEmpty {
                emptyState(symbol: "checkmark.circle",
                           text: "No to-dos in the next \(window.rawValue) days.")
            } else {
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(sortedTodos) { todo in
                            TodoRow(
                                todo: todo,
                                isDone: completed.contains(todo.id),
                                toggle: { toggle(todo) }
                            )
                        }
                    }
                    .padding(12)
                }
                .refreshable { await onPullRefresh() }
            }
        }
    }

    private var completed: Set<String> {
        Set(completedCSV.split(separator: ",").map(String.init))
    }

    private func toggle(_ todo: CalendarTodo) {
        var set = completed
        if set.contains(todo.id) { set.remove(todo.id) } else { set.insert(todo.id) }
        completedCSV = set.sorted().joined(separator: ",")
    }

    private var sortedTodos: [CalendarTodo] {
        // Priority desc, then due date asc, with completed sinking to bottom.
        todos.sorted { a, b in
            let aDone = completed.contains(a.id), bDone = completed.contains(b.id)
            if aDone != bDone { return !aDone }
            if a.priority != b.priority { return a.priority > b.priority }
            switch (a.dueDate, b.dueDate) {
            case (let x?, let y?): return x < y
            case (nil, _?):        return false
            case (_?, nil):        return true
            default:               return a.title < b.title
            }
        }
    }

    @ViewBuilder
    private func emptyState(symbol: String, text: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 44))
                .foregroundColor(.white.opacity(0.35))
            Text(text)
                .font(AppTheme.bodyFont)
                .foregroundColor(.white.opacity(0.55))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
    }
}

// MARK: - Row

private struct TodoRow: View {
    let todo: CalendarTodo
    let isDone: Bool
    let toggle: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Button(action: toggle) {
                Image(systemName: isDone ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22))
                    .foregroundColor(isDone ? AppTheme.success : .white.opacity(0.5))
            }
            .buttonStyle(.plain)
            .padding(.top, 2)

            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    priorityBadge
                    if let src = todo.source {
                        sourceBadge(src)
                    }
                    if todo.energyAligned == true {
                        Label("aligned", systemImage: "moon.stars.fill")
                            .font(AppTheme.captionFont)
                            .foregroundColor(AppTheme.gemini)
                    }
                    Spacer()
                    if let due = todo.dueDate {
                        Text(dueLabel(due))
                            .font(AppTheme.captionFont)
                            .foregroundColor(.white.opacity(0.5))
                    }
                }
                Text(todo.title)
                    .font(AppTheme.bodyFont.weight(.semibold))
                    .foregroundColor(isDone ? .white.opacity(0.45) : .white)
                    .strikethrough(isDone)
                if let detail = todo.detail, !detail.isEmpty {
                    Text(detail)
                        .font(.system(.footnote))
                        .foregroundColor(.white.opacity(0.65))
                        .lineLimit(3)
                }
            }
        }
        .padding(12)
        .background(AppTheme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .opacity(isDone ? 0.6 : 1.0)
    }

    private var priorityBadge: some View {
        Text("P\(todo.priority)")
            .font(.system(size: 10, weight: .bold, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(AppTheme.priorityColor(todo.priority).opacity(0.25))
            .foregroundColor(AppTheme.priorityColor(todo.priority))
            .clipShape(Capsule())
    }

    private func sourceBadge(_ src: String) -> some View {
        Text(src.uppercased())
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(AppTheme.inputBackground)
            .foregroundColor(.white.opacity(0.7))
            .clipShape(Capsule())
    }

    private func dueLabel(_ date: Date) -> String {
        let df = DateFormatter()
        df.dateFormat = "MMM d"
        return df.string(from: date)
    }
}
