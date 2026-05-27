import SwiftUI

#if os(macOS)
import AppKit

// MARK: - Wave 14G P10 — iOS-identical 7-tab dashboard
//
// Sidebar now mirrors the iOS bottom tab bar exactly:
//   Dashboard · Portfolio · Intel · Memory · Calendar · Journal · Ops
// "Ops" replaces "Settings" — combines the live system monitor with
// the brain-connection settings form. Same icons + colors as iOS via
// FSTab so the Mac feels like a desktop projection of the iPhone app.

struct NCLMainWindow: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @EnvironmentObject var appSettings: AppSettings
    @AppStorage("ncl.dashboard.section") private var rawSection: String = FSTab.dashboard.rawValue
    @State private var section: FSTab = .dashboard

    private var tabs: [FSTab] {
        // Mirror iOS bottomBarCases (drops .settings) + add Ops at end.
        // On Mac, .settings is presented as "Ops" inside the sidebar.
        FSTab.bottomBarCases + [.settings]
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            detail
        }
        .navigationSplitViewStyle(.balanced)
        .frame(minWidth: 1100, minHeight: 760)
        .onAppear {
            section = FSTab(rawValue: rawSection) ?? .dashboard
        }
        .onChange(of: section) { newValue in
            rawSection = newValue.rawValue
        }
        .background(
            HStack {
                ForEach(Array(tabs.enumerated()), id: \.element) { i, t in
                    Button("") { section = t }
                        .keyboardShortcut(KeyEquivalent(Character("\(i + 1)")), modifiers: .command)
                        .opacity(0)
                        .frame(width: 0, height: 0)
                }
            }
        )
    }

    private var sidebar: some View {
        List(tabs, selection: $section) { t in
            HStack(spacing: 10) {
                Image(systemName: macIcon(for: t))
                    .foregroundColor(t.color)
                    .frame(width: 22, alignment: .center)
                Text(label(for: t))
                    .font(.system(size: 13, weight: .medium))
                Spacer()
                Text("⌘\(tabs.firstIndex(of: t)! + 1)")
                    .font(.caption2.monospaced())
                    .foregroundColor(.secondary)
            }
            .tag(t)
            .padding(.vertical, 2)
        }
        .listStyle(.sidebar)
        .frame(minWidth: 200, idealWidth: 220)
        .navigationTitle("NCL")
    }

    // Override .settings → "Ops" label + waveform icon for Mac.
    private func label(for t: FSTab) -> String {
        t == .settings ? "Ops" : t.rawValue
    }

    private func macIcon(for t: FSTab) -> String {
        t == .settings ? "waveform.path.ecg" : t.icon
    }

    @ViewBuilder
    private var detail: some View {
        switch section {
        case .dashboard:
            DashboardHomeView()
        case .portfolio:
            PortfolioStubView()
        case .intel:
            NavigationStack { IntelView() }
        case .memory:
            NavigationStack { MemoryView() }
        case .calendar:
            NavigationStack { CalendarView() }
        case .journal:
            NavigationStack { JournalView() }
        case .settings:
            OpsSettingsView()
        }
    }
}

#endif
