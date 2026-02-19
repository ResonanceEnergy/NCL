NCL Shortcuts Pack v1 — Release notes (draft)

Version: 0.1.0
Release date: 2026-02-19 (draft)

Summary
- Zero‑app Shortcuts pack to emit `ncl.iphone.v1` envelope events from iPhone Shortcuts into `iCloud Drive/NCL/events/`.

Included
- QuickPaste JSON snippets for easy Copy→Paste into Shortcuts Text actions.
- Example payloads and recipe steps for NFC, Focus, ScreenTime, Pickups, and Notifications.
- Emulator script to write sample events locally for testing.

How to publish
- Export `.shortcut` files from the Shortcuts app on macOS and add them to the release assets under the expected filenames (see `releases/shortcuts_pack_v1_zip_manifest.json`).
- Add checksums to the release manifest before publishing.

Notes
- This release contains metadata-only events by default (no content retention).  
- Companion app prototype exists for higher-fidelity ingestion if you later choose shipping mode B.
