QuickPaste snippets for Shortcuts — usage

These files are copy-ready JSON snippets you can paste into a Shortcuts "Text" action. Replace the placeholder tokens with Shortcuts magic variables where indicated.

How to use
1. Open the Shortcuts app and create a new Shortcut.
2. Add a `Get Current Date` action and format it to ISO-8601 if needed; save as a variable (e.g. `now_iso`).
3. Add a `Text` action and paste the contents of the relevant QuickPaste `.txt` file.
4. Replace placeholder tokens like `{{CURRENT_DATETIME}}` or `{{TOP_APP_HASH}}` with the corresponding magic variables.
5. Add a `Save File` action -> iCloud Drive -> `NCL/events/` and set filename to `[[now_iso]]--{event_type}.json`.

Available snippets
- `pickup_quickpaste.txt` — `ncl.device.pickup`
- `screentime_quickpaste.txt` — `ncl.screentime.session`
- `notification_quickpaste.txt` — `ncl.notification.summary_daily`
- `nfc_ritual_quickpaste.txt` — `ncl.nfc.ritual`
- `focus_change_quickpaste.txt` — `ncl.system.focus_change`

Notes
- Keep the envelope fields intact; do not paste any non-JSON text into the `Text` action.  
- For privacy, `app_hash` and `tag_hash` should be opaque (e.g. SHA-256 of bundle id or salted tag id).
