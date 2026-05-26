"""FastAPI sub-routers extracted from the monolithic routes.py.

Each router owns a single URL prefix surface (e.g. /system/*) and is
registered with the root FastAPI app via :func:`register_routers`.

The extraction is intentionally incremental: routes.py was 10,754 LOC at
the start of W4-12 and won't be split in one shot. Wave additions:

    W4-12 / W5-03 / W5-04  →  system.py     (/system/*)
    W5-03 / W5-04          →  council.py    (/council/*)
    W5-03 / W5-04          →  council_runner.py (council-runner v1 endpoints)
    W5-03 / W5-04          →  memory.py     (/memory/*)
    W5-05                  →  journal.py    (/journal/*)
    W5-05                  →  mandate.py    (/mandates/*)
    W5-05                  →  pump.py       (/pump/*)
    W5-05                  →  feedback.py   (pipeline-side /feedback/*)

Other prefixes (intelligence, prediction, focus, ytc, portfolio, paper,
calendar, polymarket-strategies, feedback-events) live next to their
owning subsystem and are wired directly in routes.py via
``app.include_router(...)``.

Routers expect that :mod:`runtime.api.routes` continues to own:
    - The FastAPI ``app`` instance + lifespan
    - Module-level globals populated at startup (``brain``,
      ``_autonomous``, ``STRIKE_TOKEN``, etc.)
    - Shared helpers (``_verify_strike_token``, ``_check_rate_limit``,
      ``_maybe_limit``, ``_pump_count``, ``_PUMP_QUALITY``)

Routers reach those globals via lazy import inside handler bodies so we
do not introduce a circular import at module-load time. Stable Pydantic
types from ``runtime.ncl_brain.models`` (``PillarType``, ``MandateStatus``,
``PumpPrompt``, ``FeedbackReport``) are imported eagerly — they have no
dependency on routes.py and FastAPI needs the concrete type at handler
decoration time.
"""

from __future__ import annotations

from fastapi import FastAPI

from .council import router as council_router
from .council_runner import router as council_runner_router
from .feedback import router as feedback_pipeline_router
from .intel import router as intel_router
from .journal import router as journal_router
from .life_plan import router as life_plan_router
from .mandate import router as mandate_router
from .memory import router as memory_router
from .ops import router as ops_router
from .portfolio import router as portfolio_router
from .pump import router as pump_router
from .system import router as system_router


def register_routers(app: FastAPI) -> None:
    """Attach all extracted sub-routers to the given FastAPI app.

    Called from :mod:`runtime.api.routes` immediately after the root
    ``app = FastAPI(...)`` instance is constructed. Idempotent enough to
    call once — duplicate registration would re-mount the same handlers,
    so callers must invoke it exactly once at startup.

    Note on portfolio: W10C-3 (2026-05-24) moved the /portfolio/* handlers
    from ``runtime.portfolio.portfolio_routes`` into ``routers/portfolio.py``
    with DI. The legacy ``portfolio_routes.py`` still exposes an EMPTY
    shim ``router`` symbol so the historical
    ``app.include_router(portfolio_router)`` line in ``routes.py`` stays a
    harmless no-op while this function mounts the canonical, route-bearing
    one.
    """
    app.include_router(system_router)
    app.include_router(council_router)
    app.include_router(council_runner_router)
    app.include_router(memory_router)
    app.include_router(intel_router)
    app.include_router(journal_router)
    app.include_router(life_plan_router)
    app.include_router(mandate_router)
    app.include_router(ops_router)
    app.include_router(portfolio_router)
    app.include_router(pump_router)
    app.include_router(feedback_pipeline_router)


__all__ = [
    "register_routers",
    "council_router",
    "council_runner_router",
    "feedback_pipeline_router",
    "intel_router",
    "journal_router",
    "mandate_router",
    "memory_router",
    "portfolio_router",
    "pump_router",
    "system_router",
]
