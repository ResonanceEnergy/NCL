import SwiftUI

#if os(macOS)
import AppKit

// MARK: - Wave 14G P10 — Combined Ops + Settings tab
//
// Replaces the iOS gear-icon Settings sheet on Mac with a unified Ops
// section that surfaces:
//   1. LIVE   — the OpsView dashboard (Mac-only, host/brain/tailscale
//               + scheduler grid + LLM table + sparklines)
//   2. SETTINGS — Brain connection (Tailscale IP, port, auth token,
//                 direct/relay mode toggle)
//   3. LOGS    — the LogStreamView log tail
//
// Sub-tabs along the top via a segmented picker, mirroring how iOS
// SettingsView uses FSSectionPicker for Processor/Loops/History/Costs/
// Version. The "Ops" tab on Mac IS the iOS Settings tab — just renamed
// + with the live monitor stitched in.

enum OpsSection: String, CaseIterable, Identifiable {
    case live = "Live"
    case settings = "Settings"
    case logs = "Logs"
    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .live:     return "waveform.path.ecg"
        case .settings: return "gearshape.fill"
        case .logs:     return "terminal"
        }
    }
}

struct OpsSettingsView: View {
    @EnvironmentObject var appSettings: AppSettings
    @State private var sub: OpsSection = .live

    var body: some View {
        VStack(spacing: 0) {
            picker
            Divider()
            content
        }
    }

    private var picker: some View {
        HStack(spacing: 6) {
            ForEach(OpsSection.allCases) { s in
                Button {
                    sub = s
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: s.systemImage)
                        Text(s.rawValue)
                            .font(.system(size: 13, weight: .medium))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(sub == s ? Color.accentColor.opacity(0.25) : Color.clear)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    @ViewBuilder
    private var content: some View {
        switch sub {
        case .live:
            OpsView()
        case .settings:
            SettingsForm()
                .environmentObject(appSettings)
        case .logs:
            LogStreamView()
        }
    }
}

// MARK: - Settings form (Mac-native, replaces iOS gear sheet)

struct SettingsForm: View {
    @EnvironmentObject var appSettings: AppSettings

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                section("Brain Connection") {
                    LabeledContent("Tailscale IP") {
                        TextField("100.72.223.123", text: $appSettings.tailscaleIP)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 200)
                    }
                    LabeledContent("Brain Port") {
                        TextField("8800", value: $appSettings.brainPort, format: .number)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 100)
                    }
                    LabeledContent("Auth Token") {
                        SecureField("STRIKE_AUTH_TOKEN", text: $appSettings.brainAuthToken)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 320)
                    }
                    LabeledContent("Use Brain Direct") {
                        Toggle("", isOn: $appSettings.useBrainDirect)
                            .toggleStyle(.switch)
                    }
                    LabeledContent("Use Tailscale") {
                        Toggle("", isOn: $appSettings.useTailscale)
                            .toggleStyle(.switch)
                    }
                    LabeledContent("Relay Port") {
                        TextField("8787", value: $appSettings.relayPort, format: .number)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 100)
                    }
                }

                section("Active Brain URL") {
                    let host = appSettings.useTailscale ? appSettings.tailscaleIP : "127.0.0.1"
                    let port = appSettings.useBrainDirect ? appSettings.brainPort : appSettings.relayPort
                    HStack(spacing: 8) {
                        Image(systemName: "network")
                            .foregroundColor(.green)
                        Text("http://\(host):\(port)")
                            .font(.system(size: 13, design: .monospaced))
                            .textSelection(.enabled)
                        Spacer()
                    }
                    .padding(10)
                    .background(Color.gray.opacity(0.15))
                    .cornerRadius(6)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String,
                                         @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased())
                .font(.caption.bold().monospaced())
                .foregroundColor(.secondary)
            VStack(spacing: 8) {
                content()
            }
            .padding(14)
            .background(Color.gray.opacity(0.08))
            .cornerRadius(8)
        }
    }
}

// MARK: - Stub Dashboard (Mac variant)
//
// iOS DashboardView pulls in CouncilView, ChatBubble, ChatInputBar +
// the whole conversational surface. For Mac, we render a simpler
// "home" view that surfaces brain pulse + key actions. Power-user
// authoring happens in the other tabs.

struct DashboardHomeView: View {
    @EnvironmentObject var brainClient: NCLBrainClient
    var body: some View {
        OpsView()
    }
}

// MARK: - Portfolio stub
//
// iOS PortfolioView cascades into ~12 sub-view files (Options,
// GOATScanner, Bravo, Paper, Crypto, Polymarket, BrokerConnect, etc).
// Importing each would multiply the iOS-only-shim work. Mac users
// view portfolio on iPhone/iPad for v1.

struct PortfolioStubView: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "briefcase.fill")
                .font(.system(size: 48))
                .foregroundColor(.green.opacity(0.7))
            Text("Portfolio")
                .font(.title2.bold())
            Text("Portfolio (positions, GOAT scanner, Bravo swing, paper trades, options flow) lives on iPhone/iPad for v1. The Mac desktop is optimised for authoring + ambient ops; the conversational + portfolio surfaces stay mobile.")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal, 40)
            Text("Open on iPhone or iPad → Portfolio tab")
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
                .padding(.top, 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

#endif
