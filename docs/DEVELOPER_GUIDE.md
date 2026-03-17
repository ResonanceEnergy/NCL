# NCL Developer Guide

Getting from `git clone` to a fully running system in under 15 minutes.

---

## Prerequisites

| Tool | Minimum | Notes |
|---|---|---|
| Python | 3.11 | 3.9+ works; 3.11 recommended for match-case + tomllib |
| Git | any | — |
| iOS device | optional | Shortcuts app for live data ingestion |

---

## 1. Clone & Virtual Environment

```bash
git clone https://github.com/ResonanceEnergy/NCL.git
cd NCL

# Create venv
python -m venv .venv

# Activate
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install all deps (dev + runtime)
pip install -r requirements-dev.txt
```

---

## 2. Verify Installation

```bash
# Run the full test suite — should be green in ~3 minutes
python -m pytest tests/ -q --tb=short

# Lint check — should report zero violations
python -m ruff check .
```

Expected output:

```
1706 passed in 183s
All checks passed!
```

---

## 3. Start the Relay Server

```bash
python -m ncl_agency_runtime.runtime.relay_server --port 8787
```

Test it:

```bash
# Health check
curl http://localhost:8787/health

# Emit a sample event
python ncl_agency_runtime/tools/sample_event.py
```

---

## 4. Environment Variables

Create a `.env` file (never commit it):

```bash
# Relay auth (optional — off by default)
NCL_API_KEY=your_secret_key
NCL_API_KEYS_REQUIRED=true

# Relay URL (used by spool client)
NCL_RELAY_URL=http://localhost:8787/event

# Telegram bot (optional)
NCL_TELEGRAM_TOKEN=your_bot_token

# Data directories (override defaults)
NCL_DATA_DIR=~/NCL
NCL_MEMORY_DIR=~/NCL/memory
NCL_SPOOL_DIR=~/NCL/data/spool
NCL_BACKUP_DIR=~/NCL/backups

# Rate limits
NCL_EVENTS_PER_MINUTE=60
NCL_API_CALLS_PER_MINUTE=30
```

Load them before running:

```bash
# Windows PowerShell
Get-Content .env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2]) } }

# Linux / macOS
set -a && source .env && set +a
```

---

## 5. Docker (fastest production path)

```bash
# Build and start all services
docker compose up --build

# Relay only
docker compose up relay

# Send a test event
curl -X POST http://localhost:8787/event \
  -H "Content-Type: application/json" \
  -d '{"schema_version":"ncl.iphone.v1","event_id":"test-001","event_type":"ncl.device.pickup","occurred_at":"2026-03-16T08:00:00Z","payload":{"local_hour":8}}'
```

---

## 6. Repo Structure (quick map)

```
NCL/
├── ncl_agency_runtime/
│   ├── runtime/          # relay_server, mission_runner, autonomous_daemon,
│   │                     # event_spool, matrix_monitor, memory_api …
│   ├── agents/           # super_openclaw_agent, telegram_connector, discord_connector
│   └── fpc/              # Future Predictor Council — forecasting engine
├── schemas/
│   └── ncl.iphone.v1/    # 60 JSON Schema event types + index.json
├── shortcuts_pack/
│   ├── v1/               # 10 shortcuts (original)
│   └── v2/               # 20 shortcuts (expanded)
├── tests/                # pytest suite (1706 tests)
├── tools/                # system_health_check, backup_restore, export, import_data
├── docs/                 # BOT_SETUP, DEVELOPER_GUIDE, IPHONE_SETUP_GUIDE …
├── evaluation/           # 50 golden tasks + harness
├── ios/CompanionApp/     # Swift companion app (PolicyKernel, EventStore, etc.)
├── Dockerfile            # multi-stage relay server image
├── docker-compose.yml    # full stack: relay + missions + daemon
├── ncl_config.json       # master config (override via env vars)
├── requirements-dev.txt  # pinned dev + runtime dependencies
└── CHANGELOG.md          # keep-a-changelog format, SemVer
```

---

## 7. Key Patterns

### Emitting an event from Python

```python
from ncl_agency_runtime.runtime.event_spool import submit_event

submit_event({
    "schema_version": "ncl.iphone.v1",
    "event_type": "ncl.mood.check_in",
    "occurred_at": "2026-03-16T09:00:00Z",
    "payload": {"mood_score": 8, "energy_score": 7, "context": "morning"},
})
```

Events are delivered directly to the relay; if it's offline they're spooled and
drained automatically when the server comes back.

### Running golden task evaluation

```bash
python evaluation_harness.py --all
# or for a single task:
python evaluation_harness.py --task-id T6.1.1
```

### Backup

```bash
python tools/backup_restore.py backup
python tools/backup_restore.py list
python tools/backup_restore.py prune --keep 30
```

---

## 8. Contributing

1. Fork the repo and create a branch off `main`.
2. Write tests for anything you add — target 80%+ coverage on new code.
3. Run `python -m ruff check . && python -m pytest tests/ -q` before pushing.
4. Open a PR — GitHub Actions will run CI automatically.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution guide.
