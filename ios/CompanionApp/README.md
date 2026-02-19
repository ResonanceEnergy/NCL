Companion iOS App — prototype (HealthKit + Notification metadata)

Purpose
- Minimal prototype scaffolding that requests HealthKit read permissions and notification permission, captures metadata-only notification events, and emits NCL envelope-compliant JSON to a local share/export endpoint.

Notes
- This is a skeleton for rapid prototyping. It intentionally does not include networking or storage layers — those should be implemented per your architecture (local-first DB + export).
- Only metadata is collected by default; no raw audio/images/messages are recorded.

Files
- `Sources/CompanionApp/CompanionApp.swift` — SwiftUI App entry
- `Sources/CompanionApp/ContentView.swift` — basic UI for permission requests
- `Sources/CompanionApp/HealthManager.swift` — HealthKit permission + sample fetch stubs
- `Sources/CompanionApp/NotificationManager.swift` — UNUserNotificationCenter hooks (metadata)
- `Info.plist` — minimal usage descriptions

How to open
- Open Xcode and create a new iOS app target, then drop these source files into the project, or use the files as a reference for a real app skeleton.
