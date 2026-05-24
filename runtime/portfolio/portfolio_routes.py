"""Portfolio API routes — DI-migrated (W10C-3).

The portfolio router handlers were converted from the legacy
``from runtime.api.routes import STRIKE_TOKEN`` + module-global injection
pattern to FastAPI ``Depends()`` DI on 2026-05-24 and now live in
:mod:`runtime.api.routers.portfolio`, registered through
``runtime.api.routers.register_routers``.

This module is preserved as a compatibility shim so existing imports keep
working without forcing a cross-package cycle (``runtime.api.routes``
imports from here at module-load time, so re-exporting the new router
from here would create a circular import — instead this file exposes an
empty ``router`` that contributes zero routes when included).

What still works:

    from runtime.portfolio.portfolio_routes import router as portfolio_router
    from runtime.portfolio.portfolio_routes import set_portfolio_manager

``routes.py``'s lifespan calls ``set_portfolio_manager(_portfolio_mgr)``
which assigns to the module-level ``_portfolio_manager`` global below.
``runtime.api.deps.get_portfolio_mgr`` reads that global at request time
so the DI factory always returns the live singleton — no need to touch
``routes.py``'s lifespan code.

The ``router`` re-exported below is an EMPTY ``APIRouter`` retained only
so ``app.include_router(portfolio_router)`` in routes.py is a harmless
no-op. The canonical, route-bearing router is the one registered via
``routers/__init__.py``.
"""

from __future__ import annotations

from fastapi import APIRouter


# Empty shim router — kept so the legacy ``app.include_router(portfolio_router)``
# call in ``runtime.api.routes`` remains a harmless no-op. The real handlers
# are mounted by ``runtime.api.routers.register_routers``.
router = APIRouter()


# Module-level reference — injected by Brain startup via set_portfolio_manager()
# and read at request time by runtime.api.deps.get_portfolio_mgr().
_portfolio_manager = None


def set_portfolio_manager(pm) -> None:
    """Called by Brain startup to inject the PortfolioManager singleton.

    Stored on this module's ``_portfolio_manager`` global; the DI factory
    in :mod:`runtime.api.deps` reads back from here at request time.
    """
    global _portfolio_manager
    _portfolio_manager = pm
