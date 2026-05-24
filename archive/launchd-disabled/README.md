# archive/launchd-disabled/

**Archived**: 2026-05-23
**Reason**: These two LaunchAgent plists were `launchctl bootout`'d on
2026-05-23 when the Brain absorbed their functionality. They drove the
old strike-point file-queue pipeline; with the pipeline merged into
the Brain (see `archive/strike-point-pre-merge/README.md`), the
LaunchAgents have nothing to do.

The plists are preserved here verbatim so the configuration is
recoverable if revival is ever needed.

---

## Inventory

| Plist                                            | Process it ran                                                | Why unloaded                                                                                                  |
| ------------------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `com.resonanceenergy.ncl-watcher.plist`          | `python3 runtime/pump_watcher.py` (KeepAlive)                | The Brain `POST /pump` endpoint now receives pumps directly. The watcher was polling `mandate-generation/input/` for files that no producer writes anymore. |
| `com.resonanceenergy.ncl-orchestrator.plist`     | `python3 runtime/strike_point_orchestrator.py` (KeepAlive)   | The Brain `brain.py:receive_pump_prompt(auto_flow=True)` now runs the full strike-point flow in-process. The orchestrator process is redundant. |

The companion source files (`pump_watcher.py`,
`strike_point_orchestrator.py`) live in
`archive/strike-point-pre-merge/`.

---

## What's still loaded

For reference, here's the LaunchAgent surface that remains live on
the Mac Studio host:

| Plist                                            | What it does                                                     |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| `com.resonanceenergy.ncl-brain.plist`            | Brain API (`uvicorn runtime.api.routes:versioned_app`) on :8800. |
| `com.resonanceenergy.relay.plist`                | Pump relay on :8787 (legacy fallback, idle by default).          |
| `com.resonanceenergy.ncl-councils.plist`         | Council sweep, every 6h.                                         |

(The Brain's internal 32-loop scheduler also runs a council
auto-loop on a 5-minute poll, so the LaunchAgent sweep is mostly a
safety net.)

---

## Revival procedure (only if you really mean it)

If the file-queue strike-point pipeline must come back (see the
revival procedure in `archive/strike-point-pre-merge/README.md` for
the full picture), re-load these LaunchAgents:

```bash
# 1. Copy plists back into the LaunchAgents directory
cp archive/launchd-disabled/com.resonanceenergy.ncl-watcher.plist \
   ~/Library/LaunchAgents/
cp archive/launchd-disabled/com.resonanceenergy.ncl-orchestrator.plist \
   ~/Library/LaunchAgents/

# 2. Bootstrap them into the user session
launchctl bootstrap gui/$UID \
   ~/Library/LaunchAgents/com.resonanceenergy.ncl-watcher.plist
launchctl bootstrap gui/$UID \
   ~/Library/LaunchAgents/com.resonanceenergy.ncl-orchestrator.plist

# 3. Verify they came up
launchctl print gui/$UID/com.resonanceenergy.ncl-watcher
launchctl print gui/$UID/com.resonanceenergy.ncl-orchestrator
```

Prerequisites before doing the above:

1. Move `pump_watcher.py` and `strike_point_orchestrator.py` back to
   `runtime/` (or update each plist's `ProgramArguments` to point at
   their archive location — not recommended).
2. Recreate the `mandate-generation/{input,processed,failed,output}/`
   directory tree at the repo root.
3. Disable the Brain's `auto_flow` for pump intake — otherwise both
   the Brain and the watcher will process the same pump and you'll
   get duplicate council sessions + double-billed LLM costs.

To unload again later:

```bash
launchctl bootout gui/$UID/com.resonanceenergy.ncl-watcher
launchctl bootout gui/$UID/com.resonanceenergy.ncl-orchestrator
rm ~/Library/LaunchAgents/com.resonanceenergy.ncl-{watcher,orchestrator}.plist
```

---

## Cross-references

- `archive/strike-point-pre-merge/README.md` — code that these
  plists ran, plus the rationale for the merge.
- `CLAUDE.md` — "DO NOT TOUCH — Critical Rules" §6 forbids casual
  revival of this pipeline.
- `CLAUDE.md` — "Infrastructure → Services (Mac LaunchAgents)" table
  lists the current live + archived plists.
