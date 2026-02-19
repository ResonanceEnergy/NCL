NFC Ritual — Shortcuts action steps

Purpose: emit `ncl.nfc.ritual` when an NFC tag is scanned (tag_hash only).

Actions (in order):
1. Automation → Create Personal Automation → NFC → Scan Tag (choose one or more tags)
2. Add Action `Get Current Date` → Format ISO-8601 → save as `ts`
3. Text — paste JSON template from `examples/nfc_ritual_template.json` and replace `{{CURRENT_DATETIME}}` with `ts`, fill `tag_hash` and `ritual_id` appropriately.
4. Save File → `iCloud Drive/NCL/events/` → filename `[[ts]]--ncl.nfc.ritual.json`

Notes
- Do NOT store raw NFC payloads or PII; use a salted hash for `tag_hash` on the device if you want consistent identity without revealing the tag contents.
