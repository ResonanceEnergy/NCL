import SwiftUI
#if os(macOS)
import Sparkle

// MARK: - Wave 14G Phase 7 — Sparkle 2 auto-update
//
// Brain hosts the appcast at http://100.72.223.123:8800/desktop/appcast.xml
// (FastAPI static-file serve). The .dmg is built + signed locally via
// make_release.sh which writes the appcast entry + signed .dmg into
// ~/dev/NCL/desktop_releases/. Each NCL Desktop launch checks the
// appcast on startup + on user-triggered Check Updates.

final class UpdaterHolder: ObservableObject {
    let controller: SPUStandardUpdaterController

    init() {
        controller = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )
    }

    var canCheck: Bool {
        controller.updater.canCheckForUpdates
    }

    func checkForUpdates() {
        controller.checkForUpdates(nil)
    }
}

struct CheckForUpdatesView: View {
    @ObservedObject var holder: UpdaterHolder

    var body: some View {
        Button("Check for Updates\u{2026}") {
            holder.checkForUpdates()
        }
        .disabled(!holder.canCheck)
    }
}
#endif
