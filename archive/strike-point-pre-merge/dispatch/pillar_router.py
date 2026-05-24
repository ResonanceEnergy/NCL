"""Pillar router — first-class dispatch of approved mandates to NCC.

NCC is the *only* downstream pillar. BRS and AAC were retired on 2026-05-23
per NATRIX directive ("no orphan them we dont use them"). The router still
exists as a clean abstraction (circuit breaker + retry + idempotent file +
optional webhook), but the pillar set is now ``("NCC",)`` and any attempt
to dispatch with ``pillar in {"BRS","AAC"}`` raises
:class:`UnknownPillarError`.

Public surface
--------------
- ``PillarRouter`` — async dispatch with idempotent file write + best-effort
  webhook POST.
- ``DispatchResult`` — structured outcome (intake_path, webhook_status, errors).
- ``UnknownPillarError`` — raised for invalid pillar names (incl. BRS/AAC).
- ``get_default_router()`` — process-singleton accessor used by the orchestrator.

Environment variables honored
-----------------------------
NCC_INTAKE_DIR        default: ``$HOME/Projects/ncc-server/mandate-intake``
NCC_WEBHOOK_URL       default: unset (HTTP dispatch skipped)

Circuit breaker
---------------
NCC gets a single ``CircuitBreaker`` (3 consecutive failures, 600s
recovery). When the breaker is open, ``dispatch()`` short-circuits with a
``DispatchResult`` carrying ``circuit_open=True`` rather than retrying the
underlying write. The breaker covers both file and webhook failures.

Idempotency
-----------
If ``<intake_dir>/<mandate_id>.json`` already exists, the file write is
skipped (``already_written=True`` in the result) — but telemetry still ticks
and the webhook is still attempted. This makes redispatch / replay safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.dispatch.pillar_router")

# ── Circuit breaker import — fall back to inline impl if llm.retry is missing ──
try:
    from runtime.llm.retry import CircuitBreaker, CircuitOpen  # type: ignore
    _HAS_LLM_BREAKER = True
except Exception:  # pragma: no cover — defensive fallback
    _HAS_LLM_BREAKER = False
    import time as _time

    class CircuitOpen(Exception):  # type: ignore[no-redef]
        def __init__(self, provider: str, until: float) -> None:
            super().__init__(f"Circuit open for {provider} until {until}")
            self.provider = provider
            self.until = until

    class CircuitBreaker:  # type: ignore[no-redef]
        """Minimal local circuit breaker (used if runtime.llm.retry absent)."""

        _registry: dict[str, "CircuitBreaker"] = {}

        def __init__(
            self,
            provider: str,
            fail_threshold: int = 3,
            recovery_seconds: float = 600.0,
        ) -> None:
            self.provider = provider
            self.fail_threshold = max(1, fail_threshold)
            self.recovery_seconds = max(0.0, recovery_seconds)
            self._consecutive_failures = 0
            self._opened_at: float | None = None

        @classmethod
        def for_provider(
            cls,
            provider: str,
            fail_threshold: int = 3,
            recovery_seconds: float = 600.0,
        ) -> "CircuitBreaker":
            existing = cls._registry.get(provider)
            if existing is not None:
                return existing
            breaker = cls(provider, fail_threshold, recovery_seconds)
            cls._registry[provider] = breaker
            return breaker

        @classmethod
        def reset_registry(cls) -> None:
            cls._registry.clear()

        @property
        def is_open(self) -> bool:
            if self._opened_at is None:
                return False
            if _time.monotonic() - self._opened_at >= self.recovery_seconds:
                self._opened_at = None
                return False
            return True

        @property
        def consecutive_failures(self) -> int:
            return self._consecutive_failures

        def check(self) -> None:
            if self.is_open:
                until = _time.time() + self.recovery_seconds
                raise CircuitOpen(self.provider, until)

        def record_success(self) -> None:
            self._consecutive_failures = 0
            self._opened_at = None

        def record_failure(self) -> None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.fail_threshold:
                self._opened_at = _time.monotonic()
                log.warning(
                    "[circuit:%s] OPEN after %d consecutive failures "
                    "(cooldown=%.0fs)",
                    self.provider, self._consecutive_failures, self.recovery_seconds,
                )


# Only NCC is a live dispatch target. BRS/AAC retired 2026-05-23.
VALID_PILLARS = ("NCC",)
# Explicit black-list for clearer error messages on legacy callers.
_RETIRED_PILLARS = frozenset({"BRS", "AAC"})


class DispatchError(Exception):
    """Generic dispatch failure (file write or webhook error)."""


class UnknownPillarError(DispatchError):
    """Pillar name not in :data:`VALID_PILLARS` (or in the retired set)."""


@dataclass
class DispatchResult:
    """Outcome of a single :meth:`PillarRouter.dispatch` call."""

    pillar: str
    mandate_id: str
    intake_path: Optional[str] = None
    intake_written: bool = False
    already_written: bool = False
    webhook_url: Optional[str] = None
    webhook_status: Optional[str] = None  # "delivered" | "failed" | "skipped"
    webhook_http_code: Optional[int] = None
    circuit_open: bool = False
    success: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pillar": self.pillar,
            "mandate_id": self.mandate_id,
            "intake_path": self.intake_path,
            "intake_written": self.intake_written,
            "already_written": self.already_written,
            "webhook_url": self.webhook_url,
            "webhook_status": self.webhook_status,
            "webhook_http_code": self.webhook_http_code,
            "circuit_open": self.circuit_open,
            "success": self.success,
            "errors": list(self.errors),
        }


def _resolve_config(env: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Resolve pillar config from environment (NCC-only).

    Returns ``{pillar: {"intake_dir": Path, "webhook_url": str | None}}``.
    """
    e = env if env is not None else os.environ
    ncc_base = Path(e.get("NCL_NCC_BASE", str(Path.home() / "Projects" / "ncc-server")))

    return {
        "NCC": {
            "intake_dir": Path(e.get("NCC_INTAKE_DIR", str(ncc_base / "mandate-intake"))),
            "webhook_url": e.get("NCC_WEBHOOK_URL") or None,
        },
    }


