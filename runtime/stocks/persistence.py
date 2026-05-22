"""Scanner persistence — JSONL log + MemoryStore async-writer enqueue.

Shipped 2026-05-22 EOD as Feature 1 of scanner hardening.

- Append every scan hit to ``data/scanners/{name}-{YYYY-MM-DD}.jsonl``
  (one row per hit). Atomic-ish: open(append) is one syscall on POSIX.
- Enqueue every hit into MemoryStore via ``async_writer.AsyncMemoryWriter``
  with the source ``scanner:goat`` or ``scanner:bravo`` (mapped to
  AuthorityTier.SCANNER by authority.tier_for_source — see runtime/memory/authority.py).
- Importance: 70 for GOAT (high-conviction technical setup), 55 for BRAVO
  (swing setup, lower individual weight).

Callers pass the already-enriched result rows. We never enrich here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.stocks.persistence")

GOAT_IMPORTANCE = 70.0
BRAVO_IMPORTANCE = 55.0


def _resolve_scanners_dir() -> Path:
    base = Path(os.getenv("NCL_DATA_DIR", "data"))
    if not base.is_absolute():
        # runtime/stocks/persistence.py -> parents[2] = NCL root
        base = Path(__file__).resolve().parents[2] / base
    d = base / "scanners"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _atomic_append(path: Path, line: str) -> None:
    """POSIX append is atomic for writes < PIPE_BUF (~4K). Scanner rows are
    well under that. We open-append-close per-line to avoid holding a handle.
    """
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        if not line.endswith("\n"):
            f.write("\n")


def persist_jsonl(scanner_name: str, rows: list[dict[str, Any]]) -> Path:
    """Append rows to ``data/scanners/{name}-{YYYY-MM-DD}.jsonl``. Returns path.

    ``scanner_name`` may be ``goat``, ``bravo``, or the namespaced form
    ``scanner:goat`` / ``scanner:bravo`` — the colon prefix is stripped so
    the on-disk file is just ``goat-2026-05-22.jsonl``.
    """
    short = scanner_name.split(":")[-1] if ":" in scanner_name else scanner_name
    if not rows:
        return _resolve_scanners_dir() / f"{short}-{_today_str()}.jsonl"
    path = _resolve_scanners_dir() / f"{short}-{_today_str()}.jsonl"
    scan_at = datetime.now(timezone.utc).isoformat()
    try:
        for row in rows:
            payload = dict(row)
            payload.setdefault("scan_at", scan_at)
            payload.setdefault("scanner", scanner_name)
            _atomic_append(path, json.dumps(payload, default=str))
    except Exception as e:
        log.warning("scanner JSONL append failed (%s): %s", path, e)
    return path


def _direction_for_row(scanner_name: str, row: dict[str, Any]) -> str:
    """Best-effort long/short label. GOAT is always long-bias by design.
    BRAVO uses signal_label — EXIT/SELL → short, otherwise long.
    """
    if scanner_name == "scanner:goat":
        return "long"
    label = (row.get("signal_label") or "").upper()
    if label in ("EXIT", "SELL"):
        return "short"
    return "long"


def _build_tags(scanner_name: str, row: dict[str, Any]) -> list[str]:
    short = scanner_name.split(":")[-1]  # 'goat' or 'bravo'
    sym = (row.get("ticker") or row.get("symbol") or "").upper()
    sector = (row.get("sector") or "unknown").lower().replace(" ", "_")
    direction = _direction_for_row(scanner_name, row)
    out = ["scanner", short]
    if sym:
        out.append(sym)
    if sector and sector != "unknown":
        out.append(sector)
    out.append(direction)
    if row.get("held_in_portfolio"):
        out.append("held")
    if row.get("flow_confirms") is True:
        out.append("flow_confirmed")
    if row.get("squeeze_candidate"):
        out.append("squeeze")
    return out


def _build_content(scanner_name: str, row: dict[str, Any]) -> str:
    short = scanner_name.split(":")[-1].upper()
    sym = row.get("ticker") or "?"
    price = row.get("price")
    score_key = "goat_score" if "goat" in scanner_name else "bravo_score"
    score = row.get(score_key, 0)
    label = row.get("signal_label") or ""
    extras: list[str] = []
    if row.get("ivr") is not None:
        extras.append(f"IVR={row['ivr']:.0f}")
    if row.get("flow_confirms") is True:
        extras.append("flow_confirms=true")
    if row.get("days_to_earnings") is not None:
        extras.append(f"earnings_in={row['days_to_earnings']}d")
    if row.get("dark_pool_support"):
        extras.append(f"dp_support=${row['dark_pool_support']:.2f}")
    extra_str = (" | " + " | ".join(extras)) if extras else ""
    label_str = f" {label}" if label else ""
    return (
        f"[{short}{label_str}] {sym} @ ${price} | score={score} | "
        f"stop=${row.get('stop_loss', 0)} | rr={row.get('risk_reward', row.get('risk_pct', 0))}"
        f"{extra_str}"
    )


def _build_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Whitelist of numeric/string fields safe to drop into MemoryStore metadata."""
    keep = {
        "ticker", "symbol", "price", "change_pct",
        "goat_score", "bravo_score",
        "stop_loss", "target_1", "target_2", "target_3", "risk_reward",
        "atr", "volume_ratio", "rsi", "support",
        "vix", "vix_risk",
        "sma9", "ema20", "sma180", "sma200",
        "ma_aligned", "all_sloping_up", "entry_signal", "exit_signal",
        "caution_signal", "is_green_candle", "gogo_juice", "bollinger_squeeze",
        "signal_label", "risk_pct",
        # Enrichment fields (Features 4/5/6)
        "liquidity_pass", "avg_daily_volume", "market_cap_usd",
        "option_oi_total", "days_to_earnings", "ivr",
        "flow_confirms", "net_call_premium_24h", "call_put_ratio",
        "squeeze_candidate",
        "dark_pool_support", "dark_pool_volume", "dark_pool_date",
        "held_in_portfolio", "position_value_usd", "position_account",
        "sector", "name",
    }
    return {k: row[k] for k in keep if k in row}


