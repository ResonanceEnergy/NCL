# INTEGRATION DESIGN — future-predictor-council

## Overview
Integration points for $r within the ResonanceEnergy SuperAgency ecosystem.

## Integration Points

### Internal (ResonanceEnergy Portfolio)
- **NCL** — Knowledge base and second brain data sync
- **Matrix Monitor** — Live ops display and status feed
- **SuperAgency flywheel** — Automated development cycles via OPTIMUS/GASKET

### External Services
- **GitHub** — Source control, CI/CD via GitHub Actions

## Data Flow
```
[This Repo] <--> [NCL Knowledge Base] <--> [Matrix Monitor]
[This Repo] <--> [GitHub] <--> [CI/CD Pipeline]
```

## API Contracts
- Agent commits follow Conventional Commits spec
- State stored in state/ directory (local JSON)
- Status exposed via src/flywheel_feed.py → state/flywheel_feed.json

## Auth & Security
- GitHub auth via git credentials manager
- No secrets in code — all via environment variables
- See SECURITY.md for vulnerability reporting
