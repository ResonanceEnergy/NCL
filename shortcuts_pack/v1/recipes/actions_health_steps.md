Emit Steps Count — Shortcuts action steps

Purpose: emit `ncl.activity.steps` envelope JSON to `iCloud Drive/NCL/events/`.

Actions (in order):
1. Find Health Samples Where
   - Type: Step Count
   - Start Date: Beginning of Today
   - End Date: Current Date
2. Calculate → Sum (result → `step_count`)
3. Get Current Date
   - Format: ISO 8601
4. Set Variable `now_iso`
5. Text
   - Paste template from `examples/health_steps_template.json`
   - Replace `{{CURRENT_DATE}}` with today's date (yyyy-MM-dd)
   - Replace `{{STEP_COUNT}}` with `step_count`
6. Set Variable `json_payload`
7. Save File
   - Service: iCloud Drive
   - Path: `NCL/events/`
   - Save As: `[[now_iso]]--ncl.activity.steps.json`
8. (Optional) Show Notification "Steps emitted"

Notes
- Requires Health Data access.
- Best run at end of day for full daily count.
