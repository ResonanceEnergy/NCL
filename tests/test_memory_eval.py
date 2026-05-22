"""Tests for the weekly memory eval harness (Loop 2)."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.memory.eval.runner import MemoryEvalRunner, _MiniBM25, _tokenize
from runtime.memory.eval.loop import _seconds_until_sunday_3am_et


# ─── Stub memory store ──────────────────────────────────────────────────


class _StubUnit:
    def __init__(self, content: str, tags: list[str] | None = None):
        self.content = content
        self.tags = tags or []


class _StubStore:
    def __init__(self, units: list[_StubUnit], data_dir: Path | None = None):
        self._units = units
        self.data_dir = Path(data_dir) if data_dir else Path(tempfile.mkdtemp())

    async def search_units(self, days_back=None, tags=None, importance_threshold=0.0):
        return list(self._units)


def _write_questions(path: Path, items: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")


# ─── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_questions_parses_jsonl(tmp_path):
    qp = tmp_path / "questions.jsonl"
    _write_questions(qp, [
        {"id": "T001", "question": "what is X?", "expected_keywords": ["x"], "min_units": 1, "category": "system"},
        {"id": "T002", "question": "Y?", "expected_keywords": ["y", "Z"], "category": "system"},
    ])
    # Junk lines and a malformed line should be skipped
    with qp.open("a") as f:
        f.write("\n# comment\n")
        f.write("{not-json\n")

    runner = MemoryEvalRunner(
        memory_store=_StubStore([], data_dir=tmp_path),
        questions_path=qp,
        results_dir=tmp_path / "out",
    )
    questions = await runner.load_questions()
    assert len(questions) == 2
    assert questions[0]["id"] == "T001"
    # Keywords lowercased
    assert questions[1]["expected_keywords"] == ["y", "z"]
    # Default min_units back-filled
    assert questions[1]["min_units"] == 1


@pytest.mark.asyncio
async def test_hit5_and_mrr_math(tmp_path):
    """Top result matches → hit@5 True, MRR 1.0."""
    units = [
        _StubUnit("The Awarebot scans Reddit and YouTube and Polymarket"),
        _StubUnit("Unrelated text about gardening"),
        _StubUnit("More unrelated chatter about weather"),
    ]
    runner = MemoryEvalRunner(memory_store=_StubStore(units, tmp_path), results_dir=tmp_path)
    retrieved = await runner._retrieve("Awarebot Reddit YouTube", limit=5)
    metrics = runner.score_question(retrieved, {
        "expected_keywords": ["reddit", "youtube"],
        "min_units": 1,
    })
    assert metrics["hit5"] is True
    assert metrics["hit10"] is True
    assert metrics["mrr"] == pytest.approx(1.0)
    assert metrics["recall10"] == pytest.approx(1.0)
    assert metrics["first_hit_rank"] == 1


@pytest.mark.asyncio
async def test_mrr_with_lower_rank(tmp_path):
    """Match at rank 3 → MRR = 1/3."""
    units = [
        _StubUnit("nothing relevant here"),
        _StubUnit("still not it"),
        _StubUnit("FOMC happens on Wednesday and impacts VIX"),
        _StubUnit("more noise"),
    ]
    runner = MemoryEvalRunner(memory_store=_StubStore(units, tmp_path), results_dir=tmp_path)
    # Force the BM25 ranker by querying for the keywords
    retrieved = await runner._retrieve("FOMC VIX Wednesday", limit=10)
    rank = runner._first_hit_rank(retrieved, ["fomc", "vix"])
    metrics = runner.score_question(retrieved, {"expected_keywords": ["fomc", "vix"], "min_units": 1})
    assert rank == 1  # BM25 should push the matching doc up to rank 1
    assert metrics["mrr"] == pytest.approx(1.0 / rank)

    # And explicit test: manually arranged list with the match at index 2
    manual = [_StubUnit("a"), _StubUnit("b"), _StubUnit("contains fomc and vix"), _StubUnit("d")]
    metrics_manual = runner.score_question(manual, {"expected_keywords": ["fomc", "vix"], "min_units": 1})
    assert metrics_manual["hit5"] is True
    assert metrics_manual["mrr"] == pytest.approx(1.0 / 3)


@pytest.mark.asyncio
async def test_recall_at_10_partial_coverage(tmp_path):
    """Only some keywords appear → recall fractional."""
    units = [
        _StubUnit("Bitcoin price today"),
        _StubUnit("Ethereum gas fees"),
    ]
    runner = MemoryEvalRunner(memory_store=_StubStore(units, tmp_path), results_dir=tmp_path)
    metrics = runner.score_question(units, {
        "expected_keywords": ["bitcoin", "ethereum", "solana", "cardano"],
        "min_units": 1,
    })
    # 2 of 4 keywords present
    assert metrics["recall10"] == pytest.approx(0.5)
    # No single unit contains ALL keywords → hit5 False
    assert metrics["hit5"] is False
    assert metrics["first_hit_rank"] is None
    assert metrics["mrr"] == 0.0


@pytest.mark.asyncio
async def test_run_eval_writes_results_and_aggregates(tmp_path):
    qp = tmp_path / "q.jsonl"
    _write_questions(qp, [
        {"id": "A", "question": "polymarket trading", "expected_keywords": ["polymarket"], "category": "x", "min_units": 1},
        {"id": "B", "question": "edmonton sun", "expected_keywords": ["edmonton"], "category": "y", "min_units": 1},
    ])
    units = [
        _StubUnit("decided to fund my polymarket account"),
        _StubUnit("edmonton sunrise data for the calendar"),
    ]
    out_dir = tmp_path / "results"
    runner = MemoryEvalRunner(
        memory_store=_StubStore(units, tmp_path),
        questions_path=qp,
        results_dir=out_dir,
    )
    result = await runner.run_eval()
    assert result["question_count"] == 2
    assert "aggregate" in result and "per_category" in result
    assert result["aggregate"]["hit5"] == pytest.approx(1.0)
    # Persisted
    files = list(out_dir.glob("results-*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text())
    assert on_disk["question_count"] == 2


@pytest.mark.asyncio
async def test_baseline_regression_detected(tmp_path):
    qp = tmp_path / "q.jsonl"
    _write_questions(qp, [
        {"id": "A", "question": "polymarket", "expected_keywords": ["polymarket"], "category": "x", "min_units": 1},
    ])

    out_dir = tmp_path / "results"
    out_dir.mkdir()
    # Seed an artificially HIGH baseline
    baseline = {
        "date": "2026-05-14",
        "timestamp": "2026-05-14T03:00:00+00:00",
        "question_count": 1,
        "aggregate": {"hit5": 1.0, "hit10": 1.0, "mrr": 1.0, "recall10": 1.0},
        "per_category": {},
        "per_question": [],
    }
    (out_dir / "results-2026-05-14.json").write_text(json.dumps(baseline))

    # Current run on an empty store → 0.0 across the board.
    runner = MemoryEvalRunner(
        memory_store=_StubStore([], tmp_path),
        questions_path=qp,
        results_dir=out_dir,
    )
    current = await runner.run_eval()
    diff = await runner.compare_to_baseline(current=current)

    assert diff["regression"] is True
    assert diff["baseline_date"] == "2026-05-14"
    # All metrics dropped to 0 → deltas are -1.0
    assert diff["deltas"]["hit5"] == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_baseline_no_prior_run(tmp_path):
    qp = tmp_path / "q.jsonl"
    _write_questions(qp, [{"id": "A", "question": "x", "expected_keywords": ["x"], "category": "z", "min_units": 1}])
    runner = MemoryEvalRunner(
        memory_store=_StubStore([_StubUnit("x match")], tmp_path),
        questions_path=qp,
        results_dir=tmp_path / "fresh",
    )
    current = await runner.run_eval()
    diff = await runner.compare_to_baseline(current=current)
    # No prior file at all (only the just-written one) — should not regress.
    assert diff["regression"] is False
    assert diff["baseline_date"] is None


def test_sunday_3am_scheduler_helper():
    """Sanity-check the cron-style time helper."""
    secs = _seconds_until_sunday_3am_et()
    # Always in the future, at most 7 days + 4h.
    assert 0 < secs <= 7 * 24 * 3600 + 4 * 3600


def test_minibm25_ranks_relevant_doc_first():
    docs = [
        _tokenize("apple banana cherry"),
        _tokenize("the quick fox jumps"),
        _tokenize("nuclear fusion reactor"),
    ]
    bm25 = _MiniBM25(docs)
    scores = bm25.get_scores(_tokenize("nuclear reactor"))
    assert scores[2] > scores[0]
    assert scores[2] > scores[1]
