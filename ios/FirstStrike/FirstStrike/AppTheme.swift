import SwiftUI

enum AppTheme {
    // NATRIX brand colors
    static let accent = Color(red: 0.95, green: 0.3, blue: 0.15)  // Resonance red-orange
    static let accentGradient = LinearGradient(
        colors: [Color(red: 0.95, green: 0.3, blue: 0.15), Color(red: 1.0, green: 0.5, blue: 0.2)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    // Chat bubble colors
    static let userBubble = Color(red: 0.95, green: 0.3, blue: 0.15)
    static let aiBubble = Color(white: 0.15)
    static let userText = Color.white
    static let aiText = Color(white: 0.92)

    // Background
    static let background = Color(white: 0.06)
    static let cardBackground = Color(white: 0.12)
    static let inputBackground = Color(white: 0.14)

    // Status colors
    static let success = Color.green
    static let warning = Color.yellow
    static let danger = Color.red
    static let info = Color.blue

    // Council member colors
    static let claude = Color(red: 0.85, green: 0.55, blue: 0.3)    // Warm amber
    static let grok = Color(red: 0.3, green: 0.7, blue: 1.0)       // Electric blue
    static let gemini = Color(red: 0.3, green: 0.85, blue: 0.5)    // Google green
    static let perplexity = Color(red: 0.6, green: 0.4, blue: 0.9)  // Purple
    static let gpt = Color(red: 0.4, green: 0.85, blue: 0.7)       // Teal
    static let copilot = Color(red: 0.2, green: 0.5, blue: 0.9)    // Azure blue

    static func councilColor(for member: String) -> Color {
        switch member.lowercased() {
        case "claude": return claude
        case "grok": return grok
        case "gemini": return gemini
        case "perplexity": return perplexity
        case "gpt": return gpt
        case "copilot": return copilot
        default: return accent
        }
    }

    // Priority colors
    static func priorityColor(_ priority: Int) -> Color {
        switch priority {
        case 9...10: return .red
        case 7...8: return .orange
        case 5...6: return .yellow
        case 3...4: return .green
        default: return .gray
        }
    }

    // Typography
    static let titleFont = Font.system(.title2, design: .rounded, weight: .bold)
    static let headlineFont = Font.system(.headline, design: .rounded, weight: .semibold)
    static let bodyFont = Font.system(.body, design: .default)
    static let captionFont = Font.system(.caption, design: .monospaced)
    static let codeFont = Font.system(.footnote, design: .monospaced)
}
