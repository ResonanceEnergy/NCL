# NCL NuraulCortexLink — One‑Drop Setup

This package bootstraps the stand‑alone product with docs, VS Code tasks, a Python backend skeleton, and Matrix Monitor feeds.

## Quick Start
```bash
python3 onedrop_setup.py install
```

This will:
- Create virtual env
- Install backend deps
- Generate local config & sample data
- Print next commands for running the API and updating metrics

## Structure
- `docs/product/roadmap_100_steps.md` — Comprehensive 100‑step roadmap
- `docs/product/tasks_100.md` — Tasklist with owners & exit criteria skeleton
- `backend/api/` — FastAPI app exposing progress/roadmap endpoints
- `backend/cli/` — CLI utilities for progress updates
- `.vscode/` — Launch & Tasks for dev workflows

## SLOs (initial)
- Cold start ≤ 800 ms (app)
- FTS P95 ≤ 150 ms for 5k notes
- Q&A P95 ≤ 1.5 s (scoped)

## Privacy
Local‑only by default. Exports are human‑readable. Optional E2E sync only on opt‑in.
