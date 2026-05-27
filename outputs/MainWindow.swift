import SwiftUI

#if os(macOS)
import AppKit

// MARK: - Wave 14G P9 — single unified dashboard
//
// One window with a sidebar + detail pane. Cmd+1..8 switches the selected
// section. Replaces the prior 8 separate Window scenes which were a
// "9-window mess to deal with" per NATRIX.

enum DashboardSection: String, CaseIterable, Identifiable {
    case ops = "Ops"
    case quiz = "Morning Quiz"
    case life = "Life Plan"
    case nightWatch = "Night Watch"
    case memory = "Memory"
    case calendar = "Calendar"
    case intel = "Intel"
    case logs = "Logs"

    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .ops:        return "waveform.path.ecg"
        case .quiz:       return "sun.max"
        case .life:       return "map"
        case .nightWatch: return "moon.stars"
        case .memory:     return "brain.head.profile"
        case .calendar:   return "calendar"
        case .intel:      return "antenna.radiowaves.left.and.right"
        case .logs:       return "terminal"
        }
    }

    var tint: Color {
        switch self {
        case .ops:        return .green
        case .quiz:       return .orange
        case .life:       return .blue
        case .nightWatch: return .purple
        case .memory:     return .pink
        case .calendar:   return .yellow
        case .intel:      return .cyan
        case .logs:       return .gray
        }
    }
}

struct NCLMainWindow: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @EnvironmentObject var appSettings: AppSettings
    @AppStorage("ncl.dashboard.section") private var rawSection: String = DashboardSection.ops.rawValue
    @State private var section: DashboardSection = .ops

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            detail
        }
        .navigationSplitViewStyle(.balanced)
        .frame(minWidth: 1100, minHeight: 760)
        .onAppear {
            section = DashboardSection(rawValue: rawSection) ?? .ops
        }
        .onChange(of: section) { newValue in
            rawSection = newValue.rawValue
        }
        .background(
            // Hidden buttons attach Cmd+1..8 to section selection so the
            // shortcuts work app-wide once the main window is key.
            HStack {
                ForEach(Array(DashboardSection.allCases.enumerated()), id: \.element) { i, s in
                    Button("") { section = s }
                        .keyboardShortcut(KeyEquivalent(Character("\(i + 1)")), modifiers: .command)
                        .opacity(0)
                        .frame(width: 0, height: 0)
                }
            }
        )
    }

    private var sidebar: some View {
        List(DashboardSection.allCases, selection: $section) { s in
            HStack(spacing: 10) {
                Image(systemName: s.systemImage)
                    .foregroundColor(s.tint)
                    .frame(width: 22, alignment: .center)
                Text(s.rawValue)
                    .font(.system(size: 13, weight: .medium))
                Spacer()
                Text("⌘\(DashboardSection.allCases.firstIndex(of: s)! + 1)")
                    .font(.caption2.monospaced())
                    .foregroundColor(.secondary)
            }
            .tag(s)
            .padding(.vertical, 2)
        }
        .listStyle(.sidebar)
        .frame(minWidth: 180, idealWidth: 200)
        .navigationTitle("NCL")
    }

    @ViewBuilder
    private var detail: some View {
        switch section {
        case .ops:
            OpsView()
        case .quiz:
            NavigationStack { MorningQuizView() }
        case .life:
            NavigationStack { LifePlanView() }
        case .nightWatch:
            NavigationStack { NightWatchContainer() }
        case .memory:
            NavigationStack { MemoryView() }
        case .calendar:
            NavigationStack { CalendarView() }
        case .intel:
            NavigationStack { IntelView() }
        case .logs:
            LogStreamView()
        }
    }
}

#endif
