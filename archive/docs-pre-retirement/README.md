# archive/docs-pre-retirement/

**Archived**: 2026-05-23
**Reason**: These 10 root-level docs and 3 doctrine docs described the
pre-retirement "Resonance Energy" architecture — a multi-pillar
ecosystem where NCL was the router/dispatcher for NCC (research), BRS
(tactical revenue), and AAC (trading) pillars. That architecture is
fully retired:

- **BRS** never existed as a deployed service.
- **AAC** integration was shelved; elements (strategy scorers, IBKR
  patterns) were cherry-picked into NCL and now live entirely inside
  this repo.
- **NCC** repo has been removed from the host machine.

NCL is now a **standalone personal-AI brain**, not a pillar router.
See the current authoritative spec: **`CLAUDE.md`** at the repo root.

> Note: this `README.md` itself replaces a same-named "NCL —
> NuRealCortexLink — the four-pillar ecosystem entry point" doc that
> used to sit here. That file is listed in the inventory table below
> and was overwritten by this archive index when the directory was
> finalised.

---

## File inventory

| File                              | What it described then                                                                                  | What's true now (see CLAUDE.md)                                                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `README.md` (the old one)         | "Welcome to Resonance Energy — the four-pillar AI ecosystem." Linked all pillars + dispatch flow.       | NCL is standalone. No pillars. CLAUDE.md is the entry point. (This file overwrote that doc.)    |
| `RESONANCE_ENERGY_SOT.md`         | "Single source of truth" for the multi-pillar architecture, authority chain, mandate dispatch.          | The authority chain is `NATRIX → NCL Brain → FirstStrike iOS`. CLAUDE.md is the new SoT.        |
| `RUNTIME_GUIDE.md`                | How to start the four-pillar runtime: NCL + NCC + BRS + AAC LaunchAgents, ports 8800/8765/8000/8080.    | Only NCL (8800) and the relay (8787) run. `make run` covers the full surface for dev.            |
| `BUILD_SUMMARY.md`                | Build status across all four pillars — which subsystems were green/yellow/red.                          | There is one repo. `make test` + `/system/health/rollup` give the same signal for the Brain.    |
| `INDEX.md`                        | Cross-pillar index of every named artifact (mandates, councils, signals) and which pillar owned each.   | All artifacts are Brain-internal. ChromaDB + units.jsonl + mandates.json are the index now.     |
| `MANIFEST.txt`                    | Filesystem manifest across the four pillar repos — which directories belonged to which pillar.         | One repo, one manifest. `tree` is the manifest.                                                 |
| `STRUCTURE.md`                    | Directory-by-directory walkthrough of all four pillar repos and the shared `doctrine/` directory.       | Walk `runtime/` instead. DEVELOPING.md links the subsystems.                                   |
| `CONTEXT.md`                      | "How to give Claude the right context when working across pillars." Listed which files to pre-load.     | CLAUDE.md is the context. `/Users/natrix/Projects/FirstStrike/CLAUDE.md` covers the iOS side.   |
| `AUDIT_brain.md`                  | Static audit of the Brain code, framed as one pillar of four.                                          | Superseded by `AUDIT_full.md` (current Brain-only audit) at the repo root.                      |
| `WORKSPACES_INDEX.md`             | Index of `workspaces/execution-pipeline/` MWP stages used by the orchestrator.                          | `workspaces/execution-pipeline/` is archived under `archive/strike-point-pre-merge/`.            |
| `doctrine/AGENTS.md`              | Pillar-by-pillar agent catalog (which named agent runs in which pillar).                                | Every agent is a loop in `runtime/scheduler.py`. See CLAUDE.md "Autonomous Scheduler" table.    |
| `doctrine/paperclip.config.json`  | Pillar-dispatch routing rules for Paperclip (the agent orchestrator).                                   | Paperclip was never deployed. `runtime/cost_tracker.py` owns budget. The adapter is dead code.  |
| `doctrine/NARTIX-Ecosystem-Build-Plan.md` | The multi-quarter build plan to ship all four pillars: NCL Q1, BRS Q2, AAC Q3, NCC Q4.          | None of Q2-Q4 shipped. NCL absorbed the user-facing surface area; the rest is shelved.          |

---

## How to read this archive

These docs are useful if you're spelunking the git history of a
decision — e.g. "why does `PillarType` still have an `NCC` value?" —
or if you're auditing what was intentional vs accidental in the
retirement.

For anything else, **read CLAUDE.md**. The active spec covers:

- Identity (standalone, no pillars)
- 32 autonomous loops (with cadence + current status)
- Active API endpoints (current shape and known issues)
- Memory subsystem (25K capacity, 7-tier authority, schema versioning)
- Council system (Claude chairs, role map, write-back path)
- Cost tracker (replaced Paperclip)
- Calendar system
- Strike-point pipeline (merged into Brain, `auto_flow=True`)
- "DO NOT TOUCH — Critical Rules" — the seven rules previous sessions
  broke and the reasoning behind each

---

## Cross-references

- `CLAUDE.md` — current spec (repo root)
- `DEVELOPING.md` — onboarding workflow (repo root)
- `docs/COUNCIL_ARCHITECTURE.md` — council runner
- `docs/PERSISTENCE.md` — SQLite foundation
- `docs/SECRETS.md` — env + keychain
- `archive/strike-point-pre-merge/README.md` — file-queue pipeline retirement
- `archive/launchd-disabled/README.md` — unloaded LaunchAgents
