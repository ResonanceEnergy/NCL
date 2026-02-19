Shortcuts Automation Pack — v1 (zero-app ingestion)

Purpose
- Provide a small set of Shortcuts + documentation so an iPhone user can emit NCL-compliant `ncl.iphone.v1` events from Shortcuts (Files, iCloud Drive, or share to app).

Included shortcuts (manifests + templates)
- Pickup event — emits `ncl.device.pickup`
- Screen Time snapshot — emits `ncl.screentime.session` / `ncl.screentime.total`
- Notification snapshot — emits `ncl.notification.*` aggregates (requires manual snapshot)
- NFC ritual — emits `ncl.nfc.ritual` event
- Focus change — emits `ncl.system.focus_change`

Recipes & import
- See `shortcuts_pack/v1/recipes/IMPORT_INSTRUCTIONS.md` for step-by-step import instructions.
- Per-shortcut action steps & sample payloads are in `shortcuts_pack/v1/recipes/` and `shortcuts_pack/v1/examples/` respectively.

How to use (quick)
1. Open Shortcuts on your iPhone and create a new shortcut using the example JSON payloads in `shortcuts_pack/v1/examples/`.
2. Add an action "Save File" or "Text" → save the JSON output to iCloud/Files (folder: `NCL/events/`).
3. On the local machine, NCL watches `shortcuts_pack/v1/events/` (or use the companion app import) and ingests events.

Emulation
- Use `python shortcuts_pack/v1/emulate_shortcut.py --type ncl.device.pickup` to write a sample event into `shortcuts_pack/v1/events/`.

Templates
- We provide JSON‑based Shortcuts templates in `shortcuts_pack/v1/templates/` for quick import and iteration:
  - `capture_text.shortcut.json` — text capture
  - `capture_photo_ref.shortcut.json` — photo reference (no raw image in event)
  - `capture_voice_label.shortcut.json` — label-only voice capture
  - `create_task.shortcut.json` — create task → event
  - `start_review.shortcut.json` — start weekly review
  - `quick_tag.shortcut.json` — quick tag for inbox events

How to use the templates
1. On iPhone: open Shortcuts → Create Shortcut → Add actions that mirror the `event_template` fields from the JSON files.
2. Use the "Text" action to produce the JSON payload and "Save File" to write to `iCloud Drive/Shortcuts/NCL/events/` (or use the App Group path for the Companion App).
3. The Companion App or the watcher/emulator will ingest the JSON and validate against `schemas/ncl.iphone.v1/`.

Exporting `.shortcut` files (macOS required)
- The repo provides JSON templates so anyone can replicate Shortcuts actions without macOS. If you want true `.shortcut` files, export them from the Shortcuts app on macOS and add them to `shortcuts_pack/v1/releases/` (note: I can generate these if you provide a macOS export or ask me to produce the JSON → placeholder .shortcut wrapper for later replacement).

Notes
- Templates intentionally emit `photo_ref` and `label-only` payloads — no raw audio/images in event bodies by default.
- Keep Shortcuts as a capture layer only; enforcement (PolicyKernel, consent, execution) lives inside the Companion App.

