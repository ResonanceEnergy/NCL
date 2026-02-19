Focus Change — Shortcuts action steps

Purpose: emit `ncl.system.focus_change` when a Focus mode toggles.

Actions (in order):
1. Automation → Create Personal Automation → When Focus Changes → Select Focus(es).
2. Add the `Get Current Date` action and format as ISO-8601.
3. Text — paste JSON template from `examples/focus_change_template.json` and populate `timestamp`, `focus_name`, `action` (activated/deactivated) and `trigger`.
4. Save File → `iCloud Drive/NCL/events/` → filename `[[timestamp]]--ncl.system.focus_change.json`

Notes
- Use this automation for role-shift detection in NCL; pair with `Focus Filter` mappings to tag role (work/personal).