class PillarRouter:
    """Dispatch approved mandates to NCC (the only live pillar).

    Parameters
    ----------
    config : dict[str, dict[str, Any]] | None
        Per-pillar config. If ``None``, resolved from environment via
        :func:`_resolve_config`. Each value is a dict with keys
        ``intake_dir`` (Path | str) and ``webhook_url`` (str | None).
    http_timeout : float
        Webhook POST timeout. Default 10s.
    fail_threshold : int
        Consecutive failures before circuit breaker opens. Default 3.
    recovery_seconds : float
        Circuit breaker cooldown. Default 600s.
    """

    def __init__(
        self,
        config: Optional[dict[str, dict[str, Any]]] = None,
        http_timeout: float = 10.0,
        fail_threshold: int = 3,
        recovery_seconds: float = 600.0,
    ) -> None:
        self._config = config if config is not None else _resolve_config()
        self._http_timeout = http_timeout
        self._breakers: dict[str, CircuitBreaker] = {
            p: CircuitBreaker.for_provider(
                f"pillar-{p.lower()}", fail_threshold, recovery_seconds
            )
            for p in VALID_PILLARS
        }
        self._stats: dict[str, dict[str, Any]] = {
            p: {
                "dispatched_total": 0,
                "failed_total": 0,
                "last_dispatched_at": None,
                "last_intake_path": None,
                "last_error": None,
            }
            for p in VALID_PILLARS
        }
        # Eager-create intake dirs so the first dispatch isn't fighting mkdir.
        for p in VALID_PILLARS:
            try:
                Path(self._config[p]["intake_dir"]).mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # pragma: no cover — surfaced at dispatch
                log.warning("Could not pre-create %s intake dir: %s", p, exc)

    # ── Public API ────────────────────────────────────────────────────

    def get_config(self) -> dict[str, dict[str, Any]]:
        """Return a defensive copy of the resolved config (Paths → str)."""
        return {
            p: {
                "intake_dir": str(self._config[p]["intake_dir"]),
                "webhook_url": self._config[p]["webhook_url"],
            }
            for p in VALID_PILLARS
        }

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-pillar telemetry (dispatched/failed/last_*)."""
        out: dict[str, dict[str, Any]] = {}
        for p in VALID_PILLARS:
            breaker = self._breakers[p]
            out[p] = dict(self._stats[p])
            out[p]["circuit_open"] = bool(breaker.is_open)
            out[p]["consecutive_failures"] = breaker.consecutive_failures
        return out

    async def health_check(self, pillar: str) -> dict[str, Any]:
        """Probe a pillar's intake dir + webhook reachability.

        Returns ``{pillar, intake_dir, intake_writable, webhook_url,
        webhook_reachable, circuit_open}``. Cheap to call; does not write
        to the intake dir.
        """
        pillar = pillar.upper().strip()
        if pillar in _RETIRED_PILLARS:
            raise UnknownPillarError(
                f"Pillar {pillar} was retired 2026-05-23 — NCC only"
            )
        if pillar not in VALID_PILLARS:
            raise UnknownPillarError(f"Unknown pillar: {pillar}")
        cfg = self._config[pillar]
        intake = Path(cfg["intake_dir"])
        webhook_url = cfg["webhook_url"]
        webhook_reachable: Optional[bool] = None

        if webhook_url:
            webhook_reachable = await self._probe_webhook(webhook_url)

        return {
            "pillar": pillar,
            "intake_dir": str(intake),
            "intake_writable": _is_writable_dir(intake),
            "webhook_url": webhook_url,
            "webhook_reachable": webhook_reachable,
            "circuit_open": self._breakers[pillar].is_open,
        }

    async def dispatch(self, mandate: dict[str, Any] | Any) -> DispatchResult:
        """Route ``mandate`` to its target pillar (NCC only).

        ``mandate`` may be a dict (legacy orchestrator path) or a Pydantic
        model that supports ``.model_dump(mode="json")`` (current Mandate).
        """
        mandate_dict = _coerce_mandate(mandate)
        mandate_id = str(mandate_dict.get("mandate_id") or "unknown")
        pillar_raw = mandate_dict.get("pillar", "")
        pillar = _normalize_pillar(pillar_raw)

        if pillar in _RETIRED_PILLARS:
            raise UnknownPillarError(
                f"Pillar {pillar} was retired 2026-05-23 — refusing to dispatch "
                f"mandate {mandate_id}. Use NCC only."
            )
        if pillar not in VALID_PILLARS:
            raise UnknownPillarError(
                f"Invalid pillar '{pillar_raw}' for mandate {mandate_id} "
                f"(expected one of {VALID_PILLARS})"
            )

        result = DispatchResult(pillar=pillar, mandate_id=mandate_id)
        breaker = self._breakers[pillar]
        cfg = self._config[pillar]
        result.webhook_url = cfg["webhook_url"]

        # Short-circuit if breaker is open.
        if breaker.is_open:
            result.circuit_open = True
            result.errors.append(f"circuit_open: {pillar} breaker is OPEN")
            self._stats[pillar]["failed_total"] += 1
            self._stats[pillar]["last_error"] = "circuit_open"
            log.warning(
                "Skipping dispatch of %s to %s — circuit breaker OPEN",
                mandate_id, pillar,
            )
            return result

        # 1) File-based intake — idempotent.
        try:
            intake_path, already = self._write_intake_file(
                Path(cfg["intake_dir"]), mandate_id, mandate_dict
            )
            result.intake_path = str(intake_path)
            result.intake_written = not already
            result.already_written = already
        except Exception as exc:
            err = f"intake_write_failed: {exc}"
            result.errors.append(err)
            breaker.record_failure()
            self._stats[pillar]["failed_total"] += 1
            self._stats[pillar]["last_error"] = err
            log.error("Intake write failed for %s → %s: %s", mandate_id, pillar, exc)
            return result

        # 2) Optional webhook — best-effort.
        if cfg["webhook_url"]:
            status, http_code, err = await self._post_webhook(
                cfg["webhook_url"], pillar, mandate_dict
            )
            result.webhook_status = status
            result.webhook_http_code = http_code
            if err:
                result.errors.append(err)
        else:
            result.webhook_status = "skipped"

        # Success if intake wrote OR was already there, and webhook didn't
        # hard-fail (a missing webhook URL is "skipped", which counts as ok).
        webhook_ok = result.webhook_status in (None, "delivered", "skipped")
        result.success = (result.intake_written or result.already_written) and webhook_ok

        if result.success:
            breaker.record_success()
            self._stats[pillar]["dispatched_total"] += 1
            self._stats[pillar]["last_dispatched_at"] = (
                datetime.now(timezone.utc).isoformat()
            )
            self._stats[pillar]["last_intake_path"] = result.intake_path
            log.info(
                "Dispatched %s → %s (intake=%s, webhook=%s)",
                mandate_id, pillar, result.intake_path, result.webhook_status,
            )
        else:
            breaker.record_failure()
            self._stats[pillar]["failed_total"] += 1
            self._stats[pillar]["last_error"] = "; ".join(result.errors) or "unknown"

        return result

    # ── Per-pillar helpers (thin wrapper for testing) ─────────────────

    async def _dispatch_to_ncc(self, mandate: dict[str, Any]) -> DispatchResult:
        mandate = dict(mandate)
        mandate["pillar"] = "NCC"
        return await self.dispatch(mandate)

    # ── Internals ─────────────────────────────────────────────────────

    def _write_intake_file(
        self,
        intake_dir: Path,
        mandate_id: str,
        mandate_dict: dict[str, Any],
    ) -> tuple[Path, bool]:
        """Write ``<intake_dir>/<mandate_id>.json``.

        Returns ``(path, already_existed)``. Idempotent: if the file is
        already present the existing one is left untouched.
        """
        intake_dir.mkdir(parents=True, exist_ok=True)
        target = intake_dir / f"{mandate_id}.json"
        if target.exists():
            return target, True

        payload = dict(mandate_dict)
        payload.setdefault("_dispatched_at", datetime.now(timezone.utc).isoformat())
        # Atomic write via temp file + rename so concurrent consumers never
        # see a half-written JSON blob.
        tmp = intake_dir / f".{mandate_id}.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        tmp.replace(target)
        return target, False

    async def _post_webhook(
        self,
        url: str,
        pillar: str,
        mandate_dict: dict[str, Any],
    ) -> tuple[str, Optional[int], Optional[str]]:
        """POST mandate to the pillar's webhook. Returns (status, code, err)."""
        try:
            import httpx  # local import — avoid hard dep at module load
        except ImportError:
            return "failed", None, "httpx_unavailable"

        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                resp = await client.post(
                    url,
                    json={
                        "type": "mandate_dispatch",
                        "pillar": pillar,
                        "mandate_id": mandate_dict.get("mandate_id"),
                        "title": mandate_dict.get("title"),
                        "priority_level": mandate_dict.get("priority_level"),
                        "objective": mandate_dict.get("objective"),
                        "dispatched_at": datetime.now(timezone.utc).isoformat(),
                        "mandate": mandate_dict,
                    },
                )
                if 200 <= resp.status_code < 300:
                    return "delivered", resp.status_code, None
                return (
                    "failed",
                    resp.status_code,
                    f"webhook_http_{resp.status_code}",
                )
        except Exception as exc:
            return "failed", None, f"webhook_exception: {exc}"

    async def _probe_webhook(self, url: str) -> bool:
        """Best-effort HEAD/GET probe for health_check. Treat any 2xx/3xx/4xx as
        'the server answered'; only network errors return False."""
        try:
            import httpx
        except ImportError:
            return False
        try:
            async with httpx.AsyncClient(timeout=min(5.0, self._http_timeout)) as client:
                resp = await client.get(url)
                # A 405 here is fine — the endpoint exists and rejects GET.
                return resp.status_code < 500
        except Exception:
            return False


