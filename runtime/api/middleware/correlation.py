"""Correlation-ID middleware + logging filter.

W8-A9: every HTTP request gets a stable `request_id` that:
  1. is generated server-side (or accepted from inbound `X-Request-Id` header),
  2. is stored in a `contextvars.ContextVar` so any code path (sync or async)
     that emits a log record during the request can attach it,
  3. is echoed back to the caller via the `x-request-id` response header.

Pre-W8-A9, tracing a request through 32 autonomous loops + 176+ endpoints
required grepping by timestamp. With this middleware a single curl returns
the id, and every log line emitted under that request's task tree is tagged
with it (via `RequestIdFilter`).

Usage in `routes.py`:

    from .middleware.correlation import (
        CorrelationMiddleware,
        RequestIdFilter,
        request_id_var,
    )
    app.add_middleware(CorrelationMiddleware)
    logging.getLogger("ncl").addFilter(RequestIdFilter())

The log format string should include `%(request_id)s`. Outside an HTTP
request the contextvar default `'-'` is used, so background loops don't
crash the formatter.
"""

from __future__ import annotations  # noqa: I001

import logging
import re
import secrets
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Module-level contextvar. The default `'-'` is what `RequestIdFilter` will
# surface on records emitted outside any HTTP request (e.g. scheduler loops,
# startup logs).
request_id_var: ContextVar[str] = ContextVar("ncl_request_id", default="-")

# Inbound X-Request-Id sanity check. Accept up to 128 chars of
# [A-Za-z0-9_.:-] so callers can supply their own trace correlator
# (e.g. a vendor's id) without us blindly trusting newlines or control
# bytes that would corrupt log lines or response headers.
_INBOUND_REQ_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


def _new_request_id() -> str:
    """Generate a fresh 16-hex-char request id."""
    return secrets.token_hex(8)


def set_request_id(req_id: str) -> None:
    """Manually set the request-id contextvar.

    Used by background tasks (autonomous loops, drainer batches, etc.) that
    are not driven by an HTTP request but still want their log lines tagged
    with a stable correlation id. The id is inherited by anything that
    awaits inside the same task / contextvar scope.

    W10B-7 (2026-05-24): added so the 32 autonomous loops can stamp a fresh
    per-cycle id at the top of each iteration, replacing the `[req=-]`
    default that previously masked every background log line.

    No-ops silently on falsy input rather than poisoning the contextvar
    with garbage.
    """
    if not req_id:
        return
    request_id_var.set(req_id)


def loop_request_id(prefix: str) -> str:
    """Generate a fresh per-cycle request id of the form ``<prefix>-<hex8>``.

    Example: ``loop_request_id("loop-memcons")`` → ``loop-memcons-a3b4c5d6``.

    The prefix should be short and stable so a `grep '\[req=loop-memcons-'`
    pulls every log line emitted by that loop across all of its cycles.
    """
    return f"{prefix}-{secrets.token_hex(4)}"


def _sanitize_inbound(raw: Optional[str]) -> Optional[str]:
    """Return the inbound id if it passes the allowlist, else None."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if _INBOUND_REQ_ID_RE.match(raw):
        return raw
    return None


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every request/response and contextvar.

    Honors inbound `X-Request-Id` if the caller provided one that passes
    `_INBOUND_REQ_ID_RE`; otherwise generates a new 8-byte hex id.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        inbound = _sanitize_inbound(request.headers.get("x-request-id"))
        req_id = inbound or _new_request_id()
        token = request_id_var.set(req_id)
        try:
            # Make the id available to handlers via request.state too —
            # cheaper than re-reading the contextvar in a path expression.
            request.state.request_id = req_id
            response: Response = await call_next(request)
            # Stamp the response so the caller can correlate.
            response.headers["x-request-id"] = req_id
            return response
        finally:
            request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """Inject `request_id` onto every LogRecord.

    Reads from `request_id_var`; if unset (outside a request) falls back
    to `'-'` so formatters that include `%(request_id)s` never KeyError.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            record.request_id = request_id_var.get("-")
        except Exception:
            record.request_id = "-"
        return True


__all__ = [
    "request_id_var",
    "CorrelationMiddleware",
    "RequestIdFilter",
    "set_request_id",
    "loop_request_id",
]
