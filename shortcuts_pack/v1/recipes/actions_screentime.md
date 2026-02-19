Screen Time Snapshot — Shortcuts action steps

Purpose: emit `ncl.screentime.session` or `ncl.screentime.total` event.

Actions (in order):
1. (Optional) Ask for Input — pick session start / end times, or use `Get Current Date` for `end` and `Date` calculation for `start`.
2. Calculate `duration` (end - start) in seconds.
3. Text — paste JSON template from `examples/screentime_shortcut_template.json` and populate `start`, `end`, `duration_s`, and `top_app_hash` (use a short hash of the app name if desired).
4. Save File → `iCloud Drive/NCL/events/` → filename `[[end_iso]]--ncl.screentime.session.json`
5. (Optional) Show Result / Quick Look

Notes
- If you rely on Screen Time export, use the exported CSV to create a daily `ncl.screentime.total` event instead of session-by-session.
- Keep `top_app_hash` opaque (sha256 of bundle id) so no PII is stored.
