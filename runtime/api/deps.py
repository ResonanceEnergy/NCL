"""FastAPI dependency-injection factories for NCL routers.

Centralises the ``Depends()`` factories that previously lived at end-of-file
in :mod:`runtime.api.routes`. Extracted in W10B-3 (2026-05-24) so individual
routers can do::

    from ..deps import get_brain, verify_strike_token_dep
    from fastapi import Depends

    @router.get("/foo")
    async def foo(brain=Depends(get_brain)):
        ...

instead of the legacy lazy-import shim::

    from .. import routes as _routes
    _routes._verify_strike_token(authorization)
    brain = _routes.brain

Each factory is a thin pass-through that resolves the live singleton on the
``runtime.api.routes`` module via :func:`importlib.import_module`. We cannot
do a top-level ``from .routes import brain`` because routes.py imports the
routers package mid-execution (via ``register_routers``) before its
module-level globals (``brain``, ``_autonomous``, ``_intelligence``) have
even been declared, let alone populated. The deferred lookup also keeps the
factories pointing at the *current* singleton even after the lifespan
handler swaps it in — they always read the latest value from the
``routes`` module's namespace.

Public API (mirrors the W8-A8 routes.py EOF factories, byte-identical):

* :func:`get_brain` — live ``NCLBrain`` singleton (may be ``None`` pre-lifespan)
* :func:`get_intelligence` — live ``IntelligenceEngine`` singleton
* :func:`get_autonomous` — live ``AutonomousScheduler`` singleton
* :func:`verify_strike_token_dep` — auth guard (raises 401/403)

For back-compat, :mod:`runtime.api.routes` re-exports these names so any
caller using ``from runtime.api.routes import get_brain`` keeps working.
"""

from __future__ import annotations

import importlib

from fastapi import Header


def _routes_module():
    """Late-bound accessor for :mod:`runtime.api.routes`.

    Using ``importlib.import_module`` rather than ``from .. import routes``
    at module scope avoids the circular-import trap: ``routes.py`` imports
    the routers package (which imports this module) mid-initialisation,
    and at that point ``routes.brain`` / ``routes._autonomous`` are not
    yet defined. By deferring the lookup until request time we guarantee
    routes.py has fully loaded.
    """
    return importlib.import_module("runtime.api.routes")


def get_brain():
    """DI factory: returns the live ``NCLBrain`` singleton.

    May be ``None`` if called before the FastAPI lifespan handler has
    finished initialising the Brain. Handlers should check ``if not brain``
    and raise HTTP 503.
    """
    return _routes_module().brain


def get_intelligence():
    """DI factory: returns the live ``IntelligenceEngine`` singleton.

    The module-level global is ``_intelligence`` (underscore-prefixed);
    the public DI accessor drops the underscore for FastAPI ergonomics.
    May be ``None`` before the lifespan handler completes.
    """
    return _routes_module()._intelligence


def get_autonomous():
    """DI factory: returns the live ``AutonomousScheduler`` singleton.

    May be ``None`` before the lifespan handler completes.
    """
    return _routes_module()._autonomous


def verify_strike_token_dep(authorization: str = Header(default="")):
    """DI auth guard — delegates to ``routes._verify_strike_token``.

    Raises HTTP 401 (missing Authorization header) or 403 (invalid token)
    on failure. Returns ``None`` on success. Handlers should declare::

        _: None = Depends(verify_strike_token_dep)

    instead of pulling the Authorization header and calling the verifier
    inline.
    """
    _routes_module()._verify_strike_token(authorization)


# ─── Subsystem accessors (W10B-3 add-ons) ──────────────────────────────
# These mirror the four canonical factories above but resolve other
# routes.py module-level singletons that individual routers need. They
# return ``None`` until the lifespan handler populates them; handlers
# must guard with ``if not <thing>: raise HTTPException(503)``.
def get_journal_store():
    """DI factory: returns the live ``JournalStore`` (may be ``None``)."""
    return _routes_module()._journal_store


def get_reflection_engine():
    """DI factory: returns the live ``ReflectionEngine`` (may be ``None``)."""
    return _routes_module()._reflection_engine


def get_context_tips():
    """DI factory: returns the live ``ContextAwareTips`` engine (may be ``None``)."""
    return _routes_module()._context_tips


def get_memory_bridge():
    """DI factory: returns the live ``MemoryBridge`` (may be ``None``).

    Added W10C-2 (2026-05-24) when ``routers/memory.py`` was converted to DI.
    The bridge owns the bridged read/write surface over the underlying
    ``MemoryStore`` (stats, timeline, search, cleanup_sources). Handlers
    that need raw store access still go through ``Depends(get_brain)`` and
    read ``brain.memory_store`` because the bridge does not expose every
    primitive (e.g. ``semantic_search``, ``_load_all_units``).
    """
    return _routes_module()._memory_bridge


def get_portfolio_mgr():
    """DI factory: returns the live ``PortfolioManager`` (may be ``None``).

    Added W10C-3 (2026-05-24) when ``routers/portfolio.py`` was converted
    to DI. The manager aggregates multi-broker (IBKR / Moomoo / SnapTrade
    / NDAX / MetaMask / Polymarket) positions, accounts, and performance
    snapshots. It is injected into the legacy ``runtime.portfolio.portfolio_routes``
    module by the lifespan handler via ``set_portfolio_manager()``; this
    factory reads from that injection point so the lifespan logic in
    ``routes.py`` does NOT need to change. May be ``None`` before the
    lifespan handler completes (handlers should raise HTTP 503).
    """
    try:
        pr_module = importlib.import_module("runtime.portfolio.portfolio_routes")
    except ImportError:
        return None
    return getattr(pr_module, "_portfolio_manager", None)


def get_council_store():
    """DI factory: returns the live ``CouncilRunStore`` (may be ``None``).

    Added W10C-5 (2026-05-24) when ``routers/council.py`` was converted
    to DI. The store backs ``/councils/status`` (recent-runs rollup) and
    the legacy ``/council-runner/*`` surface owned by ``routers/council_runner.py``
    (still on the legacy lazy-import pattern as of W10C-5). Both readers
    reach through to the same module-level singleton on ``routes.py``;
    this factory is the DI-friendly accessor for the new surface.
    """
    return _routes_module()._council_store


def get_replay_engine():
    """DI factory: returns the live ``ReplayEngine`` (may be ``None``).

    Added W10C-5 (2026-05-24) alongside :func:`get_council_store` for the
    ``/councils/status`` rollup that reports replay-engine availability.
    """
    return _routes_module()._replay_engine
