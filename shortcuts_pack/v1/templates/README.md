Shortcuts Templates — JSON (templates/)

Purpose
- Provide ready-to-edit JSON templates that produce canonical `ncl.iphone.v1` envelopes when used inside Shortcuts.

Files
- `capture_text.shortcut.json` — text capture example
- `capture_photo_ref.shortcut.json` — photo reference example
- `capture_voice_label.shortcut.json` — voice-label example
- `create_task.shortcut.json` — create task example
- `start_review.shortcut.json` — start review trigger
- `quick_tag.shortcut.json` — tagging helper

How to convert template → Shortcut
1. Open a template and copy the `event_template` JSON.
2. In Shortcuts, add a "Text" action and paste the JSON; replace placeholder tokens ({{INPUT_TEXT}}, {{UUID}}, etc.).
3. Add a "Save File" action (iCloud/Files) and write the JSON to `Shortcuts/NCL/events/` or a configured App Group location.
4. Optionally, add Quick Actions / Widgets to call the Shortcut faster.

Notes
- These templates avoid placing raw image/audio data into event bodies; they reference file URIs instead.
- To generate `.shortcut` packaged exports, use macOS Shortcuts app and add exported files to `shortcuts_pack/v1/releases/`.
