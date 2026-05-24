# BRS INTAKE — RETIRED 2026-05-23

The BRS pillar was retired per NATRIX directive on 2026-05-23
("no orphan them we dont use them"). This directory is **no longer used**.

- NCL no longer routes mandates to BRS.
- `pillar="BRS"` (or `"brs"`) is a hard reject at the NCL validator.
  `Mandate(pillar="BRS", ...)` raises `ValueError`; the `/mandates`
  endpoint returns HTTP 400 with
  `{"error": "pillar BRS/AAC is no longer supported"}`.
- The `runtime/dispatch/pillar_router.py` `PillarRouter` only accepts
  `NCC`; any other value raises `UnknownPillarError`.

This directory is preserved only because historical filesystem entries
existed. Do not write new files here. The corresponding `senders/brs_sender.py`
is a no-op stub that exits with code 1.

See `docs/PILLAR_DISPATCH.md` for the current (NCC-only) contract.
