Emit Health HRV Trend — Shortcuts action steps

Purpose: emit `ncl.health.hrv_trend` envelope JSON to `iCloud Drive/NCL/events/`.

Actions (in order):
1. Find Health Samples Where
   - Type: Heart Rate Variability
   - Sort: Latest First
   - Limit: 1
2. Get Details of Health Sample → `hrv_value`
3. Get Current Date
   - Format: ISO 8601
4. Set Variable `now_iso`
5. Text
   - Paste template from `examples/health_hrv_template.json`
   - Replace `{{CURRENT_DATETIME}}` with `now_iso`
   - Replace `{{HRV_VALUE}}` with `hrv_value`
6. Set Variable `json_payload`
7. Save File
   - Service: iCloud Drive
   - Path: `NCL/events/`
   - Save As: `[[now_iso]]--ncl.health.hrv_trend.json`
8. (Optional) Show Notification "HRV trend emitted"

Notes
- Requires Health Data access (user must grant permission in Health app).
- Run as a morning automation for best resting HRV data.
