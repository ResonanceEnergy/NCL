# iPhone Setup Guide

Configure your iPhone to send events to NCL in under 20 minutes —
no jailbreak, no spyware, no raw data leaving your device.

---

## Overview

```
iPhone Shortcuts / Companion App
        │
        │ HTTP POST  (JSON, local Wi-Fi or VPN)
        ▼
NCL Relay Server (:8787)
        │
        ▼
Validated event log  →  AI agents  →  insights
```

All event schemas are **metadata-first** — no raw audio, no raw photos, no GPS
coordinates; only derived signals (step counts, HRV, focus state, etc.).

---

## Option A — Shortcuts Pack v2 (no companion app needed)

### Step 1 — Start the relay server

On your computer:

```bash
cd NCL
python -m ncl_agency_runtime.runtime.relay_server --port 8787
```

Note your machine's local IP (`ipconfig` on Windows, `ifconfig` on Mac).

### Step 2 — Install a shortcut

1. Open the **Shortcuts** app on your iPhone.
2. Tap **+** → **Add Action**.
3. Search for **"Text"** — add it and paste the JSON template from `shortcuts_pack/v2/templates/`.
4. Add a **"Get Contents of URL"** action:
   - **URL**: `http://YOUR_MAC_IP:8787/event`
   - **Method**: POST
   - **Headers**: `Content-Type: application/json`
   - **Body**: `Request Body` → Text (use the Text block from step 3)
5. Optionally add a **"Show Result"** action to see the server response.
6. Tap **Done** and give the shortcut a name (e.g. "NCL Mood Check-in").

### Step 3 — Run the shortcut

Tap the shortcut. You should see `{"ok": true}` in the result if the server is
reachable. The event will appear in `~/NCL/data/event_log/YYYY-MM-DD.ndjson`.

### Step 4 — Add to home screen or automation

- **Home screen**: tap the shortcut → Share → Add to Home Screen.
- **Automation**: Shortcuts → Automation → + → Time of Day (e.g. 8:00 AM for
  daily mood check-in).

---

## Available Shortcuts (v2, 20 total)

| ID | Title | Event type | Trigger suggestion |
|---|---|---|---|
| `mood_checkin` | Mood Check-in | `ncl.mood.check_in` | 8 AM, noon, 9 PM |
| `focus_score` | Daily Focus Score | `ncl.focus.score` | 10 PM |
| `mindfulness_session` | Log Mindfulness | `ncl.health.mindfulness` | After session |
| `home_away` | Arrived / Left Home | `ncl.location.home_away` | NFC tag on door |
| `knowledge_capture` | Quick Capture | `ncl.knowledge.capture` | Share sheet |
| `task_completed` | Task Completed | `ncl.task.completed` | Reminders automation |
| `social_interaction` | Log Interaction | `ncl.social.interaction` | After a call |
| `workout_session` | Log Workout | `ncl.activity.workout` | After workout |
| `sleep_duration` | Log Sleep | `ncl.sleep.duration` | Morning |
| `health_hrv` | HRV Trend | `ncl.health.hrv_trend` | Morning |
| `pickup` | Pickup Event | `ncl.device.pickup` | Continuous (app) |
| `screentime_snapshot` | Screen Time | `ncl.screentime.session` | Daily |
| `focus_change` | Focus Change | `ncl.system.focus_change` | Focus mode change |
| *(+ 7 more)* | … | … | … |

---

## Option B — Companion App (full offline queue + consent UI)

The Swift companion app (`ios/CompanionApp/`) provides:

- **PolicyKernel** — consent registry, kill switches, risk-tier enforcement
- **EventStore** — on-device queue that drains to relay when reachable
- **ReviewQueueView** — review and approve captured events before sending
- **HealthManager** — structured HealthKit bridge (HRV, sleep, activity)
- **BackgroundScheduler** — scheduled automatic capture

### Build (requires Mac + Xcode 15+)

```bash
# Open in Xcode
open ios/CompanionApp/CompanionApp.xcodeproj

# Or build from command line
xcodebuild -scheme CompanionApp -destination "generic/platform=iOS" build
```

Deploy to your device via Xcode or TestFlight.

---

## Security & Privacy

| Guarantee | How it's enforced |
|---|---|
| No raw audio | Shortcuts use label-only payloads; app uses `microphone.presence_label` schema |
| No raw GPS | Location events = place labels + home/away transitions only |
| No contact names | Social events = tier labels + counts only |
| Consent required | `ncl.consent.change` event must be emitted before any capture starts |
| Data sovereignty | All data stays on your local machine by default (no cloud relay) |
| Kill switch | `KillSwitchService.swift` + `PolicyGate` server-side enforcement |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` | Relay not running. Run `python -m ncl_agency_runtime.runtime.relay_server` |
| `Network error` | iPhone and Mac must be on same Wi-Fi, or use a VPN |
| `{"ok": false, "error": "unauthorized"}` | Set `NCL_API_KEYS_REQUIRED=false` or add your key to the shortcut header |
| `{"ok": false, "reason": "…"}` | Schema validation failed — check your JSON against `schemas/ncl.iphone.v1/` |
| Event not appearing in log | Check `~/NCL/data/quarantine/invalid.ndjson` for validation errors |
| Spool not draining | Check `~/NCL/data/spool/` — events queue there when relay is offline |
