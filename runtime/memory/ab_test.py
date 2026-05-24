"""Sonnet ⇄ Haiku A/B test harness for memory enrichment.

Goal
----
Before flipping any utility-path call site from Sonnet 4 → Haiku 4.5, run
both models in parallel against the *same* memory write for a week, persist
both outputs, and compute summary metrics. Decision (swap / keep) is then
data-driven instead of vibes-driven.

Active vs shadow
----------------
- **Active**: the Sonnet result. This is what flows into ``req.importance``,
  ``unit.memory_type``, downstream salience, etc. Nothing about production
  behavior changes while A/B is on.
- **Shadow**: the Haiku result. Written to disk alongside the Sonnet result
  for offline comparison. Never affects the live unit.

Enablement
----------
Set ``NCL_AB_HAIKU=true`` in ``.env`` to turn it on. Default OFF so a
restart with no flag is a no-op — easy revert.

Files
-----
``data/memory/ab_test/scores.jsonl`` — one row per memory write that ran A/B.
Schema::

    {
      "ts": "2026-05-24T07:00:00Z",
      "kind": "importance",
      "unit_id": "u-...",
      "source": "reddit",
      "tags_count": 4,
      "content_chars": 487,
      "sonnet": {"score": 7.0, "latency_ms": 612, "tokens_in": 240, "tokens_out": 28},
      "haiku":  {"score": 6.5, "latency_ms": 285, "tokens_in": 240, "tokens_out": 26},
      "delta": -0.5,
      "cost_usd_sonnet": 0.00114,
      "cost_usd_haiku":  0.00030
    }

``data/memory/ab_test/entities.jsonl`` — same shape but for entity extraction.

``data/memory/ab_test/daily-summary-YYYY-MM-DD.json`` — written by the
scheduler loop every 24h, summarizes the prior day.

Compute paths
-------------
- ``score_memory_ab(...)`` — drop-in replacement for ``score_memory`` that
  runs Sonnet + Haiku concurrently, persists comparison, returns the
  Sonnet result (active) to the caller. Caller code is unchanged.
- ``compute_summary(window_hours)`` — reads the JSONL, returns dict with
  mean abs delta, p50/p95 delta, type-agreement rate, distribution stats,
  cost reality vs projection.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional  # noqa: F401

from ..config import flags

log = logging.getLogger("ncl.memory.ab_test")

# ── Configuration ─────────────────────────────────────────────────────────

SONNET_MODEL = "claude-sonnet-4-20250514"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Pricing — keep in sync with runtime/llm/models.py.
SONNET_INPUT_PER_MTOK = 3.00
SONNET_OUTPUT_PER_MTOK = 15.00
HAIKU_INPUT_PER_MTOK = 0.80
HAIKU_OUTPUT_PER_MTOK = 4.00

# JSONL store roots. ``ab_test/`` is created lazily on first write.
_DEFAULT_DATA_ROOT = Path("/Users/natrix/dev/NCL/data/memory/ab_test")


def is_ab_enabled() -> bool:
    """True iff the operator has set ``NCL_AB_HAIKU=true`` in env."""
    return flags.ab_haiku_enabled()


def _data_root() -> Path:
    root = Path(os.environ.get("NCL_DATA_DIR", "/Users/natrix/dev/NCL/data")) / "memory" / "ab_test"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── Persistence ───────────────────────────────────────────────────────────


def _append_jsonl(path: Path, row: dict) -> None:
    """Append a single JSON row. Best-effort — never raise to caller."""
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception as e:
        log.debug("[AB] append %s failed: %s", path.name, e)


def record_importance(
    *,
    unit_id: Optional[str],
    source: str,
    tags: list[str],
    content_chars: int,
    sonnet_score: Optional[float],
    sonnet_latency_ms: int,
    haiku_score: Optional[float],
    haiku_latency_ms: int,
    tokens_in: int = 0,
    tokens_out_sonnet: int = 0,
    tokens_out_haiku: int = 0,
) -> None:
    """Persist one importance-score comparison row."""
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "importance",
        "unit_id": unit_id,
        "source": source,
        "tags_count": len(tags or []),
        "content_chars": content_chars,
        "sonnet": {
            "score": sonnet_score,
            "latency_ms": sonnet_latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out_sonnet,
        },
        "haiku": {
            "score": haiku_score,
            "latency_ms": haiku_latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out_haiku,
        },
        "delta": (
            (haiku_score - sonnet_score)
            if sonnet_score is not None and haiku_score is not None
            else None
        ),
        "cost_usd_sonnet": _cost(tokens_in, tokens_out_sonnet, SONNET_INPUT_PER_MTOK, SONNET_OUTPUT_PER_MTOK),  # noqa: E501
        "cost_usd_haiku": _cost(tokens_in, tokens_out_haiku, HAIKU_INPUT_PER_MTOK, HAIKU_OUTPUT_PER_MTOK),  # noqa: E501
    }
    _append_jsonl(_data_root() / "scores.jsonl", row)


def _cost(tokens_in: int, tokens_out: int, in_rate: float, out_rate: float) -> float:
    return round((tokens_in * in_rate + tokens_out * out_rate) / 1_000_000.0, 6)


# ── Parallel scoring ──────────────────────────────────────────────────────


@dataclass
class _ScoreCall:
    """Result of one model's importance-score call."""

    score: Optional[float] = None
    latency_ms: int = 0
    error: Optional[str] = None


