"""
NCL Portfolio Hygiene — Wave 14J Phase 8 (J8a + J8b + J8c)

J8a — Stale-quote detection (per-asset thresholds)
        Quotes go stale at different speeds:
          equities (RTH):   60s
          options (RTH):    60s
          crypto:           30s
          on-chain:         3600s (1h — block-time)
          polymarket:       300s (5min)
          equities (off):   86400s (daily close)
        Quarantine flag passes through to risk_governor so sizing math
        doesn't trust stale data.

J8b — Auth-token expiry tracking
        Single manifest file with broker token expiries; ntfy when
        any expiry is within 48h.

J8c — Per-adapter circuit breaker
        IBKR already has one (3-fail -> 10m skip). Generalize the
        pattern so every adapter can be quarantined uniformly.

J8d (trade-date/settle-date split) and J9a (test_portfolio_manager.py)
deferred — bigger surgery, separate Wave 14K.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.hygiene")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
TOKEN_MANIFEST = DATA_DIR / "auth_tokens.json"

# Stale-quote thresholds (seconds)
STALE_THRESHOLDS_S = {
    "equity": int(os.getenv("NCL_STALE_EQUITY_S", "60")),
    "option": int(os.getenv("NCL_STALE_OPTION_S", "60")),
    "crypto": int(os.getenv("NCL_STALE_CRYPTO_S", "30")),
    "onchain": int(os.getenv("NCL_STALE_ONCHAIN_S", "3600")),
    "polymarket": int(os.getenv("NCL_STALE_POLYMARKET_S", "300")),
    "future": int(os.getenv("NCL_STALE_FUTURE_S", "60")),
    "default": int(os.getenv("NCL_STALE_DEFAULT_S", "300")),
}

# Off-hours multiplier (RTH closed = bigger window)
OFF_HOURS_MULT = float(os.getenv("NCL_STALE_OFFHOURS_MULT", "1440"))  # 1 day worth

CIRCUIT_BREAKER_FAIL_THRESHOLD = int(os.getenv("NCL_CB_FAIL_THRESHOLD", "3"))
CIRCUIT_BREAKER_SKIP_SECONDS = int(os.getenv("NCL_CB_SKIP_SECONDS", "600"))

AUTH_EXPIRY_WARN_HOURS = int(os.getenv("NCL_AUTH_EXPIRY_WARN_HOURS", "48"))


# ── J8a: Stale-quote detection ───────────────────────────────────

def _is_market_open(now: Optional[datetime] = None) -> bool:
    """Crude — M-F 9:30-16:00 ET. Doesn't handle holidays; close
    enough for staleness thresholds."""
    now = now or datetime.now(timezone.utc)
    # Convert to ET. ET = UTC-5 (EST) or UTC-4 (EDT). Approximate:
    et_hour = (now.hour - 4) % 24
    return now.weekday() < 5 and 9 <= et_hour < 16


def stale_quote_check(position: dict, now: Optional[datetime] = None) -> dict:
    """Tag a position with staleness metadata.

    Looks for `quote_timestamp` (ISO) on the position. If missing,
    returns {stale_age_seconds: None, is_stale: None, threshold_s: 0,
    note: "no timestamp"} — caller decides how to treat unknown.

    Returns:
      {
        stale_age_seconds: float,
        is_stale: bool,
        threshold_s: int,
        asset_class: str,
        market_open: bool,
        note: str
      }
    """
    now = now or datetime.now(timezone.utc)
    ts_str = position.get("quote_timestamp")
    asset_class = (position.get("asset_class") or "").lower() or "default"
    threshold = STALE_THRESHOLDS_S.get(asset_class, STALE_THRESHOLDS_S["default"])
    if not _is_market_open(now) and asset_class in ("equity", "option", "future"):
        threshold = int(threshold * OFF_HOURS_MULT)
    if not ts_str:
        return {
            "stale_age_seconds": None,
            "is_stale": None,
            "threshold_s": threshold,
            "asset_class": asset_class,
            "market_open": _is_market_open(now),
            "note": "no quote_timestamp on position",
        }
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except ValueError:
        return {
            "stale_age_seconds": None,
            "is_stale": None,
            "threshold_s": threshold,
            "asset_class": asset_class,
            "market_open": _is_market_open(now),
            "note": f"unparseable quote_timestamp: {ts_str!r}",
        }
    age = (now - ts).total_seconds()
    return {
        "stale_age_seconds": round(age, 1),
        "is_stale": age > threshold,
        "threshold_s": threshold,
        "asset_class": asset_class,
        "market_open": _is_market_open(now),
        "note": (
            f"{asset_class} quote {age:.0f}s old vs {threshold}s threshold "
            f"({'STALE' if age > threshold else 'fresh'})"
        ),
    }


# ── J8b: Auth-token expiry manifest ─────────────────────────────

@dataclass
class TokenEntry:
    broker: str                # ibkr | moomoo | snaptrade | polymarket | metamask | ndax
    label: str                 # human-readable (e.g. "SnapTrade OAuth")
    expires_at_iso: str        # ISO 8601 UTC
    last_refreshed_iso: Optional[str] = None
    refresh_url: Optional[str] = None
    notes: str = ""


def load_auth_tokens() -> list[dict]:
    if not TOKEN_MANIFEST.exists():
        return []
    try:
        raw = json.loads(TOKEN_MANIFEST.read_text())
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return raw.get("tokens", [])
    except Exception as e:
        log.warning("[HYGIENE] auth_tokens load failed: %s", e)
    return []


def save_auth_tokens(tokens: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "tokens": tokens,
    }
    tmp = TOKEN_MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(TOKEN_MANIFEST)


def auth_expiry_alerts(warn_hours: int = AUTH_EXPIRY_WARN_HOURS) -> list[dict]:
    """Return tokens expiring within warn_hours, plus already-expired ones."""
    tokens = load_auth_tokens()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=warn_hours)
    out = []
    for t in tokens:
        exp = t.get("expires_at_iso")
        if not exp:
            continue
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        except ValueError:
            continue
        if exp_dt <= cutoff:
            hours_left = (exp_dt - now).total_seconds() / 3600
            out.append({
                "broker": t.get("broker"),
                "label": t.get("label"),
                "expires_at_iso": exp,
                "hours_left": round(hours_left, 2),
                "expired": hours_left < 0,
                "refresh_url": t.get("refresh_url"),
                "tier": "expired" if hours_left < 0 else
                        "imminent" if hours_left < 6 else "soon",
            })
    return sorted(out, key=lambda r: r["hours_left"])


# ── J8c: Per-adapter circuit breaker (uniform pattern) ─────────

class CircuitBreaker:
    """Three-strike circuit breaker. Generalized version of the IBKR
    adapter's pattern so every broker adapter can use the same logic.

    Usage:
      cb = get_circuit_breaker("snaptrade")
      if cb.is_open():
          return  # skip — adapter is quarantined
      try:
          ...adapter call...
          cb.record_success()
      except Exception:
          cb.record_failure()
          raise
    """

    def __init__(
        self,
        name: str,
        fail_threshold: int = CIRCUIT_BREAKER_FAIL_THRESHOLD,
        skip_seconds: int = CIRCUIT_BREAKER_SKIP_SECONDS,
    ) -> None:
        self.name = name
        self.fail_threshold = fail_threshold
        self.skip_seconds = skip_seconds
        self._fails = 0
        self._opened_at: Optional[float] = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at > self.skip_seconds:
            # Auto-reset after skip window
            self._opened_at = None
            self._fails = 0
            return False
        return True

    def record_success(self) -> None:
        self._fails = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._fails += 1
        if self._fails >= self.fail_threshold:
            self._opened_at = time.monotonic()
            log.warning(
                "[CB:%s] circuit OPEN after %d consecutive failures — "
                "skipping for %ds",
                self.name, self._fails, self.skip_seconds,
            )

    def status(self) -> dict:
        remaining_s = 0
        if self._opened_at is not None:
            remaining_s = max(0, self.skip_seconds - (time.monotonic() - self._opened_at))
        return {
            "name": self.name,
            "fails": self._fails,
            "is_open": self.is_open(),
            "remaining_skip_s": round(remaining_s, 1),
            "fail_threshold": self.fail_threshold,
            "skip_seconds": self.skip_seconds,
        }


_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKER_LOCK = asyncio.Lock()


async def get_circuit_breaker(name: str) -> CircuitBreaker:
    if name in _BREAKERS:
        return _BREAKERS[name]
    async with _BREAKER_LOCK:
        if name not in _BREAKERS:
            _BREAKERS[name] = CircuitBreaker(name)
    return _BREAKERS[name]


def all_breaker_statuses() -> list[dict]:
    return [cb.status() for cb in _BREAKERS.values()]
