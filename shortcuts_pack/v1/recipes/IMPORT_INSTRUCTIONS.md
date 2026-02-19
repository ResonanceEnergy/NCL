NCL Shortcuts Pack v1 — Import & Install Instructions

Goal: create Shortcuts on your iPhone that emit `ncl.iphone.v1` envelope JSON into `iCloud Drive -> NCL/events/` so the local NCL process can ingest them.

General approach (quick):
1. Open Shortcuts on iPhone → + to create a new Shortcut.
2. Use the provided `Text` action and paste the JSON payload template from the corresponding `examples/*.json` file.
3. Add `Get Current Date` (or use provided template tokens) and format as ISO-8601 if needed.
4. Add `Save File` → set **Service** = iCloud Drive, **Path** = `NCL/events/` and construct filename with timestamp (e.g. `2026-02-19T08-04-12Z--ncl.device.pickup.json`).
5. Optionally add `Show Notification` / `Quick Look` for visual confirmation.
6. Save Shortcut and add it to an Automation trigger if desired (NFC, Focus change, Arrive/Leave, Low Power Mode).

Automation setup examples
- NFC ritual: Shortcuts → Automation → Create Personal Automation → NFC → Scan → Select the shortcut you created.  
- Focus change: Automation → When Focus changes → select `Focus` name and attach `Emit Focus Change` shortcut.  
- Low Power Mode: Automation → Low Power Mode → On/Off → attach a shortcut.

File naming pattern (recommended):
- `{ISO8601UTC}--{event_type}.json` e.g. `2026-02-19T08-04-12Z--ncl.device.pickup.json`

Where files land locally
- Save to iCloud Drive folder `NCL/events/` (default) so the desktop/local NCL watcher can ingest events automatically.

Troubleshooting
- If Shortcuts can't write to iCloud: give Shortcuts Files access in iOS Settings → Shortcuts.  
- If events are not picked up by NCL: check `shortcuts_pack/v1/events/` (emulator) or the `NCL/events/` iCloud folder on your mac/PC.

Manual import note
- If you prefer, create the shortcut manually by following the per-shortcut "Action steps" files in `shortcuts_pack/v1/recipes/`.
