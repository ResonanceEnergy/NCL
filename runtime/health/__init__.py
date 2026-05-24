"""NCL Health subsystem — rolled-up state for iOS Dashboard + ops checks."""

from .rollup import build_health_rollup, write_rollup_atomic


__all__ = ["build_health_rollup", "write_rollup_atomic"]
