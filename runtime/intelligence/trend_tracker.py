"""Wave 14CK (2026-05-31) — Time-series trend tracker.

NATRIX: "how is memory using this info to track trends and use this data
in future?" Audit showed: BERTopic captures topic structure, Cross-Ref
captures co-occurrence, working context captures recency — but nothing
tracks "AAPL mentions up 200% week-over-week" or "options_flow on NVDA
spiked 3x vs 30-day baseline". This module fills that gap.

Pipeline:

  agent_signals.jsonl
        │  (tail-scan every 30 min)
        ▼
  hourly buckets per (source, ticker)
        │  written to data/trends/buckets-YYYY-MM-DD.jsonl
        ▼
  rolling baseline computation (7d + 30d)
        │
        ▼
  threshold-cross emission
    - jump  ≥ 200% over 7d baseline   → "spiking"
    - drop  ≤ -60% under 7d baseline  → "fading"
    - z-score ≥ 3 over 30d baseline   → "anomaly"
        │
        ▼
  data/trends/alerts-YYYY-MM-DD.jsonl
  GET /intelligence/trends/today

Idempotent, append-only, no LLM cost. Pure pandas-style rollup in stdlib.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("ncl.intelligence.trend_tracker")


_TICKER_RX = re.compile(r"\$?\b([A-Z]{1,5})\b(?!\.[a-z])")
_TICKER_BLOCKLIST = frozenset({
    # Common stop-words masking as tickers
    "I", "A", "AI", "BE", "DO", "GO", "IS", "IT", "ME", "MY", "OF",
    "OK", "ON", "OR", "SO", "TO", "UP", "US", "WE", "AM", "PM", "EST",
    "PDT", "GMT", "UTC", "USD", "CEO", "CFO", "CTO", "ETF", "IPO",
    "NEW", "ALL", "ANY", "FOR", "GET", "HAS", "HOW", "OUT", "WHO",
    "WHY", "YES", "NOW", "DID", "HER", "HIS", "HIM", "ONE", "TWO",
    "OFF", "AGO", "TOP", "BIG", "LOW", "OLD", "RAW", "TBD", "VS",
    "HOT", "RED", "WAY", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
    "NOV", "DEC", "JAN", "FEB", "MAR", "APR", "MON", "TUE", "WED",
    "THU", "FRI", "SAT", "SUN",
})


def _extract_tickers(text: str) -> set[str]:
    """Wave 14CM — must clear the ticker_universe whitelist.

    Same fix as cross_reference._extract_tickers — the trend tracker
    was producing trend alerts for NOW / WILL / GREAT etc. because
    the regex alone caught any 2-5 char uppercase token. Whitelist
    gates bare uppercase; the stop-word blocklist stays as a fast
    rejection layer before the lookup.
    """
    if not text:
        return set()
    try:
        from .ticker_universe import is_valid_ticker
    except Exception:
        is_valid_ticker = None
    raw = set(_TICKER_RX.findall(text))
    out: set[str] = set()
    for t in raw:
        if t in _TICKER_BLOCKLIST:
            continue
        if not (2 <= len(t) <= 5):
            continue
        if is_valid_ticker is not None and not is_valid_ticker(t):
            continue
        out.add(t)
    return out


def _hour_bucket(ts_iso: str) -> str:
    """ISO timestamp → YYYY-MM-DDTHH bucket key."""
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    except Exception:
        return ""
    return dt.strftime("%Y-%m-%dT%H")


def _base_dir() -> Path:
    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    d = base / "data" / "trends"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _signals_path() -> Path:
    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    return base / "data" / "intelligence" / "agent_signals.jsonl"


# ── Rollup ────────────────────────────────────────────────────────────


def rollup_recent(
    *,
    lookback_hours: int = 30 * 24,
    tail_bytes: int = 50_000_000,
) -> dict[str, Any]:
    """Tail-scan agent_signals.jsonl, bucket by (source, ticker, hour).

    Returns:
      buckets[(source, ticker, hour)] = count
      and writes to data/trends/buckets-today.jsonl (overwrite atomic).
    """
    sp = _signals_path()
    if not sp.exists():
        return {"buckets": {}, "n_signals": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    cutoff_iso = cutoff.isoformat()

    buckets: dict[tuple[str, str, str], int] = defaultdict(int)
    n_signals = 0
    try:
        with sp.open("rb") as fh:
            try:
                fh.seek(-tail_bytes, os.SEEK_END)
            except OSError:
                fh.seek(0)
            else:
                fh.readline()  # skip partial
            for raw in fh:
                try:
                    sig = json.loads(raw)
                except Exception:
                    continue
                ts = sig.get("timestamp", "")
                if ts < cutoff_iso:
                    continue
                hour = _hour_bucket(ts)
                if not hour:
                    continue
                source = (sig.get("source") or "?").split(":")[0].lower()
                text = (sig.get("title") or "") + " " + (sig.get("content") or "")
                tickers = _extract_tickers(text)
                if not tickers:
                    continue
                n_signals += 1
                for tkr in tickers:
                    buckets[(source, tkr, hour)] += 1
    except Exception as e:
        log.warning("[trend-tracker] rollup failed: %s", e)
        return {"buckets": {}, "n_signals": 0}

    # Serialize (key tuples → "source|ticker|hour")
    out = {f"{s}|{t}|{h}": n for (s, t, h), n in buckets.items()}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bucket_path = _base_dir() / f"buckets-{today}.json"
    bucket_path.write_text(json.dumps({
        "as_of": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "n_signals_with_tickers": n_signals,
        "n_buckets": len(buckets),
        "buckets": out,
    }, indent=2))
    log.info(
        "[trend-tracker] rolled up %d signals into %d (source, ticker, hour) buckets",
        n_signals, len(buckets),
    )
    return {"buckets": buckets, "n_signals": n_signals}


# ── Baseline + threshold ─────────────────────────────────────────────


def compute_alerts(buckets: dict[tuple[str, str, str], int]) -> list[dict]:
    """For each (source, ticker), compute current 24h count vs 7d baseline
    vs 30d baseline. Emit alerts on threshold cross.

    Thresholds:
      - jump  ≥ 200% over 7d baseline   (current >= 3 × 7d_avg)
      - drop  ≤ -60% under 7d baseline  (current <= 0.4 × 7d_avg)
      - z-score ≥ 3 over 30d baseline   (anomaly relative to long-term)
    """
    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")
    cutoff_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H")
    cutoff_7d = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H")
    cutoff_30d = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H")

    # Group counts per (source, ticker) → list of (hour, count)
    by_key: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for (source, ticker, hour), n in buckets.items():
        by_key[(source, ticker)].append((hour, n))

    alerts: list[dict] = []
    for (source, ticker), hourly in by_key.items():
        last_24h = [n for h, n in hourly if h >= cutoff_24h]
        last_7d = [n for h, n in hourly if h >= cutoff_7d]
        last_30d = [n for h, n in hourly if h >= cutoff_30d]

        if not last_30d:
            continue

        cur_count = sum(last_24h)
        baseline_7d = sum(last_7d) / 7.0 if last_7d else 0
        baseline_30d = sum(last_30d) / 30.0 if last_30d else 0

        # Variance for z-score
        if len(last_30d) > 1:
            # bucket counts per day across 30d
            day_counts: dict[str, int] = defaultdict(int)
            for h, n in hourly:
                if h >= cutoff_30d:
                    day_counts[h.split("T")[0]] += n
            vals = list(day_counts.values()) or [0]
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
            std = math.sqrt(var) if var else 0
            z = (cur_count - mean) / std if std else 0
        else:
            z = 0
            mean = 0
            std = 0

        flags: list[str] = []
        ratio_7d = (cur_count / baseline_7d) if baseline_7d else 0
        if baseline_7d >= 1 and ratio_7d >= 3.0:
            flags.append(f"spiking_{int(ratio_7d * 100)}pct_vs_7d")
        elif baseline_7d >= 1 and ratio_7d <= 0.4:
            flags.append(f"fading_{int((1 - ratio_7d) * 100)}pct_vs_7d")
        if abs(z) >= 3:
            flags.append(f"anomaly_z{z:.1f}")

        if not flags:
            continue

        alerts.append({
            "as_of": now.isoformat(),
            "source": source,
            "ticker": ticker,
            "current_24h_mentions": cur_count,
            "baseline_7d_daily_avg": round(baseline_7d, 2),
            "baseline_30d_daily_avg": round(baseline_30d, 2),
            "ratio_vs_7d": round(ratio_7d, 2),
            "z_score_vs_30d": round(z, 2),
            "flags": flags,
        })

    # Persist
    alerts_path = _base_dir() / f"alerts-{today_iso}.json"
    alerts_path.write_text(json.dumps({
        "as_of": now.isoformat(),
        "count": len(alerts),
        "alerts": sorted(
            alerts,
            key=lambda a: (
                -abs(a["z_score_vs_30d"]),
                -a["ratio_vs_7d"],
            ),
        ),
    }, indent=2))
    log.info("[trend-tracker] emitted %d trend alerts", len(alerts))
    return alerts


# ── Single entry-point used by scheduler + REST ──────────────────────


def trend_once() -> dict[str, Any]:
    """Single rollup + alert pass. Used by the scheduler loop AND
    POST /intelligence/trends/refresh for ad-hoc fires."""
    started = datetime.now(timezone.utc)
    res = rollup_recent()
    alerts = compute_alerts(res.get("buckets") or {})
    finished = datetime.now(timezone.utc)
    return {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_s": round((finished - started).total_seconds(), 2),
        "n_signals_with_tickers": res.get("n_signals", 0),
        "n_buckets": len(res.get("buckets") or {}),
        "n_alerts": len(alerts),
        "alerts": alerts[:50],
    }


def load_today_alerts() -> dict[str, Any]:
    """Read the most recent persisted alerts file for the GET endpoint."""
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _base_dir() / f"alerts-{today_iso}.json"
    if not path.exists():
        # Fallback: yesterday
        yest = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        path = _base_dir() / f"alerts-{yest}.json"
        if not path.exists():
            return {"as_of": None, "count": 0, "alerts": []}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"as_of": None, "count": 0, "alerts": []}


__all__ = [
    "rollup_recent",
    "compute_alerts",
    "trend_once",
    "load_today_alerts",
]
