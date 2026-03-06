Emit Call Metadata — Shortcuts action steps

Purpose: emit `ncl.call.metadata` envelope JSON to `iCloud Drive/NCL/events/`.

Actions (in order):
1. Get Current Date
   - Format: ISO 8601
2. Set Variable `now_iso`
3. Ask for Input
   - Direction: "Was the call inbound, outbound, or missed?"
   - Options: inbound, outbound, missed
   - Set Variable `call_direction`
4. Ask for Input
   - Duration: "How long was the call in seconds?"
   - Type: Number
   - Set Variable `call_duration`
5. Text
   - Paste template from `examples/call_metadata_template.json`
   - Replace `{{CURRENT_DATETIME}}` with `now_iso`
   - Replace `{{CALL_DIRECTION}}` with `call_direction`
   - Replace `{{CALL_DURATION}}` with `call_duration`
   - Replace `{{CONTACT_HASH}}` with empty string (no PII)
6. Set Variable `json_payload`
7. Save File
   - Service: iCloud Drive
   - Path: `NCL/events/`
   - Save As: `[[now_iso]]--ncl.call.metadata.json`
8. (Optional) Show Notification "Call metadata emitted"

Notes
- Manual entry only. No automated call log access in Shortcuts.
- Contact hash is intentionally left empty for privacy.
