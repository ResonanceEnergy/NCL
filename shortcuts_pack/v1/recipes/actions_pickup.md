Emit Pickup Event — Shortcuts action steps

Purpose: emit `ncl.device.pickup` envelope JSON to `iCloud Drive/NCL/events/`.

Actions (in order):
1. Get Current Date
   - Format: ISO 8601 (yyyy-MM-dd'T'HH:mm:ss'Z')
2. Set Variable `now_iso`
3. Text
   - Paste the `pickup` payload template JSON from `examples/pickup_shortcut_template.json` and replace `{{CURRENT_DATETIME}}` with `now_iso` (use the magic variable).
4. Set Variable `json_payload`
5. Save File
   - Service: iCloud Drive
   - Path: `NCL/events/`
   - Ask Where to Save: Off
   - Save As: `[[now_iso]]--ncl.device.pickup.json`
6. (Optional) Show Notification "Pickup emitted"

Notes
- Use `Replace` filename behavior or set `Ask Where to Save` only if you want manual control.
- The `Text` action must contain a fully-formed JSON object matching `schemas/ncl.iphone.v1/pickup.event.json`.
