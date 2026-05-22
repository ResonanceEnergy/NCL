import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selectedTab: Tab = .chat

    enum Tab: String, CaseIterable {
        case chat = "Chat"
        case intel = "Intel"
        case calendar = "Calendar"
        case council = "Council"
        case settings = "Settings"

        var icon: String {
            switch self {
            case .chat: return "bubble.left.and.bubble.right.fill"
            case .intel: return "brain.head.profile"
            case .calendar: return "calendar"
            case .council: return "person.3.fill"
            case .settings: return "gearshape.fill"
            }
        }
    }

    var body: some View {
        Group {
            if appState.isOnboarded {
                mainTabView
            } else {
                OnboardingView()
            }
        }
        .preferredColorScheme(.dark)
    }

    private var mainTabView: some View {
        TabView(selection: $selectedTab) {
            ForEach(Tab.allCases, id: \.self) { tab in
                tabContent(for: tab)
                    .tabItem {
                        Label(tab.rawValue, systemImage: tab.icon)
                    }
                    .tag(tab)
            }
        }
        .tint(AppTheme.accent)
    }

    @ViewBuilder
    private func tabContent(for tab: Tab) -> some View {
        switch tab {
        case .chat:
            ChatView()
        case .intel:
            IntelligenceView()
        case .calendar:
            CalendarView()
        case .council:
            CouncilView()
        case .settings:
            SettingsView()
        }
    }
}
