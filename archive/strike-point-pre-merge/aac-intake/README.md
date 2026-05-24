# AAC INTAKE — RETIRED 2026-05-23

The AAC pillar was retired per NATRIX directive on 2026-05-23
("no orphan them we dont use them"). This directory is **no longer used**.

- NCL no longer routes mandates to AAC.
- `pillar="AAC"` (or `"aac"`) is a hard reject at the NCL validator.
- The `runtime/dispatch/pillar_router.py` `PillarRouter` only accepts
  `NCC`; any other value raises `UnknownPillarError`.

This directory is preserved only because historical filesystem entries
existed. Do not write new files here. The corresponding `senders/aac_sender.py`
is a no-op stub that exits with code 1.

See `docs/PILLAR_DISPATCH.md` for the current (NCC-only) contract.
