import SwiftUI

// MARK: - Wave 14G P10 — FSTab extracted to standalone file
//
// Previously declared inline in Sources/App/ContentView.swift (iOS-only
// entry point). Extracted so the macOS NCLDesktop target can reference
// FSTab from DashboardView / NCLMainWindow without compiling ContentView.

enum FSTab: String, CaseIterable {
    case dashboard = "Dashboard"
    case portfolio = "Portfolio"
    case intel = "Intel"
    case memory = "Memory"
    case calendar = "Calendar"
    case journal = "Journal"
    case settings = "Settings"

    /// Tabs shown in the bottom tab bar. Settings is moved to a gear icon
    /// in the Dashboard header (2026-05-22) to free up a slot for the 6
    /// frequently-used tabs without overflowing iPhone's 5-tab limit.
    static var bottomBarCases: [FSTab] {
        allCases.filter { $0 != .settings }
    }

    var icon: String {
        switch self {
        case .dashboard: return "square.grid.2x2.fill"
        case .portfolio: return "briefcase.fill"
        case .intel: return "eye.fill"
        case .memory: return "brain.head.profile"
        case .calendar: return "moon.stars.fill"
        case .journal: return "square.and.pencil"
        case .settings: return "gearshape.fill"
        }
    }

    var color: Color {
        switch self {
        case .dashboard: return FSColor.orange
        case .portfolio: return FSColor.green
        case .intel: return FSColor.cyan
        case .memory: return FSColor.pink
        case .calendar: return Color(hex: "E94560")
        case .journal: return FSColor.yellow
        case .settings: return FSColor.purple
        }
    }
}
