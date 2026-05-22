// CalendarMoonView.swift
// Moon phase visualization + cycle narrative + upcoming phases + moon todos.

import SwiftUI

struct CalendarMoonView: View {
    let moon: MoonState?
    let isLoading: Bool
    let errorMessage: String?
    let onPullRefresh: () async -> Void

    var body: some View {
        ZStack {
            AppTheme.background.ignoresSafeArea()

            if isLoading && moon == nil {
                ProgressView("Reading the moon…")
                    .tint(AppTheme.accent)
                    .foregroundColor(.white.opacity(0.7))
            } else if let err = errorMessage, moon == nil {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 44))
                        .foregroundColor(.white.opacity(0.35))
                    Text(err)
                        .font(AppTheme.bodyFont)
                        .foregroundColor(.white.opacity(0.55))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }
            } else if let moon {
                ScrollView {
                    VStack(spacing: 18) {
                        phaseHero(moon.phase, energy: moon.energy)
                        if let ctx = moon.cycleContext, !ctx.isEmpty {
                            cycleContextCard(ctx)
                        }
                        if let upcoming = moon.upcomingPhases, !upcoming.isEmpty {
                            upcomingCard(upcoming)
                        }
                        if let todos = moon.suggestedTodos, !todos.isEmpty {
                            moonTodosCard(todos)
                        }
                    }
                    .padding(16)
                }
                .refreshable { await onPullRefresh() }
            }
        }
    }

    // MARK: - Sections

    private func phaseHero(_ phase: MoonPhase, energy: String?) -> some View {
        VStack(spacing: 10) {
            Image(systemName: phase.icon)
                .symbolRenderingMode(.hierarchical)
                .font(.system(size: 140, weight: .light))
                .foregroundStyle(.white)
                .shadow(color: AppTheme.gemini.opacity(0.35), radius: 30)
                .padding(.vertical, 12)
            Text(phase.name)
                .font(AppTheme.titleFont)
                .foregroundColor(.white)
            HStack(spacing: 14) {
                if let illum = phase.illumination {
                    metric(label: "Illum", value: String(format: "%.0f%%", illum * 100))
                }
                if let age = phase.age {
                    metric(label: "Age", value: String(format: "%.1fd", age))
                }
                if let energy {
                    metric(label: "Energy", value: energy)
                }
            }
            if let next = phase.nextMajor, let date = phase.nextMajorDate {
                Text("Next: \(next) · \(shortDate(date))")
                    .font(AppTheme.captionFont)
                    .foregroundColor(.white.opacity(0.6))
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 18)
        .background(AppTheme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private func metric(label: String, value: String) -> some View {
        VStack(spacing: 2) {
            Text(value)
                .font(AppTheme.bodyFont.weight(.semibold))
                .foregroundColor(.white)
            Text(label.uppercased())
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(.white.opacity(0.5))
        }
    }

    private func cycleContextCard(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("Cycle Context", icon: "waveform.path")
            Text(text)
                .font(AppTheme.bodyFont)
                .foregroundColor(.white.opacity(0.85))
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppTheme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func upcomingCard(_ phases: [UpcomingPhase]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionHeader("Upcoming Major Phases", icon: "calendar.circle")
            ForEach(phases.prefix(4)) { phase in
                HStack {
                    Image(systemName: phaseIcon(for: phase.name))
                        .foregroundColor(AppTheme.gemini)
                        .frame(width: 22)
                    Text(phase.name)
                        .font(AppTheme.bodyFont)
                        .foregroundColor(.white)
                    Spacer()
                    if let days = phase.daysUntil {
                        Text("in \(days)d")
                            .font(AppTheme.captionFont)
                            .foregroundColor(.white.opacity(0.6))
                    }
                    Text(shortDate(phase.date))
                        .font(AppTheme.captionFont)
                        .foregroundColor(.white.opacity(0.5))
                }
                .padding(.vertical, 4)
                if phase.id != phases.prefix(4).last?.id {
                    Divider().background(.white.opacity(0.06))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppTheme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func moonTodosCard(_ todos: [CalendarTodo]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionHeader("Suggested Moon To-Dos", icon: "moon.stars")
            ForEach(todos) { todo in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "circle")
                        .font(.system(size: 14))
                        .foregroundColor(.white.opacity(0.5))
                        .padding(.top, 3)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(todo.title)
                            .font(AppTheme.bodyFont.weight(.medium))
                            .foregroundColor(.white)
                        if let detail = todo.detail {
                            Text(detail)
                                .font(.system(.footnote))
                                .foregroundColor(.white.opacity(0.65))
                        }
                    }
                    Spacer()
                }
                .padding(.vertical, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppTheme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func sectionHeader(_ title: String, icon: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon).foregroundColor(AppTheme.accent)
            Text(title)
                .font(AppTheme.headlineFont)
                .foregroundColor(.white)
        }
    }

    private func shortDate(_ date: Date) -> String {
        let df = DateFormatter()
        df.dateFormat = "MMM d"
        return df.string(from: date)
    }

    private func phaseIcon(for name: String) -> String {
        // Reuse MoonPhase's mapping by faking a phase with that name.
        let p = MoonPhase(name: name, illumination: nil, age: nil, angle: nil,
                          nextMajor: nil, nextMajorDate: nil)
        return p.icon
    }
}
