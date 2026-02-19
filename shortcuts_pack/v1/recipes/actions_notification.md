Notification Summary — Shortcuts action steps

Purpose: emit `ncl.notification.summary_daily` aggregate for the current day.

Actions (in order):
1. Get Current Date → Format as `yyyy-MM-dd` (set variable `today_date`).
2. (Manual) Use `Get Notifications` / or manual counting — Shortcuts cannot read system notifications in every case; recommend manual snapshot or use companion app method.
3. Text — paste JSON template from `examples/notification_summary_template.json` and set `date` and `total_count` (and `by_category` if available).
4. Save File → `iCloud Drive/NCL/events/` → filename `[[today_date]]--ncl.notification.summary_daily.json`

Notes
- System notification access is limited via Shortcuts; this action is primarily for manual snapshots or companion-app-assisted exports.
