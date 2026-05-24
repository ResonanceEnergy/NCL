# Pillar Dispatch — NCL → NCC (NCC-only as of 2026-05-23)

Status as of 2026-05-23. Authority: NCL is the only dispatch source.
Implementation lives in `runtime/dispatch/pillar_router.py`.

> **Retirement note** — BRS and AAC were retired on **2026-05-23** per
> NATRIX directive ("no orphan them we dont use them"). NCL now ships
> mandates **only to NCC**. Any attempt to dispatch with
> `pillar in {BRS, AAC}` raises `UnknownPillarError`, the `/mandates`
> endpoint returns HTTP 400, and `PillarType("brs"|"aac")` raises
> `ValueError`. Historic memory units tagged BRS/AAC are preserved as-is
> for back-compat; no migration is performed.

Earlier in 2026 `strike_point_orchestrator.dispatch_mandate()` hard-coded
the NCC intake directory regardless of `mandate.pillar`, so the NCC
silently absorbed everything. `PillarRouter` was introduced to make BRS
and AAC first-class — and is now scoped back down to NCC-only.

## Pillar map

| Pillar | Default intake dir                                              | Override env var      | Webhook env var     | Consumer            |
|--------|-----------------------------------------------------------------|-----------------------|---------------------|---------------------|
| NCC    | `$HOME/Projects/ncc-server/mandate-intake/`                     | `NCC_INTAKE_DIR`      | `NCC_WEBHOOK_URL`   | NCC server          |

`NCL_BASE` defaults to `$HOME/dev/NCL`.

## Dispatch contract

Each `dispatch()` call produces (at most) two side effects:

1. **File write** (always attempted) — atomic write to
   `<intake_dir>/<mandate_id>.json` via temp + rename. Idempotent: if the
   target file already exists, NCL leaves it untouched and reports
   `already_written=true`.
2. **Webhook POST** (optional) — best-effort POST to `NCC_WEBHOOK_URL`
   if configured, 10s timeout. Failure does not abort the dispatch.

A single `CircuitBreaker` (3 consecutive failures, 600s cooldown) covers
both write and webhook. While open, `dispatch()` short-circuits with
`circuit_open=true` — no file write, no webhook attempt. Telemetry still
ticks `failed_total`.

## JSON schema — mandate intake file

The file written to the intake dir is the full Pydantic `Mandate` model
serialized via `model_dump(mode="json")`, plus a `_dispatched_at`
timestamp. Example:

```json
{
  "mandate_id": "MANDATE-2026-009",
  "pillar": "NCC",
  "priority": 2,
  "priority_level": "P2",
  "title": "Ship Q3 onboarding flow",
  "objective": "Implement onboarding pipeline...",
  "success_criteria": ["...", "..."],
  "deadline": "2026-09-30T23:59:59Z",
  "resources": {"budget_usd": 500},
  "status": "active",
  "version": 3,
  "created_at": "2026-05-23T14:12:01Z",
  "updated_at": "2026-05-23T14:25:11Z",
  "source_pump_id": "PUMP-2026-05-23-xyz",
  "status_history": [
    {"from": "draft", "to": "pending_approval", "reason": "...", "timestamp": "..."},
    {"from": "pending_approval", "to": "active", "reason": "approved", "timestamp": "..."}
  ],
  "_dispatched_at": "2026-05-23T14:25:11Z"
}
```

## Webhook payload

When `NCC_WEBHOOK_URL` is set, NCL POSTs the following JSON:

```json
{
  "type": "mandate_dispatch",
  "pillar": "NCC",
  "mandate_id": "MANDATE-2026-009",
  "title": "...",
  "priority_level": "P2",
  "objective": "...",
  "dispatched_at": "2026-05-23T14:25:11Z",
  "mandate": { /* full mandate dict, same as intake file */ }
}
```

The file write remains the source of truth — the webhook is a heads-up.

## Writing the NCC consumer

Minimal poller (10 lines, idempotent, crash-safe):

```python
import json, time
from pathlib import Path
INTAKE = Path("/Users/natrix/Projects/ncc-server/mandate-intake")
FAILED = INTAKE / ".failed"
while True:
    for f in sorted(INTAKE.glob("MANDATE-*.json")):
        m = json.loads(f.read_text())
        try:
            run_mandate(m)                            # your code
            f.rename(f.with_suffix(".consumed"))      # commit
        except Exception:
            FAILED.mkdir(exist_ok=True)
            f.rename(FAILED / f.name)                 # park for requeue
    time.sleep(5)
```

The `.consumed` rename is the consumer's commit. NCL's idempotent write
guarantees that a re-dispatch of the same mandate_id is a no-op while the
file is still present — re-process by deleting it first.

## Recovery procedures

### A dispatch failed (transient)

1. Check `GET /system/health/rollup` or the orchestrator stats — look for
   `failed_total` ticking on NCC.
2. If the circuit breaker is open, wait 10 minutes or restart the Brain.
3. Re-run the dispatch via `POST /orchestrator/dispatch/{mandate_id}` —
   idempotent file write means duplicate calls are safe.

### A dispatch failed (transitioned to FAILED)

`PillarRouter` does not transition mandate status on its own — the
orchestrator does. If the orchestrator transitioned the mandate to FAILED
(e.g. circuit open + max retries), use the one-way escape valve:

```
POST /mandate/MANDATE-2026-009/requeue
Authorization: Bearer <STRIKE_TOKEN>
Content-Type: application/json
{"reason": "Transient NCC connectivity blip — retrying"}
```

This transitions FAILED → DRAFT. The mandate must walk the normal
lifecycle again (DRAFT → PENDING_APPROVAL → ACTIVE → …) because the
original dispatch context (intake file, scheduler hooks) is gone.

Status code 409 means the mandate is not in FAILED. Status code 404 means
the mandate ID does not exist in `brain.mandates`.

### Manual recovery from `.failed/`

If the NCC consumer moved a mandate to `.failed/<id>.json` after an
unrecoverable processing error, an operator can:

1. Move the file back to the intake dir: `mv .failed/<id>.json ./<id>.json`
2. Re-issue the requeue: `POST /mandate/<id>/requeue` — this resets the
   mandate's NCL-side state so the next dispatch cycle picks it up.

### Telemetry

`PillarRouter.get_stats()` exposes per-pillar counters:

```json
{
  "NCC": {"dispatched_total": 14, "failed_total": 0, "last_dispatched_at": "...",
          "last_intake_path": "...", "circuit_open": false, "consecutive_failures": 0}
}
```

(Surface via `GET /system/orchestrator-quality` in a follow-up patch.)

## See also

- `runtime/dispatch/pillar_router.py` — implementation
- `runtime/strike_point_orchestrator.py:dispatch_mandate()` — caller
- `runtime/ncl_brain/models.py:PillarType` — enum (NCC + NCL only)
- `runtime/ncl_brain/models.py:MandateStatus.valid_transitions()` —
  the `FAILED → DRAFT` escape valve
- `runtime/api/routes.py` — `/mandates` rejects BRS/AAC, `/mandate/{id}/requeue` endpoint
- `feedback-synthesis/{brs,aac}-intake/README.md` — RETIRED markers
