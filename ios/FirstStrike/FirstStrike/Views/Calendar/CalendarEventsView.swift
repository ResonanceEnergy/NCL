// CalendarEventsView.swift
// Scrollable list of CalendarEvents grouped by date.
// Owned by CalendarView; receives data + the refresh hook via bindings.

import SwiftUI

struct CalendarEventsView: View {
    let cityID: String
    @Binding var window: CalendarWindow
    let events: [CalendarEvent]
    let isLoading: Bool
    let errorMessage: String?
    let onPullRefresh: () async -> Void

    @State private var selected: CalendarEvent?

    var body: some View {
        ZStack {
            AppTheme.background.ignoresSafeArea()

            if isLoading && events.isEmpty {
                ProgressView("Loading events…")
                    .tint(AppTheme.accent)
                    .foregroundColor(.white.opacity(0.7))
            } else if let err = errorMessage, events.isEmpty {
                emptyState(symbol: "exclamationmark.triangle.fill", text: err)
            } else if events.isEmpty {
                emptyState(symbol: "calendar.badge.exclamationmark",
                           text: "No events in the next \(window.rawValue) days.")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18, pinnedViews: [.sectionHeaders]) {
                        ForEach(groupedEvents, id: \.0) { dateLabel, items in
                            Section {
                                VStack(spacing: 10) {
                                    ForEach(items) { event in
                                        EventRow(event: event)
                                            .onTapGesture { selected = event }
                                    }
                                }
                                .padding(.horizontal, 12)
                            } header: {
                                Text(dateLabel)
                                    .font(AppTheme.headlineFont)
                                    .foregroundColor(.white)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 8)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(AppTheme.background.opacity(0.95))
                            }
                        }
                    }
                    .padding(.vertical, 12)
                }
                .refreshable { await onPullRefresh() }
            }
        }
        .sheet(item: $selected) { event in
            EventDetailSheet(event: event)
        }
    }

    private var groupedEvents: [(String, [CalendarEvent])] {
        let df = DateFormatter()
        df.dateFormat = "EEEE, MMM d"
        let grouped = Dictionary(grouping: events) { event in
            df.string(from: event.date)
        }
        // Preserve chronological order of first occurrence
        var seen: [String] = []
        for ev in events {
            let key = df.string(from: ev.date)
            if !seen.contains(key) { seen.append(key) }
        }
        return seen.compactMap { key in
            guard let items = grouped[key] else { return nil }
            return (key, items)
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

private struct EventRow: View {
    let event: CalendarEvent

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            // Impact stripe
            RoundedRectangle(cornerRadius: 2)
                .fill(event.impactColor)
                .frame(width: 4)

            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Image(systemName: event.sourceIcon)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(event.sourceColor)
                    Text((event.source ?? "event").uppercased())
                        .font(AppTheme.captionFont)
                        .foregroundColor(event.sourceColor)
                    if let cat = event.category {
                        Text("· \(cat)")
                            .font(AppTheme.captionFont)
                            .foregroundColor(.white.opacity(0.45))
                    }
                    Spacer()
                    Text(timeLabel)
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.5))
                }
                Text(event.title)
                    .font(AppTheme.bodyFont.weight(.semibold))
                    .foregroundColor(.white)
                    .lineLimit(2)
                if let desc = event.description, !desc.isEmpty {
                    Text(desc)
                        .font(.system(.footnote))
                        .foregroundColor(.white.opacity(0.65))
                        .lineLimit(2)
                }
                if let tags = event.tags, !tags.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(tags.prefix(4), id: \.self) { tag in
                            Text(tag)
                                .font(.system(size: 10, weight: .medium))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(AppTheme.inputBackground)
                                .clipShape(Capsule())
                                .foregroundColor(.white.opacity(0.7))
                        }
                    }
                }
            }
        }
        .padding(12)
        .background(AppTheme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var timeLabel: String {
        let df = DateFormatter()
        df.dateFormat = "h:mm a"
        return df.string(from: event.date)
    }
}

// MARK: - Detail Sheet

private struct EventDetailSheet: View {
    let event: CalendarEvent
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 8) {
                        Image(systemName: event.sourceIcon)
                            .foregroundColor(event.sourceColor)
                        Text((event.source ?? "event").uppercased())
                            .font(AppTheme.captionFont)
                            .foregroundColor(event.sourceColor)
                        Spacer()
                        if let impact = event.impact {
                            Text(impact.uppercased())
                                .font(AppTheme.captionFont)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(event.impactColor.opacity(0.25))
                                .foregroundColor(event.impactColor)
                                .clipShape(Capsule())
                        }
                    }
                    Text(event.title)
                        .font(AppTheme.titleFont)
                        .foregroundColor(.white)
                    Text(dateLabel)
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.6))

                    if let desc = event.description {
                        Text(desc)
                            .font(AppTheme.bodyFont)
                            .foregroundColor(.white.opacity(0.85))
                    }
                    if let url = event.url, let link = URL(string: url) {
                        Link(destination: link) {
                            Label("Open source", systemImage: "arrow.up.right.square")
                                .font(AppTheme.bodyFont)
                                .foregroundColor(AppTheme.accent)
                        }
                    }
                    if let tags = event.tags, !tags.isEmpty {
                        Divider().background(.white.opacity(0.1))
                        Text("Tags").font(AppTheme.headlineFont).foregroundColor(.white)
                        WrapHStack(tags: tags)
                    }
                    Spacer(minLength: 24)
                }
                .padding(16)
            }
            .background(AppTheme.background.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                        .tint(AppTheme.accent)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private var dateLabel: String {
        let df = DateFormatter()
        df.dateStyle = .full
        df.timeStyle = .short
        return df.string(from: event.date)
    }
}

private struct WrapHStack: View {
    let tags: [String]
    var body: some View {
        let columns = [GridItem(.adaptive(minimum: 70), spacing: 6)]
        LazyVGrid(columns: columns, alignment: .leading, spacing: 6) {
            ForEach(tags, id: \.self) { tag in
                Text(tag)
                    .font(.system(size: 11, weight: .medium))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(AppTheme.inputBackground)
                    .clipShape(Capsule())
                    .foregroundColor(.white.opacity(0.75))
            }
        }
    }
}
