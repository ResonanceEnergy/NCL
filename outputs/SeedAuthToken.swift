import SwiftUI

#if os(macOS)
import Foundation

// MARK: - Wave 14G P10 — Mac auth-token seeder
//
// On Mac, first-launch brainAuthToken is empty (Keychain is fresh). The
// token lives at ~/dev/NCL/.env so the brain process can read it. This
// helper reads it from there on app start and pushes it into AppSettings
// if the user hasn't already set one.
//
// One-time + silent: if the .env file is missing or doesn't have a
// STRIKE_AUTH_TOKEN line, this is a no-op and the user can paste the
// token manually in the Ops → Settings sub-tab.

enum MacAuthSeeder {
    static func seedIfEmpty(_ settings: AppSettings) {
        guard settings.brainAuthToken.isEmpty else { return }
        let envPath = "\(NSHomeDirectory())/dev/NCL/.env"
        guard let raw = try? String(contentsOfFile: envPath, encoding: .utf8) else {
            return
        }
        for line in raw.split(separator: "\n") {
            let s = line.trimmingCharacters(in: .whitespaces)
            guard s.hasPrefix("STRIKE_AUTH_TOKEN") else { continue }
            // Format: STRIKE_AUTH_TOKEN=<token> or STRIKE_AUTH_TOKEN="..."
            let parts = s.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }
            var token = String(parts[1]).trimmingCharacters(in: .whitespaces)
            token = token.trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            if !token.isEmpty {
                settings.brainAuthToken = token
            }
            return
        }
    }
}

#endif