# ── Module helpers ────────────────────────────────────────────────────────


def _coerce_mandate(mandate: Any) -> dict[str, Any]:
    """Accept either a dict or a Pydantic model. Return a plain dict."""
    if isinstance(mandate, dict):
        return mandate
    # Pydantic v2
    dump = getattr(mandate, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    # Pydantic v1 fallback
    dump_v1 = getattr(mandate, "dict", None)
    if callable(dump_v1):
        return dump_v1()
    raise TypeError(
        f"Cannot coerce {type(mandate).__name__} to mandate dict — "
        f"expected dict or Pydantic model"
    )


def _normalize_pillar(raw: Any) -> str:
    """Lowercase enum values ('ncc' from PillarType.NCC) → 'NCC'."""
    if raw is None:
        return ""
    # Enum-like: prefer .value
    value = getattr(raw, "value", raw)
    if isinstance(value, str):
        return value.strip().upper()
    return str(value).strip().upper()


def _is_writable_dir(p: Path) -> bool:
    try:
        return p.is_dir() and os.access(p, os.W_OK)
    except Exception:
        return False


# ── Process-wide singleton accessor ────────────────────────────────────────


_default_router: Optional[PillarRouter] = None
_default_router_lock = asyncio.Lock()


def get_default_router() -> PillarRouter:
    """Return (and lazily create) the process-wide :class:`PillarRouter`.

    Safe to call from anywhere; the env is read on first call. To re-read
    env after mutating config, call :func:`reset_default_router()` first.
    """
    global _default_router
    if _default_router is None:
        _default_router = PillarRouter()
    return _default_router


def reset_default_router() -> None:
    """Test helper — drop the cached singleton so env changes take effect."""
    global _default_router
    _default_router = None
    CircuitBreaker.reset_registry()


__all__ = [
    "VALID_PILLARS",
    "DispatchError",
    "DispatchResult",
    "PillarRouter",
    "UnknownPillarError",
    "get_default_router",
    "reset_default_router",
]
