# NCL Shortcuts Pack v2

Expanded zero-app ingestion pack covering **20 event types** across health, mood,
location, knowledge, tasks, workout, sleep, and social signals.

## What's New vs v1

| Category | v1 | v2 |
| --- | --- | --- |
| Device | 2 | 2 |
| Screen / Notifications | 2 | 2 |
| Focus | 1 | 2 (+daily focus score) |
| Calendar / Calls | 2 | 2 |
| Location | 1 | 2 (+home/away) |
| Health / HRV | 2 | 4 (+mindfulness, +steps carry-forward) |
| Activity / Workout | 0 | 1 (+workout session) |
| Sleep | 0 | 2 (+sleep duration, +regularity) |
| Mood | 0 | 1 (+mood check-in 1–10) |
| Knowledge | 0 | 1 (+quick capture) |
| Tasks | 0 | 1 (+task completed) |
| Social | 0 | 1 (+social interaction metadata) |
| NFC ritual | 1 | 1 |
| **Total** | **10** | **20** |

## How to Use

1. Open Shortcuts on your iPhone.
2. Choose a shortcut from the `templates/` folder.
3. Fill in the `Text` action with your actual values (or wire to a HealthKit / Calendar action).
4. Use "Save File" to write the JSON to `iCloud Drive/Shortcuts/NCL/events/`.
5. The NCL watcher or Companion App picks it up automatically.

Alternatively, use the Companion App's **Capture** tab for guided event entry.

## Emulation (development)

```bash
python shortcuts_pack/v2/emulate_shortcut.py --type ncl.mood.check_in
python shortcuts_pack/v2/emulate_shortcut.py --type ncl.health.mindfulness
python shortcuts_pack/v2/emulate_shortcut.py --type ncl.focus.score
```

## Privacy Guarantees

- **No raw content** — notes/labels capped at 500 chars, no attachments in events.
- **No raw GPS** — location events are home/away transitions + named place labels only.
- **No contact names** — social events carry relationship tiers and counts, not identities.
- **Consent registry** — all capture types respect the NCL consent system (`ncl.consent.change`).