async def _call_one(
    *,
    content: str,
    source: str,
    tags: list[str],
    model: str,
    timeout: float,
) -> _ScoreCall:
    """Call ``llm_importance_score`` for one model, capture latency + errors."""
    # Local import — avoid circular ``ab_test → importance_scorer → ab_test``
    # while still being able to test in isolation.
    from .importance_scorer import llm_importance_score

    t0 = time.perf_counter()
    try:
        score = await llm_importance_score(content, source, tags, timeout=timeout, model=model)
        return _ScoreCall(score=score, latency_ms=int((time.perf_counter() - t0) * 1000))
    except Exception as e:
        return _ScoreCall(
            score=None,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error=f"{type(e).__name__}: {e}"[:160],
        )


async def score_memory_ab(
    content: str,
    source: str = "",
    tags: Optional[list[str]] = None,
    use_llm: bool = True,
    timeout: float = 30.0,
    unit_id: Optional[str] = None,
) -> dict:
    """Drop-in replacement for ``score_memory`` that fires Sonnet + Haiku in parallel.

    Returns the SONNET result so callers see no behavior change. Haiku is
    shadow-recorded for offline analysis.

    If ``NCL_AB_HAIKU`` is not enabled, this is a no-op pass-through to the
    plain ``score_memory`` so call sites can be wired safely.
    """
    tags = tags or []

    # Pass-through when A/B is off — keeps the call-site change one-line.
    if not is_ab_enabled() or not use_llm:
        from .importance_scorer import score_memory
        return await score_memory(content, source, tags, use_llm=use_llm, model=SONNET_MODEL)

    # Both models, concurrent. ``asyncio.gather`` keeps wall-clock = max(sonnet, haiku).
    sonnet_task = _call_one(content=content, source=source, tags=tags, model=SONNET_MODEL, timeout=timeout)  # noqa: E501
    haiku_task = _call_one(content=content, source=source, tags=tags, model=HAIKU_MODEL, timeout=timeout)  # noqa: E501
    sonnet, haiku = await asyncio.gather(sonnet_task, haiku_task)

    # Persist the comparison row. tokens_in/out aren't returned by
    # llm_importance_score yet — leave 0 for now; tighten later when the
    # facade surfaces them.
    record_importance(
        unit_id=unit_id,
        source=source,
        tags=tags,
        content_chars=len(content or ""),
        sonnet_score=sonnet.score,
        sonnet_latency_ms=sonnet.latency_ms,
        haiku_score=haiku.score,
        haiku_latency_ms=haiku.latency_ms,
    )

    # Reuse score_memory's final-score blending logic by going back through
    # the rule-based component. Equivalent to: call score_memory normally
    # but with llm_score forced to the value we already have.
    from .importance_scorer import rule_based_score

    rule_score = rule_based_score(content, source, tags)
    llm_score = sonnet.score  # Active = Sonnet during shadow phase.

    if llm_score is not None:
        final = (llm_score * 10 * 0.7) + (rule_score * 10 * 0.3)
    else:
        final = rule_score * 10

    # Same type-inference as score_memory.
    content_lower = content.lower()
    memory_type = "episodic"
    if any(kw in content_lower for kw in ["decided", "decision", "approved", "committed"]):
        memory_type = "decision"
    elif any(kw in content_lower for kw in ["prefer", "always", "never", "like", "dislike"]):
        memory_type = "preference"
    elif any(kw in content_lower for kw in ["procedure", "workflow", "how to", "step 1"]):
        memory_type = "procedural"
    elif any(kw in content_lower for kw in ["alert", "signal", "trend", "spike", "breaking"]):
        memory_type = "signal"
    elif any(kw in content_lower for kw in ["fact:", "definition:", "means:", "is a"]):
        memory_type = "semantic"

    return {
        "llm_score": llm_score,
        "rule_score": rule_score,
        "final_score": max(0.0, min(100.0, final)),
        "memory_type": memory_type,
    }


# ── Summary computation ───────────────────────────────────────────────────


