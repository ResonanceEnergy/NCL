import SwiftUI

// MARK: - Wave 14G Phase 5 — NightWatch fetcher container
//
// NightWatchBriefView takes `brief: NightWatchBrief` as a required init
// param. The iOS NightWatchView wraps it inside the Intel tab where the
// brief is passed down from a list. For the macOS Cmd+3 Window scene we
// need a self-contained loader: fetch /intelligence/night-watch/latest,
// handle loading + error states, then hand off the brief to the view.

struct NightWatchContainer: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    @State private var brief: NightWatchBrief? = nil
    @State private var loading = true
    @State private var error: String? = nil

    var body: some View {
        Group {
            if loading {
                ProgressView("Loading latest Night Watch…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let err = error {
                VStack(spacing: 14) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 36))
                        .foregroundColor(.orange)
                    Text("Failed to load Night Watch")
                        .font(.headline)
                    Text(err)
                        .font(.caption.monospaced())
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                    Button("Retry") {
                        Task { await load() }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let b = brief {
                NightWatchBriefView(brief: b)
            } else {
                Text("No Night Watch briefs found.")
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await load() }
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button {
                    Task { await load() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Refresh")
            }
        }
    }

    private func load() async {
        loading = true
        error = nil
        do {
            brief = try await brainClient.fetchNightWatchLatest()
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }
}
