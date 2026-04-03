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
    """Lazy import to prevent circular import on module load."""
    if name == "NCLBrain":
        from runtime.ncl_brain.brain import NCLBrain
        return NCLBrain
    raise AttributeError(f"module 'runtime' has no attribute {name}")
