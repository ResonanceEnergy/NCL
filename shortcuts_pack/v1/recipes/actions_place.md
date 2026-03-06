Emit Place Fingerprint — Shortcuts action steps

Purpose: emit `ncl.connectivity.place_fingerprint` envelope JSON to `iCloud Drive/NCL/events/`.

Actions (in order):
1. Get Current Date
   - Format: ISO 8601
2. Set Variable `now_iso`
3. Get Network Details
   - Wi-Fi Network Name (SSID) → Set Variable `raw_ssid`
4. Generate Hash
   - Input: `raw_ssid`
   - Algorithm: SHA-256
   - Set Variable `ssid_hash`
5. Text
   - Paste template from `examples/place_fingerprint_template.json`
   - Replace `{{CURRENT_DATETIME}}` with `now_iso`
   - Replace `{{WIFI_SSID_SHA256}}` with `ssid_hash`
6. Set Variable `json_payload`
7. Save File
   - Service: iCloud Drive
   - Path: `NCL/events/`
   - Save As: `[[now_iso]]--ncl.connectivity.place_fingerprint.json`
8. (Optional) Show Notification "Place fingerprint emitted"

Notes
- NEVER store the raw SSID. Only the SHA-256 hash.
- The Shortcut can be triggered via NFC tag or Automation (arrive/leave).
