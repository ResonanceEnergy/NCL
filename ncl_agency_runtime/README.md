# NCL AGENCY Runtime (Mac v1 — Local‑Only)

Generated: 2026-02-18T13:28:31 (GMT‑07)

This bundle provides a **local‑only** (zero cloud) runnable starter for the NCL Agency framework:

✅ Local Wi‑Fi event relay (iPhone Shortcuts → Mac) via HTTP POST to localhost/LAN
✅ Append‑only NDJSON event log writer
✅ Schema validator + quarantine
✅ Mission queue + mission runner skeleton
✅ Daily Brief v0 (rules-based placeholder) + report writer
✅ launchd plists for always‑on relay + scheduled jobs
✅ Sample event generator for end‑to‑end testing

## Doctrine‑Lock: ZERO CLOUD DATA
- No cloud-sync paths are used.
- Canonical data lives under `~/NCL/` only.

## Quick Start (10 minutes)
1) Unzip.
2) Run the bootstrap:

```bash
cd NCL_AGENCY_Runtime_Mac_v1_LocalOnly
bash scripts/bootstrap_mac.sh
```

3) Start the relay (foreground test):

```bash
python3 runtime/relay_server.py --host 0.0.0.0 --port 8787
```

4) Send a test event:

```bash
python3 tools/sample_event.py --url http://localhost:8787/event
```

5) Run a Daily Brief for today:

```bash
python3 runtime/mission_runner.py --mission missions/queue/daily_brief_today.json
```

6) Optional: install launchd services:

```bash
bash scripts/install_launchd.sh
launchctl load -w ~/Library/LaunchAgents/ncl.relay.plist
launchctl load -w ~/Library/LaunchAgents/ncl.nightly.plist
```

## iPhone Shortcut (local‑only)
Create a Shortcut that does:
- Dictionary → your event payload
- Get Contents of URL:
  - URL: `http://<MAC_LAN_IP>:8787/event`
  - Method: POST
  - Request Body: JSON

See: `docs/iphone_shortcut_recipe.md`

