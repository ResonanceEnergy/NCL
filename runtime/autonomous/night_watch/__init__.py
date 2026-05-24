"""
runtime.autonomous.night_watch — carved-out Night Watch phases.

W10B-14 (2026-05-24) extracted `_night_watch_analyst` (Phase 5 — LLM-powered
analyst) into `analyst.py`. W10C-7 followed with `_night_watch_memory_cycle`
(Phase 2 — memory maintenance) into `memory_cycle.py`. W10C-8 finished the
sweep with `_night_watch_intel_cycle` (Phase 3 — intel correlation) into
`intel_cycle.py`. All three night-watch monsters now live here; the
scheduler methods of the same names are thin shims that re-route to
`run(self)` in the matching submodule.

Each module here exposes `async def run(scheduler) -> None:` so the
scheduler shims can re-route an existing method to its extracted body
without changing the method's public name or signature.
"""

from __future__ import annotations  # noqa: I001

from . import analyst, intel_cycle, memory_cycle

__all__ = ["analyst", "intel_cycle", "memory_cycle"]