async def enqueue_to_memory(
    async_writer,
    scanner_name: str,
    rows: list[dict[str, Any]],
) -> int:
    """Enqueue each hit as a memory write request. Returns count enqueued.

    No-op when ``async_writer`` is None (e.g. ad-hoc CLI scan with no Brain).
    """
    if async_writer is None or not rows:
        return 0
    try:
        from ..memory.async_writer import WriteRequest
    except Exception as e:
        log.debug("async_writer import failed (memory disabled?): %s", e)
        return 0

    importance = GOAT_IMPORTANCE if "goat" in scanner_name else BRAVO_IMPORTANCE
    scan_at = datetime.now(timezone.utc).isoformat()
    enqueued = 0
    for row in rows:
        try:
            md = _build_metadata(row)
            md["scan_at"] = scan_at
            await async_writer.enqueue(WriteRequest(
                content=_build_content(scanner_name, row),
                source=scanner_name,
                importance=float(importance),
                memory_type="signal",
                tags=_build_tags(scanner_name, row),
                entities=[(row.get("ticker") or "").upper()] if row.get("ticker") else [],
                metadata=md,
            ))
            enqueued += 1
        except Exception as e:
            log.debug("enqueue failed for %s: %s", row.get("ticker"), e)
    return enqueued


async def persist_and_enqueue(
    scanner_name: str,
    rows: list[dict[str, Any]],
    async_writer=None,
) -> dict[str, Any]:
    """One-shot: JSONL append + memory enqueue. Returns ``{path, persisted, enqueued}``."""
    path = persist_jsonl(scanner_name, rows)
    enqueued = await enqueue_to_memory(async_writer, scanner_name, rows)
    return {
        "jsonl_path": str(path),
        "persisted": len(rows),
        "enqueued_memory": enqueued,
    }
