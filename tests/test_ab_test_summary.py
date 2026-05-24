"""W8-A14 D7: A/B test summary harness math.

``runtime.memory.ab_test.compute_summary`` is the offline harness that
reads ``$NCL_DATA_DIR/memory/ab_test/scores.jsonl`` and emits a daily
recommendation (``swap`` / ``keep`` / ``needs_more_data``). The summary
math is pure — no LLM calls — so it's a perfect place for fast, locked-in
unit tests. The actual paired-call LLM evaluation
(``score_memory_ab``) is left to integration tests.

Recommendation rules (from ab_test.py):

* ``needs_more_data`` if paired_rows < 50
* ``keep`` if p95_abs_delta > 1.5    (Haiku diverges on edge cases)
* ``keep`` if haiku_errors / rows > 5%
* ``swap`` otherwise
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _reload_ab(monkeypatch, data_root: Path):
    """Force ab_test to re-read NCL_DATA_DIR."""
    monkeypatch.setenv("NCL_DATA_DIR", str(data_root))
    import runtime.memory.ab_test as ab

    return importlib.reload(ab)


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _row(
    *,
    sonnet_score: float | None,
    haiku_score: float | None,
    sonnet_latency: int = 600,
    haiku_latency: int = 250,
    sonnet_cost: float = 0.02,
    haiku_cost: float = 0.005,
    ts: str | None = None,
) -> dict:
    return {
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "sonnet": {"score": sonnet_score, "latency_ms": sonnet_latency},
        "haiku": {"score": haiku_score, "latency_ms": haiku_latency},
        "cost_usd_sonnet": sonnet_cost,
        "cost_usd_haiku": haiku_cost,
    }


def test_summary_empty_returns_needs_more_data(tmp_path, monkeypatch):
    ab = _reload_ab(monkeypatch, tmp_path)
    summary = ab.compute_summary(window_hours=24)

    assert summary["rows"] == 0
    assert summary["recommendation"] == "needs_more_data"
    assert summary["window_hours"] == 24


def test_summary_below_threshold_returns_needs_more_data(tmp_path, monkeypatch):
    """5 paired rows < 50 paired threshold → ``needs_more_data``."""
    ab = _reload_ab(monkeypatch, tmp_path)
    scores_path = tmp_path / "memory" / "ab_test" / "scores.jsonl"
    _write_rows(
        scores_path,
        [_row(sonnet_score=7.0, haiku_score=6.5) for _ in range(5)],
    )

    s = ab.compute_summary(window_hours=24)
    assert s["rows"] == 5
    assert s["rows_with_both_scores"] == 5
    assert s["recommendation"] == "needs_more_data"


def test_summary_tight_agreement_recommends_swap(tmp_path, monkeypatch):
    """50+ paired rows + tight agreement (p95 ≤ 1.5, no error spike) → ``swap``."""
    ab = _reload_ab(monkeypatch, tmp_path)
    scores_path = tmp_path / "memory" / "ab_test" / "scores.jsonl"
    _write_rows(
        scores_path,
        [_row(sonnet_score=7.0, haiku_score=6.7) for _ in range(60)],
    )

    s = ab.compute_summary(window_hours=24)
    assert s["rows"] == 60
    assert s["rows_with_both_scores"] == 60
    assert s["recommendation"] == "swap"
    # Sanity: positive savings because Haiku is cheaper per row.
    assert s["savings_pct_if_switched"] > 0
    # Mean abs delta computed correctly.
    assert pytest.approx(s["mean_abs_delta"], abs=1e-2) == 0.3


def test_summary_edge_case_divergence_recommends_keep(tmp_path, monkeypatch):
    """p95_abs_delta > 1.5 on enough rows → ``keep`` (Haiku unsafe on edge cases)."""
    ab = _reload_ab(monkeypatch, tmp_path)
    scores_path = tmp_path / "memory" / "ab_test" / "scores.jsonl"
    rows = [_row(sonnet_score=7.0, haiku_score=6.8) for _ in range(54)]
    # Inject 6 wildly-divergent rows (≈10% of the dataset) so p95 > 1.5.
    rows.extend([_row(sonnet_score=7.0, haiku_score=2.5) for _ in range(6)])
    _write_rows(scores_path, rows)

    s = ab.compute_summary(window_hours=24)
    assert s["rows_with_both_scores"] == 60
    assert s["p95_abs_delta"] > 1.5
    assert s["recommendation"] == "keep"


def test_summary_haiku_error_rate_recommends_keep(tmp_path, monkeypatch):
    """>5% Haiku errors → ``keep`` even if scores agree on the paired subset.

    Errors are rows where ``haiku.score is None``. The ratio is computed
    against ``len(rows)`` (total) not ``paired`` (with both scores).
    """
    ab = _reload_ab(monkeypatch, tmp_path)
    scores_path = tmp_path / "memory" / "ab_test" / "scores.jsonl"
    # 50 clean paired rows + 10 haiku errors → 10/60 = 16.7% > 5%.
    rows = [_row(sonnet_score=7.0, haiku_score=6.9) for _ in range(50)]
    rows.extend([_row(sonnet_score=7.0, haiku_score=None) for _ in range(10)])
    _write_rows(scores_path, rows)

    s = ab.compute_summary(window_hours=24)
    assert s["rows"] == 60
    assert s["haiku_errors"] == 10
    assert s["recommendation"] == "keep"


def test_summary_filters_outside_window(tmp_path, monkeypatch):
    """Rows older than ``window_hours`` are excluded from the dataset."""
    ab = _reload_ab(monkeypatch, tmp_path)
    scores_path = tmp_path / "memory" / "ab_test" / "scores.jsonl"

    # 60 rows from now (in-window) + 20 rows stamped 10 days ago (out-of-window).
    in_window = [_row(sonnet_score=7.0, haiku_score=6.8) for _ in range(60)]
    old_ts = "2020-01-01T00:00:00+00:00"
    out_of_window = [_row(sonnet_score=5.0, haiku_score=5.0, ts=old_ts) for _ in range(20)]
    _write_rows(scores_path, in_window + out_of_window)

    s = ab.compute_summary(window_hours=24)
    assert s["rows"] == 60  # only the in-window rows


def test_summary_handles_corrupt_lines_gracefully(tmp_path, monkeypatch):
    """Bad JSON lines are skipped, not fatal — harness must survive partial corruption."""
    ab = _reload_ab(monkeypatch, tmp_path)
    scores_path = tmp_path / "memory" / "ab_test" / "scores.jsonl"
    scores_path.parent.mkdir(parents=True, exist_ok=True)

    good = json.dumps(_row(sonnet_score=7.0, haiku_score=6.8))
    with scores_path.open("w", encoding="utf-8") as fh:
        fh.write(good + "\n")
        fh.write("{not valid json\n")
        fh.write("\n")  # blank line
        fh.write(good + "\n")

    s = ab.compute_summary(window_hours=24)
    # Two good rows survived; one corrupt + one blank skipped without error.
    assert s["rows"] == 2
