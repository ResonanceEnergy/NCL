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

Notes
- This pack is intentionally non-binary: share the JSON payload format so users can reconstruct the Shortcuts action manually.
- If you want, I can export `.shortcut` files (requires an Apple-environment export).
