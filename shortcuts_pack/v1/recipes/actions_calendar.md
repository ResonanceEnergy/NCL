Emit Calendar Summary — Shortcuts action steps

Purpose: emit `ncl.calendar.event_summary` envelope JSON to `iCloud Drive/NCL/events/`.

Actions (in order):
1. Find Calendar Events Where
   - Start Date is today
2. Count (result → `event_count`)
3. Get Current Date
   - Format: ISO 8601
4. Set Variable `now_iso`
5. Text
   - Paste the template from `examples/calendar_summary_template.json`
   - Replace `{{CURRENT_DATE}}` with today's date (yyyy-MM-dd)
   - Replace `{{CALENDAR_EVENT_COUNT}}` with `event_count`
6. Set Variable `json_payload`
7. Save File
   - Service: iCloud Drive
   - Path: `NCL/events/`
   - Save As: `[[now_iso]]--ncl.calendar.event_summary.json`
8. (Optional) Show Notification "Calendar summary emitted"

Notes
- Use Read access only — never store event titles or attendee names.
- The Shortcut only captures metadata counts, not PII.
