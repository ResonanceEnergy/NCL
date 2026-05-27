import Foundation
import SwiftUI

#if os(macOS)
// MARK: - Wave 14G P13 — Mac stub for VoiceEngine
//
// The real iOS VoiceEngine uses AVAudioSession (unavailable on macOS) for
// microphone capture + speech recognition + synthesis. Mac users author
// via keyboard, so this stub satisfies the type contract that ChatView /
// ChatInputBar reference + lets those views compile + render. All
// methods are silent no-ops; voiceEnabled stays false so the chat input
// bar's voice button doesn't activate.

@MainActor
final class VoiceEngine: NSObject, ObservableObject {
    @Published var isListening = false
    @Published var isSpeaking = false
    @Published var transcribedText = ""
    @Published var lastSpokenResponse = ""
    @Published var voiceEnabled = false
    @Published var audioLevel: Float = 0.0
    @Published var errorMessage: String? = nil
    @Published var permissionGranted = false

    override init() { super.init() }

    func requestPermissions() async { /* no-op on macOS */ }
    func startListening() { /* no-op */ }
    func stopListening() { /* no-op */ }
    func speak(_ text: String) { /* no-op */ }
    func stopSpeaking() { /* no-op */ }
    func getTranscribedText() -> String { transcribedText }
}
#endif