def compute_summary(window_hours: int = 24) -> dict:
    """Read scores.jsonl and produce a summary dict for the trailing window.

    Returns
    -------
    dict with keys::

        {
          "window_hours": 24,
          "rows": 142,
          "rows_with_both_scores": 138,
          "mean_abs_delta": 0.42,
          "p50_abs_delta": 0.4,
          "p95_abs_delta": 1.2,
          "max_abs_delta": 2.3,
          "haiku_lower_count": 60,
          "haiku_higher_count": 55,
          "haiku_equal_count": 23,
          "sonnet_mean": 6.8,
          "haiku_mean": 6.7,
          "sonnet_p50_latency_ms": 612,
          "haiku_p50_latency_ms": 285,
          "cost_sonnet_usd": 0.18,
          "cost_haiku_usd": 0.05,
          "savings_pct_if_switched": 72.2,
          "sonnet_errors": 0,
          "haiku_errors": 2,
          "recommendation": "swap" | "keep" | "needs_more_data"
        }
    """
    path = _data_root() / "scores.jsonl"
    if not path.exists():
        return {"window_hours": window_hours, "rows": 0, "recommendation": "needs_more_data"}

    cutoff = time.time() - window_hours * 3600

    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                # Filter to window.
                ts = row.get("ts", "")
                try:
                    ts_epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                if ts_epoch < cutoff:
                    continue
                rows.append(row)
    except Exception as e:
        log.warning("[AB] compute_summary read failed: %s", e)
        return {"window_hours": window_hours, "rows": 0, "error": str(e)}

    if not rows:
        return {"window_hours": window_hours, "rows": 0, "recommendation": "needs_more_data"}

    paired = [r for r in rows if r.get("sonnet", {}).get("score") is not None and r.get("haiku", {}).get("score") is not None]  # noqa: E501

    sonnet_scores = [r["sonnet"]["score"] for r in paired]
    haiku_scores = [r["haiku"]["score"] for r in paired]
    deltas = [abs(s - h) for s, h in zip(sonnet_scores, haiku_scores)]
    signed = [h - s for s, h in zip(sonnet_scores, haiku_scores)]

    def _pct(vals: list[float], q: float) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
        return float(s[idx])

    sonnet_latencies = [r["sonnet"]["latency_ms"] for r in rows if r["sonnet"].get("latency_ms")]
    haiku_latencies = [r["haiku"]["latency_ms"] for r in rows if r["haiku"].get("latency_ms")]

    cost_sonnet = sum(r.get("cost_usd_sonnet", 0.0) for r in rows)
    cost_haiku = sum(r.get("cost_usd_haiku", 0.0) for r in rows)
    savings_pct = ((cost_sonnet - cost_haiku) / cost_sonnet * 100.0) if cost_sonnet > 0 else 0.0

    sonnet_errors = sum(1 for r in rows if r.get("sonnet", {}).get("score") is None)
    haiku_errors = sum(1 for r in rows if r.get("haiku", {}).get("score") is None)

    # Recommendation rule (tuned for caution):
    #   * needs_more_data if paired < 50
    #   * keep if p95_abs_delta > 1.5 (Haiku diverges meaningfully on edge cases)
    #   * keep if haiku_errors/rows > 5%
    #   * swap otherwise
    mean_abs = sum(deltas) / len(deltas) if deltas else 0.0
    p95_abs = _pct(deltas, 0.95)

    if len(paired) < 50:
        recommendation = "needs_more_data"
    elif p95_abs > 1.5:
        recommendation = "keep"
    elif haiku_errors / max(1, len(rows)) > 0.05:
        recommendation = "keep"
    else:
        recommendation = "swap"

    return {
        "window_hours": window_hours,
        "rows": len(rows),
        "rows_with_both_scores": len(paired),
        "mean_abs_delta": round(mean_abs, 3),
        "p50_abs_delta": round(_pct(deltas, 0.5), 3),
        "p95_abs_delta": round(p95_abs, 3),
        "max_abs_delta": round(max(deltas) if deltas else 0.0, 3),
        "haiku_lower_count": sum(1 for d in signed if d < 0),
        "haiku_higher_count": sum(1 for d in signed if d > 0),
        "haiku_equal_count": sum(1 for d in signed if d == 0),
        "mean_signed_delta": round(sum(signed) / len(signed), 3) if signed else 0.0,
        "sonnet_mean": round(sum(sonnet_scores) / len(sonnet_scores), 3) if sonnet_scores else 0.0,
        "haiku_mean": round(sum(haiku_scores) / len(haiku_scores), 3) if haiku_scores else 0.0,
        "sonnet_p50_latency_ms": int(_pct(sonnet_latencies, 0.5)) if sonnet_latencies else 0,
        "haiku_p50_latency_ms": int(_pct(haiku_latencies, 0.5)) if haiku_latencies else 0,
        "cost_sonnet_usd": round(cost_sonnet, 4),
        "cost_haiku_usd": round(cost_haiku, 4),
        "savings_pct_if_switched": round(savings_pct, 1),
        "sonnet_errors": sonnet_errors,
        "haiku_errors": haiku_errors,
        "recommendation": recommendation,
    }


def write_daily_summary() -> dict:
    """Compute 24h summary, write it to data/memory/ab_test/daily-summary-YYYY-MM-DD.json.

    Returns the summary dict (also written to disk).
    """
    summary = compute_summary(window_hours=24)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    out = _data_root() / f"daily-summary-{today}.json"
    try:
        out.write_text(json.dumps(summary, indent=2))
    except Exception as e:
        log.warning("[AB] write_daily_summary failed: %s", e)
    return summary


__all__ = [
    "is_ab_enabled",
    "score_memory_ab",
    "record_importance",
    "compute_summary",
    "write_daily_summary",
    "SONNET_MODEL",
    "HAIKU_MODEL",
]
