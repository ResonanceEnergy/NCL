# archive/strike-point-pre-merge/

**Archived**: 2026-05-23
**Reason**: The pump → mandate → pillar file-queue pipeline was MERGED
into the NCL Brain. The Brain's `POST /pump` endpoint
(`runtime/api/routes.py:795`) with `auto_flow=True` now runs the entire
strike-point flow in-process — council spawn, mandate extraction,
memory persistence — with no external orchestrator process and no
mandate-generation file queue.

The previous architecture was an external watcher process picking up
files from `mandate-generation/input/`, handing them to a separate
orchestrator process that moved them through MWP stages
(`workspaces/execution-pipeline/`), and dispatching mandates to NCC,
BRS, and AAC pillar intake directories. That whole apparatus is gone.

---

## File inventory

| Path                                          | What it was                                                  |
| --------------------------------------------- | ------------------------------------------------------------ |
| `pump_watcher.py`                             | LaunchAgent process that polled `mandate-generation/input/` for new pump prompts, validated payloads, and handed them to the orchestrator. Replaced by Brain `POST /pump`. |
| `strike_point_orchestrator.py`                | LaunchAgent process that ran the strike-point flow: council spawn, mandate extraction, MWP stage progression, pillar dispatch. Replaced by Brain `brain.py:receive_pump_prompt(auto_flow=True)`. |
| `execution_loop.py`                           | Copilot/Claude-Code subprocess bridge that polled mandate-output for new mandates and shelled out to a code-executor agent. Dead since May 22 (manual-mode fallback). |
| `mandate-generation/`                         | Directory tree (`input/`, `processed/`, `failed/`, `output/`) — the file queue itself. Preserved with 21 historical processed pumps and 5 stuck AAC War Room sweeps for forensics. |
| `workspaces/execution-pipeline/`              | MWP stage directories (`stage-1-research/`, `stage-2-debate/`, `stage-3-decision/`, `stage-4-execution/`). Mandate hand-off scaffolding. Empty in practice — orchestrator never used the file-based stages, only the in-memory ones. |
| `test_pump_watcher.py`                        | Pytest suite for the watcher process. |
| `dispatch/`, `aac-intake/`, `brs-intake/`     | Pillar-dispatch routers and intake stubs. NCC/BRS/AAC are retired (BRS never shipped, AAC integration shelved, NCC repo removed). |
| `PILLAR_DISPATCH.md`, `test_pillar_dispatch.py` | The pillar router doc + test. Both describe a no-op now. |
| `council_runner/`                             | Sprint-4 v1 parallel-agent council (Planner / Skeptic / Risk) — archived 2026-05-23 by W5-06. The pack now owns persistence + replay (`runtime/council_pack/store.py`, `replay.py`, `models.py`); the v1 agents survive only as a deprecated back-compat shim at `runtime/council_pack/legacy.py` (`run_parallel_council`). Contains `__init__.py`, `agents.py`, `models.py`, `replay.py`, `store.py`, `example_usage.py`, plus three markdown docs (`BUILD_SUMMARY.md`, `COUNCIL_RUNNER_V1.md`, `INDEX.md`). |

---

## Why the merge

- **Latency**: the file-queue added 60-300 s between pump submission
  and council spawn (watcher poll interval + orchestrator handoff).
  In-process is sub-second.
- **Reliability**: 5 AAC sweeps were stuck in `failed/` because the
  orchestrator crashed mid-batch. With no in-process queue, the same
  crash is contained to one HTTP request.
- **No remaining pillars**: with NCC removed, BRS retired, AAC
  shelved, there's nothing to dispatch *to*. The file queue was
  load-bearing scaffolding for a system that no longer exists.
- **Memory native**: every council output now flows directly to
  MemoryStore via the async writer, with authority-tier and
  schema-version stamping. The file queue had no such hooks.

---

## Current canonical strike-point path (do NOT re-route around this)

```
iOS POST /pump
  → runtime/api/routes.py:receive_pump_prompt
  → runtime/ncl_brain/brain.py:receive_pump_prompt(auto_flow=True)
  → spawn_council_session()
  → _extract_mandates_from_council()
  → async_writer.enqueue(...)  # memory persistence
  → return CouncilBrief
```

The Brain's `auto_flow=True` IS the strike-point pipeline. Reviving
the orchestrator would mean routing **around** this path, not through
it — which is a regression and explicitly forbidden by CLAUDE.md
"DO NOT TOUCH" §6.

---

## Revival procedure (only if you really mean it)

If — for some reason — the file-queue architecture must come back
(say, to gate council spawn behind a separate process boundary, or
to multi-target dispatch to a new external pillar):

1. **Move the code back to `runtime/`**:
   ```bash
   mv archive/strike-point-pre-merge/pump_watcher.py runtime/
   mv archive/strike-point-pre-merge/strike_point_orchestrator.py runtime/
   mv archive/strike-point-pre-merge/execution_loop.py runtime/
   mv archive/strike-point-pre-merge/test_pump_watcher.py tests/
   ```
2. **Re-enable the LaunchAgents**:
   ```bash
   cp archive/launchd-disabled/com.resonanceenergy.ncl-watcher.plist \
      ~/Library/LaunchAgents/
   cp archive/launchd-disabled/com.resonanceenergy.ncl-orchestrator.plist \
      ~/Library/LaunchAgents/
   launchctl bootstrap gui/$UID \
      ~/Library/LaunchAgents/com.resonanceenergy.ncl-watcher.plist
   launchctl bootstrap gui/$UID \
      ~/Library/LaunchAgents/com.resonanceenergy.ncl-orchestrator.plist
   ```
3. **Rebuild the `mandate-generation/` directory tree** at the repo
   root:
   ```bash
   mkdir -p mandate-generation/{input,processed,failed,output}
   ```
4. **Disable the Brain's `auto_flow`** for the pump endpoint — either
   default `auto_flow=False` on `receive_pump_prompt` or add an env
   flag (`NCL_PUMP_AUTO_FLOW=false`) so the Brain stops running the
   in-process strike-point and the watcher takes over.
5. **Restart the Brain**:
   ```bash
   make restart-brain
   ```
6. **Verify the watcher picks up a test pump**:
   ```bash
   echo '{"pump_id":"test","content":"smoke"}' \
     > mandate-generation/input/test.json
   sleep 5
   ls mandate-generation/processed/
   ```

**Critical**: this is a re-architecture, not a "restoration". Treat
it as a fresh project with a design doc and a rollout plan — do not
do it as a side-effect of another change. Update CLAUDE.md "DO NOT
TOUCH" §6 in the same commit, or back out.
