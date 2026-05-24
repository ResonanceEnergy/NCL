"""
ncl-sqlite-burnin-verify loop (carved from scheduler.py, W10A-11).

6-hourly invocation of `scripts/sqlite_burn_in_verify.py` against the
cost_ledger + mandates + units_index tables, persisting per-cycle
results to `data/persistence/burnin/verifier-results.jsonl` (with 5MB
rotation) and ntfy-alerting whenever a tracked table's
`jsonl_only_count` grows by more than 200 between cycles — signalling
that the live double-write hook is missing new rows.

The cost_ledger table is intentionally excluded from drift alerting:
its historical pre-flip rows live only in JSONL by design, so the
absolute count is irrelevant and only post-flip drift would matter
(and that's caught by the other two tables sharing the same hook).

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler._running` (bool gate to stop the loop)

Other module-level dependencies:
- `runtime.governance.emergency_stop.EMERGENCY_STOP_EVENT` — pauses the
  cycle while the kill-switch is engaged (the inline closure did the
  same).
- `runtime.notifications.alert_dispatch.enqueue_alert` (best-effort)
- `/opt/homebrew/bin/python3` + `scripts/sqlite_burn_in_verify.py` on
  disk; subprocess timeout 120s, results decoded as JSON.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ...governance.emergency_stop import EMERGENCY_STOP_EVENT

log = logging.getLogger(__name__)

_BURNIN_DIR = Path("/Users/natrix/dev/NCL/data/persistence/burnin")
_SCRIPT_PATH = "/Users/natrix/dev/NCL/scripts/sqlite_burn_in_verify.py"
_PYTHON_BIN = "/opt/homebrew/bin/python3"
_BOOT_DELAY_S = 600  # 10 min cold-start delay
_CYCLE_S = 6 * 3600  # 6h between verifier runs
_EMERGENCY_RECHECK_S = 60  # how often to wake while ESTOP held
_SUBPROCESS_TIMEOUT_S = 120
_ROTATION_BYTES = 5 * 1024 * 1024  # 5 MB soft rotation cap
_DRIFT_ALERT_THRESHOLD = 200  # jsonl_only growth between cycles


async def run(scheduler) -> None:
    """Run the SQLite burn-in verifier loop for the given scheduler.

    The scheduler instance owns the lifecycle flag (`_running`). This
    function is the extracted body of what used to be
    `_sqlite_burnin_verify_loop` defined inline inside
    `Scheduler.start()`.
    """
    _BURNIN_DIR.mkdir(parents=True, exist_ok=True)
    results_path = _BURNIN_DIR / "verifier-results.jsonl"
    # Cold-start delay so first cycle hits AFTER warmstart
    await asyncio.sleep(_BOOT_DELAY_S)
    prev_drift: dict[str, int] = {}
    while scheduler._running:
        if EMERGENCY_STOP_EVENT.is_set():
            await asyncio.sleep(_EMERGENCY_RECHECK_S)
            continue
        try:
            proc = await asyncio.create_subprocess_exec(
                _PYTHON_BIN,
                _SCRIPT_PATH,
                "--table",
                "all",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_S)
            payload = json.loads(stdout_b.decode("utf-8", errors="replace"))
            payload["ts"] = datetime.now(timezone.utc).isoformat()
            # Soft 5 MB rotation guard — mirrors contradicts_index.jsonl
            # pattern in runtime/memory/conflict_resolver.py. Without this
            # the burn-in verifier appends ~1 row/6h indefinitely; in a
            # high-cadence backfill scenario the file can grow unbounded
            # and contribute to Brain RSS pressure.
            if results_path.exists() and results_path.stat().st_size > _ROTATION_BYTES:
                rotated = results_path.with_suffix(".jsonl.1")
                try:
                    if rotated.exists():
                        rotated.unlink()
                    results_path.rename(rotated)
                except Exception as e:
                    log.warning("[BURNIN] rotation failed: %s", e)
            # Append one row per cycle to JSONL
            with results_path.open("a") as f:
                f.write(json.dumps(payload, separators=(",", ":")) + "\n")
            # Per-table drift growth check
            for entry in payload.get("results", []):
                table = entry.get("table", "?")
                div = entry.get("divergence") or {}
                drift = int(div.get("jsonl_only_count", 0) or 0)
                prior = prev_drift.get(table, drift)
                growth = drift - prior
                prev_drift[table] = drift
                log.info(
                    "[BURNIN] %s jsonl_only=%d (delta %+d) sqlite_only=%d match=%s",
                    table,
                    drift,
                    growth,
                    int(div.get("sqlite_only_count", 0) or 0),
                    entry.get("match"),
                )
                # Alert when a tracked table's jsonl_only count grows
                # by >200 between cycles — means live double-write is
                # missing new rows. cost_ledger is excluded (intentional
                # historical drift; only post-flip rows can drift).
                if table != "cost_ledger" and growth > _DRIFT_ALERT_THRESHOLD:
                    try:
                        from ...notifications.alert_dispatch import enqueue_alert

                        enqueue_alert(
                            title=f"SQLite burn-in drift on {table}",
                            body=f"jsonl_only grew {prior}→{drift} (+{growth}) — live double-write may be missing writes",  # noqa: E501
                            priority="3",
                            dedup_key=f"sqlite_burnin_drift_{table}",
                            source="persistence",
                        )
                    except Exception:
                        pass
        except Exception as e:
            log.warning("[BURNIN] verifier cycle failed: %s", e)
        await asyncio.sleep(_CYCLE_S)
