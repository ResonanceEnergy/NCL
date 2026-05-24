"""
NCL (NUREALCORTEXLINK) Brain Service.

Think pillar of Resonance Energy enterprise.
Version 2.0.0 — Optimized for Mac Mini M4 Pro
"""

__version__ = "2.0.0"
__author__ = "NATRIX"

# Lazy imports to avoid circular dependencies at module load time.
# Use: from runtime import NCLBrain  (only when needed)

__all__ = ["NCLBrain"]


def __getattr__(name: str):
    """Lazy import to prevent circular import on module load.

    Three branches:
      1. Dunder attrs (``__path__``, ``__spec__``, ``__all__`` probes from
         the import machinery) → raise AttributeError WITHOUT importing.
         Greedy lazy-imports here used to break dictConfig's dotted-path
         resolver (caught W8-A9 + W8-A6 audit, fixed 2026-05-24).
      2. Known lazy targets (``NCLBrain``) → import and return.
      3. Anything else → try to resolve as a real subpackage via
         ``importlib.import_module``. Defers to Python's normal import
         path so callers like ``logging.dictConfig`` see a live module
         instead of an AttributeError.
    """
    # 1. Don't intercept dunder probes — they must AttributeError fast.
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)

    # 2. Explicit lazy targets.
    if name == "NCLBrain":
        from runtime.ncl_brain.brain import NCLBrain

        return NCLBrain

    # 3. Subpackage fallback. Cached after first hit by Python's import
    # machinery — this branch only runs the first time and only when the
    # caller bypassed a normal ``import runtime.<name>`` (which the
    # dictConfig dotted resolver does).
    import importlib

    try:
        return importlib.import_module(f"runtime.{name}")
    except ImportError:
        raise AttributeError(f"module 'runtime' has no attribute {name!r}")
