# Agent Orchestration Pack

## Components
- `agents/repo_sentry.py` — detects repo changes → per‑repo delta plans
- `agents/daily_brief.py` — aggregates → portfolio daily brief
- `agents/council.py` — evaluates proposals (autonomy/risk/consent)
- `agents/orchestrator.py` — runs sentry + brief
- `bin/run_daily.sh` — daily cycle runner
- `bin/propose.sh` — submit a proposal to council

## Config
Edit `config/settings.json` (set `repos_base` to where your 23 repos live locally).

## Run
```bash
./bin/run_daily.sh
```

Propose an action:
```bash
./bin/propose.sh TESLACALLS2026 financial_actions L2 HIGH "Request to place paper trade for strategy X"
```
