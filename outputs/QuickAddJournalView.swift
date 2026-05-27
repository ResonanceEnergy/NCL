import SwiftUI
#if os(macOS)
import AppKit
import UniformTypeIdentifiers

// MARK: - Wave 14G Phase 3 — Quick-add Journal HUD
//
// Cmd+Shift+J anywhere brings up a small floating window. Single text
// field, a kind picker, an importance slider, and Submit. Drag image or
// text onto the surface — text appends, image is included as an inline
// note attachment (data URL stub for v1; real upload endpoint queued).
//
// Auto-dismisses on successful submit. Esc cancels.

struct QuickAddJournalView: View {
    @Environment(\.dismissWindow) private var dismissWindow
    @State private var body: String = ""
    @State private var kind: String = "note"
    @State private var importance: Double = 50
    @State private var submitting = false
    @State private var error: String? = nil
    @State private var hoveringDrop = false
    @State private var attachedImagePath: String? = nil

    private let kinds = ["note", "observation", "lesson", "reflection", "morning_quiz"]
    private let baseURL = URL(string: "http://100.72.223.123:8800")!

    var body: some View {
        VStack(spacing: 12) {
            header
            entryArea
            controlsRow
            if let e = error {
                Text(e).font(.caption).foregroundColor(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            submitRow
        }
        .padding(16)
        .frame(width: 480)
        .background(.ultraThinMaterial)
        .onAppear {
            // Bring window to front + focus the text field on open.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                NSApp.activate(ignoringOtherApps: true)
            }
        }
    }

    private var header: some View {
        HStack {
            Image(systemName: "square.and.pencil")
                .foregroundColor(.blue)
            Text("Quick Add — Journal")
                .font(.headline)
            Spacer()
            Text("\(Int(importance))")
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
        }
    }

    private var entryArea: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 8)
                .fill(Color(NSColor.textBackgroundColor))
                .frame(minHeight: 120)
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(hoveringDrop ? Color.blue : Color.gray.opacity(0.3),
                                lineWidth: hoveringDrop ? 2 : 1)
                )
            if body.isEmpty {
                Text("What's on your mind? (drop text or images here)")
                    .foregroundColor(.secondary)
                    .padding(10)
                    .allowsHitTesting(false)
            }
            TextEditor(text: $body)
                .font(.system(size: 13))
                .padding(8)
                .background(Color.clear)
                .scrollContentBackground(.hidden)
                .frame(minHeight: 120)
        }
        .onDrop(of: [.text, .plainText, .image, .fileURL], isTargeted: $hoveringDrop) { providers in
            handleDrop(providers)
        }
        .overlay(alignment: .bottomTrailing) {
            if let path = attachedImagePath {
                HStack(spacing: 4) {
                    Image(systemName: "paperclip")
                    Text((path as NSString).lastPathComponent)
                        .font(.caption.monospaced())
                    Button {
                        attachedImagePath = nil
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                    }
                    .buttonStyle(.plain)
                }
                .padding(6)
                .background(Color.blue.opacity(0.2))
                .clipShape(Capsule())
                .padding(8)
            }
        }
    }

    private var controlsRow: some View {
        HStack(spacing: 12) {
            Picker("Kind", selection: $kind) {
                ForEach(kinds, id: \.self) { Text($0).tag($0) }
            }
            .pickerStyle(.menu)
            .frame(width: 180)
            Slider(value: $importance, in: 0...100, step: 1) {
                Text("Importance")
            }
        }
    }

    private var submitRow: some View {
        HStack(spacing: 10) {
            Spacer()
            Button("Cancel") {
                dismissWindow(id: "quickadd")
            }
            .keyboardShortcut(.cancelAction)
            Button(submitting ? "Submitting…" : "Submit") {
                Task { await submit() }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(body.trimmingCharacters(in: .whitespaces).isEmpty || submitting)
        }
    }

    // MARK: - Drop handling

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        for provider in providers {
            if provider.canLoadObject(ofClass: NSString.self) {
                _ = provider.loadObject(ofClass: NSString.self) { item, _ in
                    if let s = item as? String {
                        DispatchQueue.main.async {
                            if self.body.isEmpty {
                                self.body = s
                            } else {
                                self.body += "\n" + s
                            }
                        }
                    }
                }
            }
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                    if let data = item as? Data,
                       let url = URL(dataRepresentation: data, relativeTo: nil) {
                        DispatchQueue.main.async {
                            self.attachedImagePath = url.path
                        }
                    }
                }
            }
        }
        return true
    }

    // MARK: - Submit

    private func submit() async {
        submitting = true
        defer { submitting = false }
        var url = baseURL
        url.append(path: "/journal/entries")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var payload: [String: Any] = [
            "body": body,
            "kind": kind,
            "importance": Int(importance),
            "source": "ncl-desktop-quickadd",
        ]
        if let path = attachedImagePath {
            payload["attachment_path"] = path
        }
        do {
            req.httpBody = try JSONSerialization.data(withJSONObject: payload)
        } catch {
            self.error = "encode failed: \(error.localizedDescription)"
            return
        }
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse, http.statusCode >= 200 && http.statusCode < 300 {
                // Success — dismiss
                dismissWindow(id: "quickadd")
                return
            }
            let body = String(data: data, encoding: .utf8) ?? "<no body>"
            self.error = "HTTP error: \(body.prefix(200))"
        } catch {
            self.error = "submit failed: \(error.localizedDescription)"
        }
    }
}

#endif
