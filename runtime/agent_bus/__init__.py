"""Agent bus — unified service-request dispatcher (Wave 14W-E).

The auto-trader (and other agents) call ``intel_request(kind=..., **kwargs)``
to pull intel, spawn councils, schedule follow-ups, etc. — instead of
being a passive receiver of pushed signals.

See ``intel_request`` for the full dispatcher + handler list.
"""

from .intel_request import (
    IntelRequest,
    IntelResponse,
    RequestKind,
    intel_request,
    list_recent_requests,
)


__all__ = [
    "IntelRequest",
    "IntelResponse",
    "RequestKind",
    "intel_request",
    "list_recent_requests",
]
